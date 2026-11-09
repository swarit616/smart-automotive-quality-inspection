#!/usr/bin/env python3
"""Five-minute demonstration of both projects, in-process (no web server required).

  python scripts/demo.py            # uses DEMO MODE unless real weights are configured
  python scripts/demo.py --keep     # keep the generated data in ./demo_output

Project A: image -> preprocessing -> detector -> PASS/REJECT -> annotated image -> database record
Project B: simulated PLC (Modbus TCP) -> trigger -> same engine -> PASS/REJECT signal -> PLC counters
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.core import synthetic  # noqa: E402
from app.db import MemoryRepository  # noqa: E402
from app.services.container import build_services  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--mode", default="auto", choices=["auto", "real", "demo"])
    a = ap.parse_args()
    out = ROOT / "demo_output" if a.keep else Path(tempfile.mkdtemp(prefix="inspection-demo-"))
    out.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings.from_env(), data_dir=out, model_dir=ROOT / "models", detection_mode=a.mode,
                       database_url="sqlite://", plc_port=0, plc_host="127.0.0.1", plc_autostart_simulator=True)
    s = build_services(settings, MemoryRepository())
    st = s.model.status()
    print(f"== Model: mode={st['mode']} ready={st['ready']}\n   {st['reason']}")
    if st["mode"] == "demo":
        print("   *** DEMO MODE: heuristic detections on SYNTHETIC images; this is not a trained defect model. ***")

    print("\n== Project A - image inspection")
    for name, defective in (("clean part", False), ("scratched part", True)):
        img, truth = synthetic.make_sample(7, defective)
        rec = s.inspections.analyze_bytes(synthetic.encode_png(img), f"{name}.png")
        print(f"   {name:15s} -> {rec['decision']:6s} defects={rec['defect_count']} top={rec['top_class']} "
              f"({rec['duration_ms']:.0f} ms) id={rec['id']}")
        (out / f"{name.replace(' ', '_')}_annotated.png").write_bytes(s.inspections.image_path(rec["id"], "annotated").read_bytes())

    print("\n== Project B - PLC-integrated cycle (SIMULATED PLC over Modbus TCP)")
    plc = s.plc.connect()
    print(f"   connected={plc['connected']} target={plc['target']} ({plc['label']})")
    for scenario in ("normal", "defective"):
        r = s.plc.simulate_cycle(scenario)
        print(f"   cycle[{scenario:9s}] status={r['status']} decision={r['decision']} component={r['plc_after']['component_status']} ({r['duration_ms']:.0f} ms)")
        for e in r["events"]:
            print(f"       +{e['t_ms']:7.1f} ms  {e['event']:18s} {e['detail']}")
    s.plc.emergency_stop(True)
    r = s.plc.simulate_cycle("normal")
    print(f"   cycle during E-STOP -> {r['status']}")
    s.plc.emergency_stop(False)
    c = s.plc.status()["plc"]["counters"]
    print(f"   PLC counters: components={c['components']} passed={c['passed']} rejected={c['rejected']}")

    print("\n== Dashboard statistics (from the database)")
    stats = s.repo.stats()
    print(json.dumps({k: stats[k] for k in ("total", "passed", "rejected", "reject_rate", "defect_distribution")}, indent=2))
    s.plc.shutdown()
    print(f"\nAnnotated images written to: {out}")
    if not a.keep:
        print("(temporary directory; run with --keep to retain it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
