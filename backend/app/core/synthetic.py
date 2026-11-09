"""Synthetic metal-surface images with known defect boxes.

SYNTHETIC / DEMONSTRATION DATA ONLY. These images exist so the pipeline, the PLC workflow and
the tests can run without a real dataset. Results on them say nothing about real-world
defect-detection performance.
"""
from __future__ import annotations

import cv2
import numpy as np

SYNTHETIC_CLASSES = ["scratch", "pit"]


def make_surface(size: tuple[int, int] = (640, 640), seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = size
    base = rng.normal(150, 6, (h, w)).astype(np.float32)
    streaks = cv2.GaussianBlur(rng.normal(0, 14, (h, w)).astype(np.float32), (0, 0), sigmaX=22, sigmaY=0.8)
    yy, xx = np.mgrid[0:h, 0:w]
    gradient = 10 * np.sin(xx / w * np.pi) + 6 * np.cos(yy / h * np.pi)
    img = np.clip(base + streaks + gradient, 0, 255).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def add_defects(img: np.ndarray, seed: int, n_scratch: int = 1, n_pit: int = 1) -> tuple[np.ndarray, list[tuple[int, tuple[int, int, int, int]]]]:
    """Return (image, [(class_id, (x1, y1, x2, y2))...]) with defects drawn onto a copy."""
    rng = np.random.default_rng(seed + 10_000)
    out = img.copy()
    h, w = out.shape[:2]
    labels: list[tuple[int, tuple[int, int, int, int]]] = []
    for _ in range(n_scratch):
        length = int(rng.integers(70, 150))
        ang = float(rng.uniform(0, np.pi))
        cx, cy = int(rng.integers(100, w - 100)), int(rng.integers(100, h - 100))
        dx, dy = int(np.cos(ang) * length / 2), int(np.sin(ang) * length / 2)
        p1, p2 = (cx - dx, cy - dy), (cx + dx, cy + dy)
        color = (235, 235, 235) if rng.random() < 0.5 else (55, 55, 55)
        cv2.line(out, p1, p2, color, 2, cv2.LINE_AA)
        x1, x2 = sorted((p1[0], p2[0]))
        y1, y2 = sorted((p1[1], p2[1]))
        labels.append((0, (max(x1 - 3, 0), max(y1 - 3, 0), min(x2 + 3, w), min(y2 + 3, h))))
    for _ in range(n_pit):
        r = int(rng.integers(7, 14))
        cx, cy = int(rng.integers(60, w - 60)), int(rng.integers(60, h - 60))
        cv2.circle(out, (cx, cy), r, (40, 40, 40), -1, cv2.LINE_AA)
        labels.append((1, (cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2)))
    return out, labels


def make_sample(seed: int, defective: bool, size: tuple[int, int] = (640, 640)):
    surface = make_surface(size, seed)
    if not defective:
        return surface, []
    rng = np.random.default_rng(seed + 77)
    return add_defects(surface, seed, n_scratch=int(rng.integers(1, 3)), n_pit=int(rng.integers(0, 2)))


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()
