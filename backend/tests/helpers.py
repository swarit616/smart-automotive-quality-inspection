import cv2
import numpy as np


def png_bytes(w=128, h=96, color=(120, 130, 140)) -> bytes:
    img = np.full((h, w, 3), color, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def jpg_bytes(w=128, h=96) -> bytes:
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()
