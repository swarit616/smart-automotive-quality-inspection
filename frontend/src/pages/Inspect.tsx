import { useRef, useState } from "react";
import { api, ApiError } from "../api";
import { BoxOverlay, DefectTable, ErrorNote, Panel, Verdict } from "../components/ui";
import type { Inspection, ModelStatus } from "../types";

interface Row { filename: string; error?: string; inspection?: Inspection }

export function Inspect({ model }: { model: ModelStatus | null }) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"annotated" | "overlay">("annotated");
  const [conf, setConf] = useState<string>("");
  const [iou, setIou] = useState<string>("");
  const [drag, setDrag] = useState(false);

  const pick = (list: FileList | null) => {
    if (!list) return;
    setFiles(Array.from(list));
    setRows([]);
    setError(null);
  };

  const run = async () => {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      const up = await api.upload(files);
      const out: Row[] = up.results.filter((r) => !r.ok).map((r) => ({ filename: r.filename, error: r.error }));
      const ok = up.results.filter((r) => r.ok && r.upload_id);
      if (ok.length) {
        const an = await api.analyze(ok.map((r) => r.upload_id!), conf ? Number(conf) : undefined, iou ? Number(iou) : undefined);
        an.results.forEach((r) => {
          const name = ok.find((o) => o.upload_id === r.upload_id)?.filename ?? r.upload_id;
          out.push(r.ok && r.inspection ? { filename: name, inspection: r.inspection } : { filename: name, error: r.error });
        });
      }
      setRows(out);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const blocked = model !== null && !model.ready;

  return (
    <div className="page">
      <div className="page-head"><h1>Image inspection</h1></div>
      <Panel title="Select images">
        <div
          className={`drop${drag ? " drag" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files); }}
        >
          <p>Drop JPG / PNG images here, or</p>
          <button className="btn" onClick={() => input.current?.click()}>Choose files</button>
          <input ref={input} type="file" accept="image/jpeg,image/png" multiple hidden onChange={(e) => pick(e.target.files)} />
          {files.length > 0 && <p className="muted">{files.length} file(s): {files.map((f) => f.name).join(", ")}</p>}
        </div>
        <div className="row row-wrap">
          <label className="field">Confidence override<input inputMode="decimal" placeholder={model ? String(model.confidence_threshold) : "default"} value={conf} onChange={(e) => setConf(e.target.value)} /></label>
          <label className="field">IoU override<input inputMode="decimal" placeholder={model ? String(model.iou_threshold) : "default"} value={iou} onChange={(e) => setIou(e.target.value)} /></label>
          <button className="btn btn-primary" onClick={run} disabled={busy || !files.length || blocked}>{busy ? "Analysing…" : "Analyse"}</button>
        </div>
        {blocked && <ErrorNote message={`Analysis is unavailable: ${model?.reason}`} />}
        {error && <ErrorNote message={error} />}
      </Panel>

      {rows.length > 0 && (
        <div className="row"><span className="muted">Image view:</span>
          <div className="seg">
            <button className={view === "annotated" ? "on" : ""} onClick={() => setView("annotated")}>Annotated image</button>
            <button className={view === "overlay" ? "on" : ""} onClick={() => setView("overlay")}>Original + live boxes</button>
          </div>
        </div>
      )}

      {rows.map((r, i) =>
        r.inspection ? (
          <Panel key={i} className="result" title={r.filename} aside={<span className="mono">{r.inspection.id}</span>}>
            <div className="result-grid">
              <div>
                <h3>Original</h3>
                <img className="photo" src={r.inspection.original_url} alt={`Original ${r.filename}`} />
              </div>
              <div>
                <h3>{view === "annotated" ? "Annotated" : "Boxes drawn in the browser"}</h3>
                {view === "annotated"
                  ? <img className="photo" src={r.inspection.annotated_url} alt={`Annotated ${r.filename}`} />
                  : <BoxOverlay src={r.inspection.original_url} width={r.inspection.width} height={r.inspection.height} defects={r.inspection.defects} alt={`Boxes ${r.filename}`} />}
              </div>
              <div className="verdict-col">
                <Verdict decision={r.inspection.decision} demo={r.inspection.is_demo} size="lg" />
                <p>{r.inspection.reasons}</p>
                <dl className="facts">
                  <dt>Mode</dt><dd>{r.inspection.model_mode === "demo" ? "DEMO (heuristic, not a trained model)" : "Real model"}</dd>
                  <dt>Model</dt><dd>{r.inspection.model_name} · {r.inspection.model_version}</dd>
                  <dt>Thresholds</dt><dd>conf {r.inspection.confidence_threshold} · IoU {r.inspection.iou_threshold}</dd>
                  <dt>Time</dt><dd>{r.inspection.duration_ms?.toFixed(0)} ms</dd>
                </dl>
              </div>
            </div>
            <DefectTable defects={r.inspection.defects} />
            {r.inspection.is_demo && <p className="muted small">Score = normalised contrast from the demo heuristic, not a model confidence.</p>}
          </Panel>
        ) : (
          <Panel key={i} title={r.filename}><ErrorNote message={r.error ?? "Analysis failed"} /></Panel>
        ),
      )}
    </div>
  );
}
