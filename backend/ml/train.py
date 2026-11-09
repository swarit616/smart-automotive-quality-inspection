"""Train / fine-tune YOLOv8 on a YOLO-format dataset (requires `pip install -r requirements-train.txt`).

  python -m ml.train --data data/datasets/neu-det/data.yaml --epochs 50 --batch 8 --device auto

CPU is supported (use yolov8n and a small batch); a CUDA GPU is used automatically when present.
Starting from the COCO-pretrained yolov8n.pt downloads that file through Ultralytics; it is a general
object detector, NOT a defect model - it becomes one only after fine-tuning on a defect dataset.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

from ml.dataset_tools import validate_yolo_dataset


def _status(model_dir: Path, **kw) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "training_status.json").write_text(json.dumps({"updated_at": dt.datetime.now(dt.timezone.utc).isoformat(), **kw}, indent=1))


def main(argv=None) -> int:  # pragma: no cover - needs ultralytics + data
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to data.yaml")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--project", default="runs/train")
    ap.add_argument("--name", default="defects")
    ap.add_argument("--model-dir", default="models")
    ap.add_argument("--skip-validation", action="store_true")
    a = ap.parse_args(argv)
    model_dir = Path(a.model_dir)
    data = Path(a.data)
    if not a.skip_validation:
        rep = validate_yolo_dataset(data.parent)
        if not rep["ok"]:
            print(json.dumps(rep, indent=1))
            print("Dataset validation failed; fix the problems above (or pass --skip-validation).", file=sys.stderr)
            return 2
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics is not installed. Run: pip install -r requirements-train.txt", file=sys.stderr)
        return 3
    device = a.device
    if device == "auto":
        import torch

        device = 0 if torch.cuda.is_available() else "cpu"
    cfg = {"data": str(data), "model": a.model, "epochs": a.epochs, "imgsz": a.imgsz, "batch": a.batch, "device": str(device)}
    _status(model_dir, status="running", started_at=dt.datetime.now(dt.timezone.utc).isoformat(), **cfg)
    try:
        model = YOLO(a.model)
        results = model.train(data=str(data), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=device, project=a.project,
                              name=a.name, exist_ok=True, workers=2)
        run_dir = Path(results.save_dir)
        best = run_dir / "weights" / "best.pt"
        model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, model_dir / "best.pt")
        shutil.copy2(run_dir / "args.yaml", model_dir / "training_config.yaml") if (run_dir / "args.yaml").is_file() else None
        names = [model.names[i] for i in sorted(model.names)]
        (model_dir / "class_names.json").write_text(json.dumps(names))
        _status(model_dir, status="completed", finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), run_dir=str(run_dir),
                weights=str(model_dir / "best.pt"), note="Run `python -m ml.evaluate` on the held-out test split before trusting this model.", **cfg)
    except Exception as exc:  # noqa: BLE001
        _status(model_dir, status="failed", error=str(exc), **cfg)
        raise
    print(f"Training finished. Weights copied to {model_dir / 'best.pt'}. Now run: python -m ml.evaluate --weights {model_dir / 'best.pt'} --data {data.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
