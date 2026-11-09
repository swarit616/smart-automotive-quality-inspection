"""OpenCV image validation and preprocessing.

The original upload bytes are never modified; preprocessing works on decoded copies.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

ALLOWED_FORMATS = {"jpeg": ".jpg", "png": ".png"}


class ImageValidationError(ValueError):
    """Raised when uploaded bytes are not an acceptable image."""


@dataclass(frozen=True)
class ValidatedImage:
    image: np.ndarray  # BGR uint8, shape (H, W, 3)
    fmt: str  # "jpeg" | "png"
    width: int
    height: int
    size_bytes: int

    @property
    def extension(self) -> str:
        return ALLOWED_FORMATS[self.fmt]


def sniff_format(data: bytes) -> str | None:
    """Detect format from magic bytes (the filename/content-type are never trusted)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def _header_dimensions(data: bytes, fmt: str) -> tuple[int, int] | None:
    """Read dimensions cheaply from the header so decompression bombs are rejected before decoding."""
    try:
        if fmt == "png" and len(data) >= 24:
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if fmt == "jpeg":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5 : i + 7], "big")
                    w = int.from_bytes(data[i + 7 : i + 9], "big")
                    return w, h
                seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
                i += 2 + seg_len
    except Exception:  # noqa: BLE001 - header parsing is best-effort
        return None
    return None


def validate_and_decode(data: bytes, *, max_bytes: int, max_pixels: int, min_side: int = 32) -> ValidatedImage:
    """Validate type, size and dimensions, then decode to a BGR array."""
    if not data:
        raise ImageValidationError("empty file")
    if len(data) > max_bytes:
        raise ImageValidationError(f"file too large ({len(data)} bytes > {max_bytes})")
    fmt = sniff_format(data)
    if fmt is None:
        raise ImageValidationError("unsupported file type; only JPG/JPEG and PNG are accepted")
    dims = _header_dimensions(data, fmt)
    if dims and dims[0] * dims[1] > max_pixels:
        raise ImageValidationError(f"image dimensions too large ({dims[0]}x{dims[1]} px)")
    arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ImageValidationError("image is corrupted or cannot be decoded")
    h, w = arr.shape[:2]
    if w * h > max_pixels:
        raise ImageValidationError(f"image dimensions too large ({w}x{h} px)")
    if min(w, h) < min_side:
        raise ImageValidationError(f"image too small ({w}x{h}px; minimum side is {min_side}px)")
    return ValidatedImage(arr, fmt, w, h, len(data))


@dataclass(frozen=True)
class LetterboxResult:
    image: np.ndarray
    scale: float
    pad_x: float
    pad_y: float


def letterbox(image: np.ndarray, size: int = 640, pad_value: int = 114) -> LetterboxResult:
    """Resize keeping aspect ratio, padding to a square canvas (YOLO-style preprocessing)."""
    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    left, top = (size - nw) // 2, (size - nh) // 2
    canvas[top : top + nh, left : left + nw] = resized
    return LetterboxResult(canvas, scale, float(left), float(top))


def to_model_input(image_bgr: np.ndarray, size: int = 640) -> tuple[np.ndarray, LetterboxResult]:
    """BGR uint8 -> NCHW float32 RGB in [0,1] plus the letterbox metadata."""
    lb = letterbox(image_bgr, size)
    rgb = cv2.cvtColor(lb.image, cv2.COLOR_BGR2RGB)
    tensor = rgb.astype(np.float32) / 255.0
    return np.ascontiguousarray(tensor.transpose(2, 0, 1)[None]), lb


def undo_letterbox(xyxy: np.ndarray, lb: LetterboxResult, orig_w: int, orig_h: int) -> np.ndarray:
    """Map boxes from letterboxed model space back to original image pixels (clipped)."""
    out = xyxy.astype(np.float64).copy()
    out[:, [0, 2]] = (out[:, [0, 2]] - lb.pad_x) / lb.scale
    out[:, [1, 3]] = (out[:, [1, 3]] - lb.pad_y) / lb.scale
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, orig_w)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, orig_h)
    return out


def enhance_contrast(image_bgr: np.ndarray) -> np.ndarray:
    """Optional CLAHE on the luminance channel; useful for low-contrast metal surfaces."""
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
