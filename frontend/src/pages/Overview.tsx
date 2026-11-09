import { useState } from "react";
import { api, ApiError } from "../api";
import { DefectBars, TrendChart } from "../components/charts";
import { Empty, ErrorNote, Panel, Readout, Spinner, Verdict } from "../components/ui";
import { fmtTime, pct, useAsync } from "../hooks";

export function Overview({ go }: { go: (route: string) => void }) {
  const [includeDemo, setIncludeDemo] = useState(true);
  const [busy, setBusy] = useState(false);
  const [seedError, setSeedError] = useState<string | null>(null);
  const stats = useAsync(() => api.stats(includeDemo), [includeDemo], 10000);

  const seed = async () => {
    setBusy(true);
    setSeedError(null);
    try {
      await api.seedDemo(24);
      stats.reload();
    } catch (e) {
      setSeedError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (stats.loading && !stats.data) return <Spinner />;
  if (stats.error && !stats.data) return <ErrorNote message={stats.error} onRetry={stats.reload} />;
  const s = stats.data!;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Line overview</h1>
        <label className="check">
          <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} />
          Include demo records
        </label>
      </div>
      {s.demo_records > 0 && includeDemo && (
        <div className="note note-demo">{s.demo_records} of these records are DEMO data (synthetic images / demo heuristic) and do not describe real production quality.</div>
      )}
      {stats.error && <ErrorNote message={stats.error} onRetry={stats.reload} />}

      <div className="readouts">
        <Readout label="Inspected" value={s.total} />
        <Readout label="Passed" value={s.passed} tone="pass" />
        <Readout label="Rejected" value={s.rejected} tone="reject" />
        <Readout label="Reject rate" value={pct(s.reject_rate)} />
        <Readout label="Avg. inference" value={s.avg_duration_ms === null ? "–" : s.avg_duration_ms.toFixed(0)} unit={s.avg_duration_ms === null ? undefined : "ms"} />
      </div>

      {s.total === 0 ? (
        <Panel title="No inspections yet">
          <Empty>
            <p>Upload an image on the Inspect screen, run a PLC cycle on the Automation screen, or load clearly labelled demo records.</p>
            <div className="row">
              <button className="btn" onClick={() => go("inspect")}>Inspect an image</button>
              <button className="btn btn-ghost" onClick={seed} disabled={busy}>{busy ? "Loading…" : "Load demo records"}</button>
            </div>
            {seedError && <ErrorNote message={seedError} />}
          </Empty>
        </Panel>
      ) : (
        <div className="grid-2">
          <Panel title="Inspections per day (14 days)" aside={<span className="legend"><i className="sw sw-pass" />passed<i className="sw sw-reject" />rejected</span>}>
            <TrendChart data={s.trend} />
          </Panel>
          <Panel title="Defect distribution">
            <DefectBars data={s.defect_distribution} />
          </Panel>
          <Panel title="Recent activity" className="span-2" aside={<button className="btn btn-ghost" onClick={() => go("history")}>All records</button>}>
            <ul className="activity">
              {s.recent.map((r) => (
                <li key={r.id}>
                  <Verdict decision={r.decision} demo={r.model_mode === "demo"} />
                  <span className="mono">{r.id}</span>
                  <span>{r.top_class ?? "no defect"}</span>
                  <span className="tag">{r.source.replace("_", " ")}</span>
                  <span className="muted">{fmtTime(r.created_at)}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      )}
    </div>
  );
}
