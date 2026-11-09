"""Evaluate a detector on the held-out TEST split of a YOLO dataset.

  python -m ml.evaluate --weights models/best.pt --data data/datasets/neu-det [--conf 0.25]

Writes models/metrics.json (read by the dashboard) ONLY when real weights were evaluated.
Metrics are computed by app.core.metrics from predictions and ground truth; nothing is estimated.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import cv2

from app.core.boxes import yolo_to_xyxy
from app.core.metrics import GroundTruth, evaluate_detections
from ml.dataset_tools import IMG_EXT, SYNTHETIC_MARKER, _read_names, read_label_file


def run_evaluation(detector, dataset_root: Path, split: str = "test", conf: float = 0.25, iou: float = 0.45,
                   class_names: list[str] | None = None) -> dict:
    root = Path(dataset_root)
    names = class_names or _read_names(root / "data.yaml")
    if not names:
        raise ValueError("class names not found (data.yaml)")
    img_dir, lbl_dir = root / "images" / split, root / "labels" / split
    imgs = sorted(p for p in img_dir.glob("*") if p.suffix.lower() in IMG_EXT) if img_dir.is_dir() else []
    if not imgs:
        raise ValueError(f"no images in {img_dir}; evaluation needs a held-out '{split}' split")
    preds, gts = [], []
    for p in imgs:
        im = cv2.imread(str(p))
        h, w = im.shape[:2]
        preds.append(detector.detect(im, min(conf, 0.001), iou))  # low floor so AP sees the full PR curve
        lbl = lbl_dir / (p.stem + ".txt")
        rows = read_label_file(lbl, len(names))[0] if lbl.is_file() else []
        gts.append([GroundTruth(r[0], yolo_to_xyxy(*r[1:], w, h)) for r in rows])
    res = evaluate_detections(preds, gts, names, conf_threshold=conf)
    res.update({"dataset": str(root), "split": split, "iou_nms": iou, "synthetic_dataset": (root / SYNTHETIC_MARKER).is_file(),
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    return res


def main(argv=None) -> int:  # pragma: no cover - CLI, needs real weights
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out-dir", default="models")
    a = ap.parse_args(argv)
    from app.core.detectors import OnnxYoloDetector, UltralyticsDetector, file_version, load_class_names

    w = Path(a.weights)
    det = OnnxYoloDetector(w, load_class_names(w)) if w.suffix == ".onnx" else UltralyticsDetector(w)
    res = run_evaluation(det, Path(a.data), a.split, a.conf)
    res["weights"] = str(w)
    res["weights_version"] = file_version(w)
    if res["synthetic_dataset"]:
        res["warning"] = "Evaluated on a SYNTHETIC dataset; not representative of real-world performance."
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(res, indent=1))
    try:  # optional confusion-matrix plot
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        m = np.array(res["confusion_matrix"])
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.imshow(m, cmap="Blues")
        labels = res["confusion_matrix_labels"]
        ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right"); ax.set_yticks(range(len(labels)), labels)
        ax.set_xlabel("predicted"); ax.set_ylabel("true")
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                ax.text(j, i, int(m[i, j]), ha="center", va="center")
        fig.tight_layout(); fig.savefig(out / "confusion_matrix.png", dpi=120)
    except ImportError:
        pass
    print(json.dumps({k: res[k] for k in ("n_images", "precision", "recall", "f1", "map50", "map50_95")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
