"""Export trained .pt weights to ONNX (CPU-friendly serving through onnxruntime) + class_names.json.

  python -m ml.export_onnx --weights models/best.pt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:  # pragma: no cover - needs ultralytics
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="models/best.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    a = ap.parse_args(argv)
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics is not installed (pip install -r requirements-train.txt)", file=sys.stderr)
        return 3
    model = YOLO(a.weights)
    onnx_path = Path(model.export(format="onnx", imgsz=a.imgsz, simplify=True))
    names = [model.names[i] for i in sorted(model.names)]
    onnx_path.with_suffix(".names.json").write_text(json.dumps(names))
    print(f"exported {onnx_path} (+ {onnx_path.with_suffix('.names.json').name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
