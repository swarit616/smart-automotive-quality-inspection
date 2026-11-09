import type { PlcSnapshot } from "../types";

/** Schematic of the simulated station driven only by PLC register/coil values read from the backend. */
export function ConveyorDiagram({ plc }: { plc: PlcSnapshot | null }) {
  const running = !!plc?.conveyor_running;
  const estop = !!plc?.estop;
  const trigger = !!plc?.trigger;
  const pusher = !!plc?.reject_actuator;
  const lastRejected = plc?.component_status === "REJECTED";
  const partX = trigger ? 292 : running ? 120 : 292;
  return (
    <svg className={`conveyor${estop ? " is-estop" : ""}`} viewBox="0 0 640 200" role="img" aria-label={`Conveyor ${running ? "running" : "stopped"}${estop ? ", emergency stop active" : ""}`}>
      <rect x="20" y="120" width="600" height="26" rx="4" className="belt" />
      <g className={running ? "belt-lines run" : "belt-lines"}>
        {Array.from({ length: 31 }).map((_, i) => <line key={i} x1={20 + i * 20} x2={32 + i * 20} y1="133" y2="133" />)}
      </g>
      <rect x="20" y="146" width="600" height="6" className="belt-edge" />
      <g transform="translate(262 28)">
        <rect width="60" height="44" rx="4" className={`camera${trigger ? " active" : ""}`} />
        <circle cx="30" cy="22" r="10" className="lens" />
        <line x1="30" y1="44" x2="30" y2="92" className={trigger ? "beam active" : "beam"} />
      </g>
      <text x="292" y="22" textAnchor="middle" className="diag-label">INSPECTION STATION</text>
      <rect x={partX - 22} y="94" width="44" height="26" rx="3" className={`part${trigger ? " at-station" : ""}`} />
      <g transform="translate(400 150)">
        <rect width="70" height="22" rx="3" className={`pusher${pusher ? " active" : ""}`} />
        <text x="35" y="38" textAnchor="middle" className="diag-label">REJECT PUSHER</text>
      </g>
      <rect x="520" y="158" width="86" height="30" rx="3" className={`bin${lastRejected ? " filled" : ""}`} />
      <text x="563" y="177" textAnchor="middle" className="diag-bin">REJECT BIN</text>
      <g transform="translate(40 40)">
        <circle r="14" className={`estop-lamp${estop ? " on" : ""}`} />
        <text y="32" textAnchor="middle" className="diag-label">E-STOP</text>
      </g>
      <text x="620" y="22" textAnchor="end" className="diag-label">{running ? "CONVEYOR RUNNING" : "CONVEYOR STOPPED"}</text>
    </svg>
  );
}
