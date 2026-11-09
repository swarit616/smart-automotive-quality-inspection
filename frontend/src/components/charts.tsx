import type { Stats } from "../types";
import { Empty } from "./ui";

export function DefectBars({ data }: { data: Stats["defect_distribution"] }) {
  if (!data.length) return <Empty>No defects recorded yet.</Empty>;
  const max = Math.max(...data.map((d) => d.count));
  return (
    <ul className="bars" aria-label="Defect distribution">
      {data.map((d) => (
        <li key={d.class_name}>
          <span className="bars-label">{d.class_name}</span>
          <span className="bars-track"><span className="bars-fill" style={{ width: `${(d.count / max) * 100}%` }} /></span>
          <span className="bars-value">{d.count}</span>
        </li>
      ))}
    </ul>
  );
}

/** Stacked daily columns: passed (bottom) and rejected (top). */
export function TrendChart({ data }: { data: Stats["trend"] }) {
  const W = 560, H = 190, pad = { l: 30, r: 8, t: 10, b: 26 };
  const max = Math.max(4, ...data.map((d) => d.total));
  const bw = (W - pad.l - pad.r) / data.length;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, Math.round(max / 2), max];
  return (
    <svg className="trend" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Inspections per day, passed and rejected">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="grid" />
          <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{t}</text>
        </g>
      ))}
      {data.map((d, i) => {
        const x = pad.l + i * bw + bw * 0.16;
        const w = bw * 0.68;
        return (
          <g key={d.date}>
            <title>{`${d.date}: ${d.total} total, ${d.passed} passed, ${d.rejected} rejected`}</title>
            <rect x={x} y={y(d.passed)} width={w} height={y(0) - y(d.passed)} className="col-pass" />
            <rect x={x} y={y(d.passed + d.rejected)} width={w} height={y(d.passed) - y(d.passed + d.rejected)} className="col-reject" />
            {(i % 2 === 0 || data.length < 8) && <text x={x + w / 2} y={H - 8} textAnchor="middle" className="axis">{d.date.slice(5)}</text>}
          </g>
        );
      })}
    </svg>
  );
}
