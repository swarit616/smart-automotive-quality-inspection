"""Draw detections on a copy of the image."""
from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from .detectors import Detection

_PALETTE = [(42, 64, 214), (0, 140, 255), (30, 160, 60), (200, 120, 20), (170, 50, 150), (20, 180, 200)]


def annotate(image_bgr: np.ndarray, detections: Sequence[Detection], decision: str, *, demo: bool) -> np.ndarray:
    out = image_bgr.copy()
    h, w = out.shape[:2]
    thick = max(2, round(min(h, w) / 280))
    font_scale = max(0.45, min(h, w) / 900)
    for d in detections:
        color = _PALETTE[d.class_id % len(_PALETTE)]
        p1, p2 = (int(d.bbox.x1), int(d.bbox.y1)), (int(d.bbox.x2), int(d.bbox.y2))
        cv2.rectangle(out, p1, p2, color, thick)
        label = f"{d.class_name} {d.confidence:.2f}"
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        y0 = max(p1[1] - th - base - 2, 0)
        cv2.rectangle(out, (p1[0], y0), (p1[0] + tw + 6, y0 + th + base + 4), color, -1)
        cv2.putText(out, label, (p1[0] + 3, y0 + th + 1), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 1, cv2.LINE_AA)
    banner_color = (60, 140, 30) if decision == "PASS" else (40, 60, 210)
    text = f"{decision}" + ("  |  DEMO MODE - not a trained model" if demo else "")
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale * 1.1, 2)
    cv2.rectangle(out, (0, h - th - base - 12), (tw + 16, h), banner_color, -1)
    cv2.putText(out, text, (8, h - base - 6), cv2.FONT_HERSHEY_SIMPLEX, font_scale * 1.1, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def encode_png(image_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image_bgr)
    if not ok:  # pragma: no cover
        raise RuntimeError("failed to encode annotated image")
    return buf.tobytes()
