import type { ReactNode } from "react";
import type { Decision, Defect, Mode } from "../types";

export function Verdict({ decision, demo, size = "md" }: { decision: Decision; demo?: boolean; size?: "md" | "lg" }) {
  return (
    <span className={`verdict verdict-${decision.toLowerCase()} verdict-${size}${demo ? " is-demo" : ""}`} aria-label={`Decision ${decision}`}>
      {decision}
    </span>
  );
}

export function ModeBanner({ mode, ready, reason }: { mode: Mode | undefined; ready: boolean | undefined; reason?: string }) {
  if (mode === "demo") {
    return (
      <div className="banner banner-demo" role="status">
        <strong>DEMO MODE</strong>
        <span>No trained model is loaded. Detections come from a classical OpenCV heuristic and are for demonstration only.</span>
      </div>
    );
  }
  if (ready === false) {
    return (
      <div className="banner banner-error" role="alert">
        <strong>MODEL NOT READY</strong>
        <span>{reason ?? "Real-model mode is selected but no usable weights were found."}</span>
      </div>
    );
  }
  if (mode === "real") {
    return (
      <div className="banner banner-real" role="status">
        <strong>REAL MODEL MODE</strong>
        <span>Inference runs on trained weights.</span>
      </div>
    );
  }
  return null;
}

export function SimBadge() {
  return <span className="sim-badge" title="Software simulation, not physical hardware">SIMULATED PLC</span>;
}

export function Panel({ title, aside, children, className = "" }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      {(title || aside) && (
        <header className="panel-head">
          {title && <h2>{title}</h2>}
          {aside && <div className="panel-aside">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Readout({ label, value, unit, tone }: { label: string; value: ReactNode; unit?: string; tone?: "pass" | "reject" | "neutral" }) {
  return (
    <div className={`readout tone-${tone ?? "neutral"}`}>
      <div className="readout-label">{label}</div>
      <div className="readout-value">
        {value}
        {unit && <span className="readout-unit">{unit}</span>}
      </div>
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="note note-error" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn btn-ghost" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="spinner" role="status" aria-label={label}><i /><i /><i /></div>;
}

/** Original image with SVG bounding boxes drawn in image-pixel coordinates. */
export function BoxOverlay({ src, width, height, defects, alt }: { src: string; width: number; height: number; defects: Defect[]; alt: string }) {
  const stroke = Math.max(2, Math.round(Math.min(width, height) / 220));
  const font = Math.max(12, Math.round(Math.min(width, height) / 38));
  return (
    <div className="image-frame">
      <img src={src} alt={alt} width={width} height={height} />
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        {defects.map((d, i) => {
          const [x1, y1, x2, y2] = d.bbox;
          const color = d.triggered ? "#e0452b" : "#e8a317";
          const label = `${d.class_name} ${d.confidence.toFixed(2)}`;
          return (
            <g key={i}>
              <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke={color} strokeWidth={stroke} strokeDasharray={d.triggered ? undefined : `${stroke * 3} ${stroke * 2}`} />
              <rect x={x1} y={Math.max(0, y1 - font - 6)} width={label.length * font * 0.58 + 8} height={font + 6} fill={color} />
              <text x={x1 + 4} y={Math.max(font, y1 - 5)} fontSize={font} fill="#fff" fontFamily="sans-serif">{label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function DefectTable({ defects }: { defects: Defect[] }) {
  if (!defects.length) return <Empty>No detections above the detection threshold.</Empty>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th>Class</th><th className="num">Score</th><th>Box (x1,y1,x2,y2)</th><th>Counts toward reject</th></tr>
        </thead>
        <tbody>
          {defects.map((d, i) => (
            <tr key={i}>
              <td>{d.class_name}</td>
              <td className="num">{d.confidence.toFixed(3)}</td>
              <td className="mono">{d.bbox.map((v) => Math.round(v)).join(", ")}</td>
              <td>{d.triggered ? "yes" : "below rule thresholds"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
