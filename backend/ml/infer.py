"""Run the shared detection engine on image files from the command line.

  python -m ml.infer path/to/image_or_dir [--out outputs] [--mode auto|real|demo]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import Settings
from app.core.engine import DetectionEngine
from ml.dataset_tools import IMG_EXT


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--mode", default=None, choices=["auto", "real", "demo"])
    a = ap.parse_args(argv)
    settings = Settings.from_env()
    if a.mode:
        from dataclasses import replace

        settings = replace(settings, detection_mode=a.mode)
    engine = DetectionEngine(settings)
    st = engine.status()
    print(f"mode={st['mode']} ready={st['ready']} ({st['reason']})", file=sys.stderr)
    src = Path(a.source)
    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in IMG_EXT) if src.is_dir() else [src]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in files:
        r = engine.analyze_bytes(f.read_bytes())
        (out / f"{f.stem}_annotated.png").write_bytes(r.annotated_png)
        rows.append({"file": str(f), "decision": r.decision.result, "mode": r.mode, "ms": r.duration_ms,
                     "detections": [d.to_dict() for d in r.detections]})
    print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
