"""PLC integration service: manages the (simulated) PLC connection, event persistence and inspection cycles."""
from __future__ import annotations

import logging
import threading

from ..config import Settings
from ..core import synthetic
from ..db.common import new_id
from ..plc.client import PlcClient, PlcError, SocketModbus, validate_plc_target
from ..plc.controller import InspectionController
from ..plc.registers import REGISTER_DOC
from ..plc.simulator import LOOPBACK, PlcSimulator
from .inspection_service import InspectionService, NotFound

log = logging.getLogger(__name__)
SIM_LABEL = "SIMULATED PLC (software Modbus TCP server) - not physical hardware"


class PlcNotConnected(RuntimeError):
    pass


class PlcService:
    def __init__(self, settings: Settings, inspections: InspectionService, repo, *, client_factory=None):
        self.settings, self.inspections, self.repo = settings, inspections, repo
        self._client_factory = client_factory or self._default_client
        self._client: PlcClient | None = None
        self._sim: PlcSimulator | None = None
        self._target = (settings.plc_host, settings.plc_port)
        self._lock = threading.RLock()
        self._cycle_lock = threading.Lock()
        self._seed = 0

    # -- plumbing ------------------------------------------------------------
    def _default_client(self, host: str, port: int) -> PlcClient:
        low = SocketModbus(host, port, self.settings.plc_unit_id, self.settings.plc_timeout_s)
        return PlcClient(low, retries=self.settings.plc_retries, on_event=self._record_event)

    def _record_event(self, ev: dict) -> None:
        try:
            self.repo.add_plc_event({"type": ev["type"], "ok": ev["ok"], "detail": ev.get("detail"),
                                     "duration_ms": ev.get("duration_ms"), "payload": {k: v for k, v in ev.items() if k not in ("type", "ok", "detail", "duration_ms")}})
        except Exception:  # noqa: BLE001 - never let logging break control flow
            log.exception("could not persist PLC event")

    def shutdown(self) -> None:
        with self._lock:
            if self._client:
                try:
                    self._client.low.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._sim:
                self._sim.stop()
                self._sim = None

    # -- connection ------------------------------------------------------------
    def connect(self, host: str | None = None, port: int | None = None) -> dict:
        with self._lock:
            host, port = host or self._target[0], port or self._target[1]
            validate_plc_target(host, self.settings.plc_allow_non_local_host)
            if self.settings.plc_autostart_simulator and host in LOOPBACK and self._sim is None:
                try:
                    self._sim = PlcSimulator(host, port, self.settings.plc_unit_id).start()
                    port = self._sim.port  # resolves port 0 (ephemeral) used by tests
                    self.repo.add_system_event("INFO", f"embedded PLC SIMULATOR started on {host}:{port}")
                except OSError:
                    log.info("port %s busy; assuming an external simulator is already running", port)
            self._target = (host, port)
            if self._client:
                self._client.low.close()
            self._client = self._client_factory(host, port)
            self._client.connect()
            self._save_machine_status()
            return self.status()

    def disconnect(self) -> dict:
        with self._lock:
            if self._client:
                self._client.close()
                self._client = None
            return self.status()

    def _require(self) -> PlcClient:
        if self._client is None or not self._client.connected:
            raise PlcNotConnected("not connected to the PLC; call POST /api/v1/plc/connect first")
        return self._client

    # -- status ------------------------------------------------------------------
    def status(self) -> dict:
        base = {
            "simulator": True, "label": SIM_LABEL, "target": f"{self._target[0]}:{self._target[1]}",
            "embedded_simulator_running": self._sim is not None, "connected": False, "plc": None, "error": None,
        }
        if self._client and self._client.connected:
            try:
                base["plc"] = self._client.snapshot().to_dict()
                base["connected"] = True
            except PlcError as exc:
                base["error"] = str(exc)
        return base

    def registers(self) -> dict:
        snap = self._require().snapshot().to_dict()
        return {"simulator": True, "label": SIM_LABEL, "register_map": REGISTER_DOC, "values": snap}

    def events(self, limit: int = 50) -> list[dict]:
        return [{**e, "created_at": e["created_at"].isoformat() if hasattr(e["created_at"], "isoformat") else e["created_at"]}
                for e in self.repo.list_plc_events(limit)]

    def _save_machine_status(self) -> None:
        try:
            snap = self._require().snapshot().to_dict()
            self.repo.save_machine_status({"machine_state": snap["machine_state"], "conveyor_running": snap["conveyor_running"],
                                           "estop": snap["estop"], "components": snap["counters"]["components"],
                                           "passed": snap["counters"]["passed"], "rejected": snap["counters"]["rejected"], "simulated": True})
        except (PlcError, PlcNotConnected):
            pass

    # -- control -------------------------------------------------------------------
    def emergency_stop(self, active: bool) -> dict:
        client = self._require()
        client.set_estop(active)
        self.repo.add_system_event("WARNING" if active else "INFO", "SIMULATED emergency stop " + ("PRESSED" if active else "RELEASED"))
        self._save_machine_status()
        return self.status()

    def simulate_cycle(self, scenario: str = "normal", upload_id: str | None = None) -> dict:
        client = self._require()
        if scenario not in ("normal", "defective", "upload"):
            raise ValueError("scenario must be one of: normal, defective, upload")
        if scenario == "upload" and not upload_id:
            raise ValueError("upload_id is required for scenario 'upload'")
        if not self._cycle_lock.acquire(blocking=False):
            raise RuntimeError("an inspection cycle is already running")
        try:
            def image() -> bytes:
                if scenario == "upload":
                    return self.inspections.upload_bytes(upload_id)[0]  # type: ignore[arg-type]
                self._seed += 1
                img, _ = synthetic.make_sample(9000 + self._seed, defective=(scenario == "defective"))
                return synthetic.encode_png(img)

            start_evt = self.repo.add_plc_event({"type": "cycle_start", "ok": True, "detail": f"scenario={scenario}", "payload": {"scenario": scenario}})
            ctl = InspectionController(client, lambda data: self.inspections.outcome_for_plc(data, start_evt["id"]))
            result = ctl.run_cycle(image)
            self.repo.add_plc_event({"type": "cycle_end", "ok": result.status == "completed", "detail": f"{result.status}; decision={result.decision}",
                                     "inspection_id": result.inspection_id, "payload": {"cycle": start_evt["id"], "failsafe": result.failsafe}})
            self._save_machine_status()
            out = result.to_dict()
            out["scenario"] = scenario
            out["scenario_note"] = ("Scenario only selects which synthetic image is fed in; PASS/REJECT always comes from the detection engine."
                                    if scenario != "upload" else "Using the uploaded image.")
            out["simulator"] = True
            return out
        finally:
            self._cycle_lock.release()
