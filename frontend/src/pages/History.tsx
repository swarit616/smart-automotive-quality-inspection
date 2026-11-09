import { useEffect, useState } from "react";
import { api } from "../api";
import { DefectTable, Empty, ErrorNote, Panel, Spinner, Verdict } from "../components/ui";
import { fmtTime, useAsync } from "../hooks";

const PAGE = 15;

export function History({ focusId }: { focusId?: string | null }) {
  const [q, setQ] = useState("");
  const [decision, setDecision] = useState("");
  const [source, setSource] = useState("");
  const [cls, setCls] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [includeDemo, setIncludeDemo] = useState(true);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(focusId ?? null);

  useEffect(() => setOffset(0), [q, decision, source, cls, from, to, includeDemo]);

  const list = useAsync(
    () => api.inspections({
      q, decision, source, class_name: cls, include_demo: includeDemo, limit: PAGE, offset,
      date_from: from ? new Date(from + "T00:00:00").toISOString() : undefined,
      date_to: to ? new Date(to + "T23:59:59").toISOString() : undefined,
    }),
    [q, decision, source, cls, from, to, includeDemo, offset],
  );
  const detail = useAsync(() => (selected ? api.inspection(selected) : Promise.resolve(null)), [selected]);
  const data = list.data;

  return (
    <div className="page">
      <div className="page-head"><h1>Inspection history</h1></div>
      <Panel>
        <div className="filters">
          <label className="field">Search<input placeholder="id, file name or class" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <label className="field">Decision
            <select value={decision} onChange={(e) => setDecision(e.target.value)}><option value="">All</option><option>PASS</option><option>REJECT</option></select>
          </label>
          <label className="field">Source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All</option><option value="upload">Upload</option><option value="plc_cycle">PLC cycle</option><option value="demo_seed">Demo seed</option>
            </select>
          </label>
          <label className="field">Defect class<input placeholder="e.g. scratch" value={cls} onChange={(e) => setCls(e.target.value)} /></label>
          <label className="field">From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="field">To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <label className="check"><input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />Include demo records</label>
        </div>
      </Panel>

      {list.error && <ErrorNote message={list.error} onRetry={list.reload} />}
      {list.loading && !data ? <Spinner /> : data && (
        <Panel title={`${data.total} record(s)`}>
          {data.items.length === 0 ? <Empty>No inspections match these filters.</Empty> : (
            <div className="table-wrap">
              <table className="table table-click">
                <thead><tr><th>Time</th><th>ID</th><th>Result</th><th>Top defect</th><th className="num">Defects</th><th>Source</th><th>Mode</th></tr></thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.id} tabIndex={0} className={selected === r.id ? "sel" : ""} onClick={() => setSelected(r.id)} onKeyDown={(e) => e.key === "Enter" && setSelected(r.id)}>
                      <td>{fmtTime(r.created_at)}</td>
                      <td className="mono">{r.id}</td>
                      <td><Verdict decision={r.decision} demo={r.is_demo} /></td>
                      <td>{r.top_class ?? "–"}{r.top_confidence !== null && r.top_confidence !== undefined ? ` (${r.top_confidence.toFixed(2)})` : ""}</td>
                      <td className="num">{r.defect_count}</td>
                      <td>{r.source.replace("_", " ")}</td>
                      <td>{r.model_mode === "demo" ? "DEMO" : "real"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="pager">
            <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
            <span className="muted">{data.total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
            <button className="btn btn-ghost" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
          </div>
        </Panel>
      )}

      {selected && (
        <Panel title={`Inspection ${selected}`} aside={<button className="btn btn-ghost" onClick={() => setSelected(null)}>Close</button>}>
          {detail.error && <ErrorNote message={detail.error} />}
          {detail.data && (
            <>
              <div className="result-grid">
                <div><h3>Original</h3><img className="photo" src={detail.data.original_url} alt="Original" /></div>
                <div><h3>Annotated</h3><img className="photo" src={detail.data.annotated_url} alt="Annotated" /></div>
                <div className="verdict-col">
                  <Verdict decision={detail.data.decision} demo={detail.data.is_demo} size="lg" />
                  <p>{detail.data.reasons}</p>
                  <dl className="facts">
                    <dt>Recorded</dt><dd>{fmtTime(detail.data.created_at)}</dd>
                    <dt>File</dt><dd>{detail.data.original_filename ?? "–"}</dd>
                    <dt>Model</dt><dd>{detail.data.model_name} · {detail.data.model_version}</dd>
                    <dt>Mode</dt><dd>{detail.data.model_mode === "demo" ? "DEMO" : "Real model"}</dd>
                    <dt>Thresholds</dt><dd>conf {detail.data.confidence_threshold} · IoU {detail.data.iou_threshold}</dd>
                    <dt>Processing</dt><dd>{detail.data.duration_ms?.toFixed(0)} ms</dd>
                    <dt>Source</dt><dd>{detail.data.source}{detail.data.plc_event_id ? ` · ${detail.data.plc_event_id}` : ""}</dd>
                  </dl>
                </div>
              </div>
              <DefectTable defects={detail.data.defects} />
            </>
          )}
        </Panel>
      )}
    </div>
  );
}
