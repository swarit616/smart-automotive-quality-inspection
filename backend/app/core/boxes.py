"""Bounding-box geometry: validation, IoU and non-maximum suppression (NMS).

Boxes are absolute pixel coordinates in (x1, y1, x2, y2) order, origin top-left.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


class BoxError(ValueError):
    """Raised when a bounding box is geometrically invalid."""


@dataclass(frozen=True)
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)

    def as_list(self) -> list[float]:
        return [round(float(v), 2) for v in (self.x1, self.y1, self.x2, self.y2)]


def validate_box(box: BBox, image_w: int, image_h: int, *, clip: bool = False) -> BBox:
    """Validate (and optionally clip) a box against image bounds.

    Raises BoxError for NaN/inf, inverted or zero-area boxes, or boxes entirely
    outside the image. With clip=True, boxes partly outside are clipped.
    """
    vals = (box.x1, box.y1, box.x2, box.y2)
    if not all(np.isfinite(v) for v in vals):
        raise BoxError("box contains NaN or infinite values")
    if box.x2 <= box.x1 or box.y2 <= box.y1:
        raise BoxError("box has non-positive width or height")
    inside = box.x1 >= 0 and box.y1 >= 0 and box.x2 <= image_w and box.y2 <= image_h
    if not inside:
        if not clip:
            raise BoxError("box extends outside the image")
        box = BBox(max(box.x1, 0.0), max(box.y1, 0.0), min(box.x2, float(image_w)), min(box.y2, float(image_h)))
        if box.x2 <= box.x1 or box.y2 <= box.y1:
            raise BoxError("box lies entirely outside the image")
    return box


def validate_yolo_box(cx: float, cy: float, w: float, h: float) -> None:
    """Validate a normalised YOLO-format box (all values in [0, 1], w/h > 0)."""
    for name, v in (("cx", cx), ("cy", cy), ("w", w), ("h", h)):
        if not np.isfinite(v):
            raise BoxError(f"{name} is not finite")
        if v < 0 or v > 1:
            raise BoxError(f"{name}={v} outside [0, 1]")
    if w <= 0 or h <= 0:
        raise BoxError("width/height must be > 0")
    if cx - w / 2 < -1e-6 or cx + w / 2 > 1 + 1e-6 or cy - h / 2 < -1e-6 or cy + h / 2 > 1 + 1e-6:
        raise BoxError("box extends beyond the image")


def yolo_to_xyxy(cx: float, cy: float, w: float, h: float, image_w: int, image_h: int) -> BBox:
    return BBox((cx - w / 2) * image_w, (cy - h / 2) * image_h, (cx + w / 2) * image_w, (cy + h / 2) * image_h)


def iou(a: BBox, b: BBox) -> float:
    """Intersection over Union of two boxes; 0.0 when they do not overlap."""
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(ix2 - ix1, 0.0) * max(iy2 - iy1, 0.0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression. boxes: (N,4) xyxy; returns kept indices, best first."""
    if len(boxes) == 0:
        return []
    boxes = np.asarray(boxes, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(xx2 - xx1, 0) * np.maximum(yy2 - yy1, 0)
        union = areas[i] + areas[rest] - inter
        overlap = np.where(union > 0, inter / union, 0.0)
        order = rest[overlap <= iou_threshold]
    return keep


def class_aware_nms(boxes: np.ndarray, scores: np.ndarray, class_ids: Sequence[int], iou_threshold: float) -> list[int]:
    """NMS applied independently per class (boxes of different classes never suppress each other)."""
    class_ids = np.asarray(class_ids)
    kept: list[int] = []
    for c in np.unique(class_ids):
        idx = np.where(class_ids == c)[0]
        for k in nms(boxes[idx], scores[idx], iou_threshold):
            kept.append(int(idx[k]))
    kept.sort(key=lambda i: -float(scores[i]))
    return kept
