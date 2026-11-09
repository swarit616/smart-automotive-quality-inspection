"""Detection metrics computed from predictions and ground truth (NumPy only).

Precision/recall/F1 are reported at a fixed confidence threshold and IoU 0.5.
AP uses COCO-style 101-point interpolation; mAP50-95 averages IoU 0.50:0.05:0.95.
Only classes that have at least one ground-truth box contribute to the mAP averages.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .boxes import BBox, iou
from .detectors import Detection


@dataclass(frozen=True)
class GroundTruth:
    class_id: int
    bbox: BBox


def _average_precision(tp: np.ndarray, n_gt: int) -> float:
    if n_gt == 0:
        return float("nan")
    if len(tp) == 0:
        return 0.0
    tp_c = np.cumsum(tp)
    fp_c = np.cumsum(1 - tp)
    recall = tp_c / n_gt
    precision = tp_c / np.maximum(tp_c + fp_c, 1e-12)
    for i in range(len(precision) - 2, -1, -1):  # monotone precision envelope (COCO-style, no sentinel)
        precision[i] = max(precision[i], precision[i + 1])
    grid = np.linspace(0, 1, 101)
    idx = np.searchsorted(recall, grid, side="left")
    vals = np.array([precision[j] if j < len(precision) else 0.0 for j in idx])
    return float(vals.mean())


def _match_class(preds: Sequence[Sequence[Detection]], gts: Sequence[Sequence[GroundTruth]], cls: int, thr: float) -> tuple[np.ndarray, int]:
    entries = [(d.confidence, img, d) for img, dets in enumerate(preds) for d in dets if d.class_id == cls]
    entries.sort(key=lambda e: -e[0])
    used = {img: [False] * len(g) for img, g in enumerate(gts)}
    n_gt = sum(1 for g in gts for x in g if x.class_id == cls)
    tp = np.zeros(len(entries))
    for k, (_, img, d) in enumerate(entries):
        best, best_j = 0.0, -1
        for j, g in enumerate(gts[img]):
            if g.class_id != cls or used[img][j]:
                continue
            v = iou(d.bbox, g.bbox)
            if v > best:
                best, best_j = v, j
        if best_j >= 0 and best >= thr:
            used[img][best_j] = True
            tp[k] = 1
    return tp, n_gt


def evaluate_detections(
    preds: Sequence[Sequence[Detection]],
    gts: Sequence[Sequence[GroundTruth]],
    class_names: Sequence[str],
    conf_threshold: float = 0.25,
) -> dict:
    if len(preds) != len(gts):
        raise ValueError("preds and gts must have one entry per image")
    nc = len(class_names)
    thresholds = np.round(np.arange(0.5, 0.96, 0.05), 2)
    ap = np.full((nc, len(thresholds)), np.nan)
    for c in range(nc):
        for t_i, thr in enumerate(thresholds):
            tp, n_gt = _match_class(preds, gts, c, float(thr))
            ap[c, t_i] = _average_precision(tp, n_gt)
    has_gt = ~np.isnan(ap[:, 0])
    map50 = float(np.nanmean(ap[has_gt, 0])) if has_gt.any() else float("nan")
    map5095 = float(np.nanmean(ap[has_gt])) if has_gt.any() else float("nan")

    filt = [[d for d in dets if d.confidence >= conf_threshold] for dets in preds]
    per_class = {}
    tot_tp = tot_fp = tot_fn = 0
    for c in range(nc):
        tp_arr, n_gt = _match_class(filt, gts, c, 0.5)
        tp = int(tp_arr.sum())
        n_pred = sum(1 for dets in filt for d in dets if d.class_id == c)
        fp, fn = n_pred - tp, n_gt - tp
        tot_tp, tot_fp, tot_fn = tot_tp + tp, tot_fp + fp, tot_fn + fn
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        per_class[class_names[c]] = {
            "gt_instances": n_gt, "tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "ap50": None if np.isnan(ap[c, 0]) else round(float(ap[c, 0]), 4),
            "ap50_95": None if np.isnan(ap[c]).all() else round(float(np.nanmean(ap[c])), 4),
        }
    precision = tot_tp / (tot_tp + tot_fp) if tot_tp + tot_fp else 0.0
    recall = tot_tp / (tot_tp + tot_fn) if tot_tp + tot_fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n_images": len(gts),
        "n_gt_instances": int(sum(len(g) for g in gts)),
        "conf_threshold": conf_threshold,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "map50": None if np.isnan(map50) else round(map50, 4),
        "map50_95": None if np.isnan(map5095) else round(map5095, 4),
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(filt, gts, nc),
        "confusion_matrix_labels": list(class_names) + ["background"],
    }


def confusion_matrix(preds: Sequence[Sequence[Detection]], gts: Sequence[Sequence[GroundTruth]], nc: int, iou_thr: float = 0.5) -> list[list[int]]:
    """Rows = true class, columns = predicted class, last index = background (missed / spurious)."""
    m = np.zeros((nc + 1, nc + 1), dtype=int)
    for dets, gt in zip(preds, gts):
        used = set()
        for d in sorted(dets, key=lambda x: -x.confidence):
            best, best_j = 0.0, -1
            for j, g in enumerate(gt):
                if j in used:
                    continue
                v = iou(d.bbox, g.bbox)
                if v > best:
                    best, best_j = v, j
            if best_j >= 0 and best >= iou_thr:
                used.add(best_j)
                m[gt[best_j].class_id, d.class_id] += 1
            else:
                m[nc, d.class_id] += 1
        for j, g in enumerate(gt):
            if j not in used:
                m[g.class_id, nc] += 1
    return m.tolist()
