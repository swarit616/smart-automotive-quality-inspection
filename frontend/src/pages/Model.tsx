import { Fragment, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Empty, ErrorNote, Panel, Spinner } from "../components/ui";
import type { ModelStatus } from "../types";

const METRIC_ROWS: [string, string][] = [
  ["precision", "Precision"], ["recall", "Recall"], ["f1", "F1 score"], ["map50", "mAP@0.50"], ["map50_95", "mAP@0.50:0.95"],
];

export function Model({ model, error, reload }: { model: ModelStatus | null; error: string | null; reload: () => void }) {
  const [conf, setConf] = useState("");
  const [iou, setIou] = useState("");
  const [maxDef, setMaxDef] = useState("");
  const [minConf, setMinConf] = useState("");
  const [mode, setMode] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!model) return;
    setConf(String(model.confidence_threshold));
    setIou(String(model.iou_threshold));
    setMaxDef(String(model.decision_rules.max_defects_allowed));
    setMinConf(String(model.decision_rules.min_confidence));
    setMode(model.requested_mode);
  }, [model?.confidence_threshold, model?.iou_threshold, model?.requested_mode, model?.decision_rules.max_defects_allowed, model?.decision_rules.min_confidence]);

  if (error && !model) return <ErrorNote message={error} onRetry={reload} />;
  if (!model) return <Spinner />;

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.modelConfig({
        confidence_threshold: Number(conf), iou_threshold: Number(iou), mode,
        decision_rules: { min_confidence: Number(minConf), max_defects_allowed: Number(maxDef) }, reload: true,
      });
      setMsg({ ok: true, text: "Configuration saved." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const m = model.metrics as Record<string, number | string | boolean | null> | null;
  const t = model.training as Record<string, string | number> | null;

  return (
    <div className="page">
      <div className="page-head"><h1>Model information</h1></div>
      <div className="grid-2">
        <Panel title="Status">
          <dl className="facts">
            <dt>Operating mode</dt><dd><strong>{model.mode === "real" ? "REAL MODEL" : model.mode === "demo" ? "DEMO" : "none"}</strong> <span className="muted">(requested: {model.requested_mode})</span></dd>
            <dt>Ready</dt><dd><span className={`dot ${model.ready ? "dot-on" : "dot-off"}`}>{model.ready ? "ready" : "not ready"}</span></dd>
            <dt>Reason</dt><dd>{model.reason}</dd>
            <dt>Model</dt><dd>{model.model_name ?? "–"}</dd>
            <dt>Version (weights hash)</dt><dd className="mono">{model.model_version ?? "–"}</dd>
            <dt>Weights file</dt><dd className="mono">{model.weights_path} {model.weights_present ? "" : "(not found)"}</dd>
            <dt>Classes</dt><dd>{model.class_names.length ? model.class_names.join(", ") : "–"}</dd>
            <dt>Input size</dt><dd>{model.image_size}px</dd>
          </dl>
          {model.demo_notice && <div className="note note-demo">{model.demo_notice}</div>}
          {model.setup_instructions && <div className="note">{model.setup_instructions}</div>}
        </Panel>

        <Panel title="Thresholds & decision rules">
          <div className="form-grid">
            <label className="field">Detection confidence<input value={conf} onChange={(e) => setConf(e.target.value)} inputMode="decimal" /></label>
            <label className="field">NMS IoU threshold<input value={iou} onChange={(e) => setIou(e.target.value)} inputMode="decimal" /></label>
            <label className="field">Reject if confidence ≥<input value={minConf} onChange={(e) => setMinConf(e.target.value)} inputMode="decimal" /></label>
            <label className="field">Defects tolerated<input value={maxDef} onChange={(e) => setMaxDef(e.target.value)} inputMode="numeric" /></label>
            <label className="field">Mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="auto">auto (real if weights exist, else demo)</option>
                <option value="real">real only</option>
                <option value="demo">demo only</option>
              </select>
            </label>
          </div>
          <div className="row">
            <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save & reload"}</button>
          </div>
          {msg && (msg.ok ? <div className="note note-ok">{msg.text}</div> : <ErrorNote message={msg.text} />)}
        </Panel>

        <Panel title="Evaluation metrics">
          {model.mode !== "real" ? (
            <Empty>No evaluation metrics: they are only shown for a real model that has been evaluated on a held-out test split (<code>python -m ml.evaluate</code>). Demo mode has no accuracy figures.</Empty>
          ) : !m ? (
            <Empty>No <code>models/metrics.json</code> found. Run <code>python -m ml.evaluate</code> to produce measured metrics for these weights.</Empty>
          ) : (
            <>
              <table className="table compact">
                <tbody>
                  {METRIC_ROWS.map(([k, label]) => <tr key={k}><td>{label}</td><td className="num mono">{typeof m[k] === "number" ? (m[k] as number).toFixed(3) : "–"}</td></tr>)}
                </tbody>
              </table>
              <p className="muted small">{String(m.n_images)} test images · confidence ≥ {String(m.conf_threshold)} · dataset {String(m.dataset)} · {String(m.generated_at)}</p>
              {m.synthetic_dataset && <div className="note note-demo">These metrics were measured on a SYNTHETIC dataset and do not represent real-world performance.</div>}
              {model.metrics_warning && <ErrorNote message={model.metrics_warning} />}
            </>
          )}
        </Panel>

        <Panel title="Training status">
          {!t ? <Empty>No training run recorded. See docs/MODEL_TRAINING.md (<code>python -m ml.train</code>).</Empty> : (
            <dl className="facts">
              {Object.entries(t).filter(([, v]) => typeof v !== "object").map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd className="mono">{String(v)}</dd></Fragment>)}
            </dl>
          )}
        </Panel>
      </div>
    </div>
  );
}
