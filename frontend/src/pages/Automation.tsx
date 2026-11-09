import { useState } from "react";
import { api, ApiError } from "../api";
import { ConveyorDiagram } from "../components/ConveyorDiagram";
import { Empty, ErrorNote, Panel, Readout, SimBadge, Verdict } from "../components/ui";
import { fmtTime, useAsync } from "../hooks";
import type { CycleResult } from "../types";

export function Automation({ goToInspection }: { goToInspection: (id: string) => void }) {
  const status = useAsync(api.plcStatus, [], 1500);
  const connected = status.data?.connected ?? false;
  const regs = useAsync(() => (connected ? api.plcRegisters() : Promise.resolve(null)), [connected], 1500);
  const events = useAsync(api.plcEvents, [], 4000);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cycle, setCycle] = useState<CycleResult | null>(null);

  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
      status.reload();
      events.reload();
      regs.reload();
    }
  };

  const plc = status.data?.plc ?? null;
  const estop = !!plc?.estop;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Industrial automation</h1>
        <SimBadge />
      </div>
      <div className="note note-sim">
        This screen drives a <strong>software PLC simulator</strong> over Modbus TCP. It is not connected to physical equipment, and the
        e-stop below is a simulated input, not a safety function.
      </div>
      {status.error && <ErrorNote message={status.error} onRetry={status.reload} />}
      {error && <ErrorNote message={error} />}

      <div className="grid-2">
        <Panel title="Connection" aside={<span className={`dot ${connected ? "dot-on" : "dot-off"}`}>{connected ? "connected" : "disconnected"}</span>}>
          <dl className="facts">
            <dt>Target</dt><dd className="mono">{status.data?.target ?? "–"}</dd>
            <dt>Type</dt><dd>{status.data?.label ?? "–"}</dd>
            <dt>Embedded simulator</dt><dd>{status.data?.embedded_simulator_running ? "running in the backend" : "not started by the backend"}</dd>
            <dt>Machine state</dt><dd><strong>{plc?.machine_state ?? "–"}</strong></dd>
            <dt>Heartbeat</dt><dd className="mono">{plc?.heartbeat ?? "–"}</dd>
          </dl>
          {status.data?.error && <ErrorNote message={`PLC error: ${status.data.error}`} />}
          <div className="row">
            {!connected
              ? <button className="btn btn-primary" disabled={busy !== null} onClick={() => act("connect", api.plcConnect)}>{busy === "connect" ? "Connecting…" : "Connect to simulator"}</button>
              : <button className="btn" disabled={busy !== null} onClick={() => act("disconnect", api.plcDisconnect)}>Disconnect</button>}
          </div>
        </Panel>

        <Panel title="Station">
          <ConveyorDiagram plc={plc} />
          <div className="row row-wrap">
            <button className={`btn ${estop ? "btn-warn" : "btn-danger"}`} disabled={!connected || busy !== null} onClick={() => act("estop", () => api.plcEstop(!estop))}>
              {estop ? "Release emergency stop" : "Press emergency stop"}
            </button>
            <span className={`estop-state${estop ? " on" : ""}`}>{estop ? "EMERGENCY STOP ACTIVE — cycles blocked" : "e-stop released"}</span>
          </div>
        </Panel>
      </div>

      <div className="readouts">
        <Readout label="Parts presented" value={plc?.counters.components ?? "–"} />
        <Readout label="PASS signals" value={plc?.counters.passed ?? "–"} tone="pass" />
        <Readout label="REJECT signals" value={plc?.counters.rejected ?? "–"} tone="reject" />
        <Readout label="Last component" value={plc?.component_status.replace("_", " ") ?? "–"} />
        <Readout label="Last result" value={plc?.inspection_result ?? "–"} />
      </div>

      <Panel title="Run a simulated inspection cycle" aside={<span className="muted small">part arrives → PLC trigger → shared AI engine → PASS/REJECT → PLC</span>}>
        <div className="row row-wrap">
          <button className="btn btn-primary" disabled={!connected || busy !== null} onClick={() => act("cycle-normal", async () => setCycle(await api.plcCycle("normal")))}>
            {busy === "cycle-normal" ? "Running…" : "Cycle with clean synthetic part"}
          </button>
          <button className="btn" disabled={!connected || busy !== null} onClick={() => act("cycle-defective", async () => setCycle(await api.plcCycle("defective")))}>
            {busy === "cycle-defective" ? "Running…" : "Cycle with defective synthetic part"}
          </button>
        </div>
        <p className="muted small">The scenario only chooses which synthetic image is presented. The decision is produced by the detection engine, not predetermined; with a real model the synthetic images may not behave like real parts.</p>
        {cycle && (
          <div className="cycle">
            <div className="row">
              {cycle.decision ? <Verdict decision={cycle.decision} size="lg" /> : <span className="tag">{cycle.status}</span>}
              <div>
                <div><strong>{cycle.status.replace(/_/g, " ")}</strong>{cycle.failsafe_reject && " · fail-safe REJECT (inspection error)"}</div>
                <div className="muted small">{cycle.duration_ms.toFixed(0)} ms · PLC cycle {cycle.plc_cycle_id ?? "–"}{cycle.plc_after ? ` · component ${cycle.plc_after.component_status}` : ""}</div>
                {cycle.inspection_id && <button className="link" onClick={() => goToInspection(cycle.inspection_id!)}>Open inspection {cycle.inspection_id}</button>}
              </div>
            </div>
            <ol className="timeline">
              {cycle.events.map((e, i) => <li key={i}><span className="mono">+{e.t_ms.toFixed(0)} ms</span><strong>{e.event.replace(/_/g, " ")}</strong><span>{e.detail}</span></li>)}
            </ol>
          </div>
        )}
      </Panel>

      <div className="grid-2">
        <Panel title="Register map & live values">
          {!regs.data ? <Empty>Connect to the simulator to read registers.</Empty> : (
            <div className="table-wrap">
              <table className="table compact">
                <thead><tr><th>Type</th><th className="num">Addr</th><th>Name</th><th className="num">Value</th><th>Access</th></tr></thead>
                <tbody>
                  {regs.data.register_map.map((r) => {
                    const v = r.type === "coil" ? regs.data!.values.coils[r.name] : regs.data!.values.registers[r.name];
                    return (
                      <tr key={r.type + r.address} title={r.description}>
                        <td>{r.type === "coil" ? "coil" : "holding"}</td>
                        <td className="num mono">{r.address}</td>
                        <td>{r.name}</td>
                        <td className="num mono">{typeof v === "boolean" ? (v ? "1" : "0") : v}</td>
                        <td>{r.access}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Communication & cycle events">
          {!events.data || events.data.items.length === 0 ? <Empty>No PLC events yet.</Empty> : (
            <ul className="eventlog">
              {events.data.items.map((e) => (
                <li key={e.id} className={e.ok ? "" : "bad"}>
                  <span className="mono">{fmtTime(e.created_at)}</span>
                  <strong>{e.type}</strong>
                  <span>{e.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
