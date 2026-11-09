"""DetectionEngine: the single detection pipeline shared by Project A (upload inspection)
and Project B (PLC-triggered inspection).

image bytes -> validation -> detector -> PASS/REJECT decision -> annotated image
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import Settings
from .annotate import annotate, encode_png
from .decision import Decision, DecisionRules, decide
from .detectors import DemoDetector, Detection, Detector, DetectorUnavailable, OnnxYoloDetector, UltralyticsDetector
from .preprocessing import ValidatedImage, validate_and_decode

log = logging.getLogger(__name__)

MODE_REAL = "real"
MODE_DEMO = "demo"


class ModelNotReadyError(RuntimeError):
    """REAL MODEL MODE was requested but no usable model is loaded."""


@dataclass
class AnalysisResult:
    detections: list[Detection]
    decision: Decision
    duration_ms: float
    width: int
    height: int
    mode: str
    model_name: str
    model_version: str
    confidence_threshold: float
    iou_threshold: float
    annotated_png: bytes
    original_format: str
    original_extension: str


class DetectionEngine:
    def __init__(self, settings: Settings, rules: DecisionRules | None = None):
        self.settings = settings
        self.rules = rules or DecisionRules()
        self.confidence = settings.confidence_threshold
        self.iou = settings.iou_threshold
        self.requested_mode = settings.detection_mode if settings.detection_mode in {"auto", "real", "demo"} else "auto"
        self._detector: Detector | None = None
        self._mode: str | None = None
        self._reason = "not loaded"
        self._lock = threading.RLock()
        self._loaded = False

    # ------------------------------------------------------------------ loading
    def _load_real(self) -> Detector:
        weights = Path(self.settings.model_weights_path)
        if not weights.is_absolute():
            weights = Path.cwd() / weights
        if not weights.is_file():
            raise DetectorUnavailable(f"model weights not found at {weights}")
        names = None
        from .detectors import load_class_names

        names = load_class_names(weights, self.settings.class_names_path)
        if weights.suffix.lower() == ".onnx":
            return OnnxYoloDetector(weights, names, self.settings.image_size)
        if weights.suffix.lower() == ".pt":
            return UltralyticsDetector(weights, self.settings.image_size)
        raise DetectorUnavailable(f"unsupported weights extension {weights.suffix!r} (use .pt or .onnx)")

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._detector, self._mode = None, None
            if self.requested_mode == "demo":
                self._detector, self._mode, self._reason = DemoDetector(), MODE_DEMO, "DEMO MODE selected by configuration"
            else:
                try:
                    self._detector, self._mode, self._reason = self._load_real(), MODE_REAL, "real model loaded"
                except DetectorUnavailable as exc:
                    log.warning("real model unavailable: %s", exc)
                    if self.requested_mode == "auto":
                        self._detector, self._mode = DemoDetector(), MODE_DEMO
                        self._reason = f"{exc}; running in DEMO MODE (no trained model)"
                    else:
                        self._reason = str(exc)
                except Exception as exc:  # noqa: BLE001 - corrupt weights, runtime errors
                    log.exception("failed to load model")
                    self._reason = f"failed to load model: {exc}"
                    if self.requested_mode == "auto":
                        self._detector, self._mode = DemoDetector(), MODE_DEMO
                        self._reason += "; running in DEMO MODE"
            self._loaded = True

    def reload(self) -> None:
        with self._lock:
            self._loaded = False
        self.ensure_loaded()

    # ------------------------------------------------------------------ config
    def configure(self, *, confidence: float | None = None, iou: float | None = None, mode: str | None = None,
                  rules: DecisionRules | None = None) -> None:
        if confidence is not None and not 0.0 < confidence < 1.0:
            raise ValueError("confidence must be within (0, 1)")
        if iou is not None and not 0.0 < iou < 1.0:
            raise ValueError("iou must be within (0, 1)")
        if mode is not None and mode not in {"auto", "real", "demo"}:
            raise ValueError("mode must be one of: auto, real, demo")
        if rules is not None:
            rules.validate()
        with self._lock:
            if confidence is not None:
                self.confidence = confidence
            if iou is not None:
                self.iou = iou
            if rules is not None:
                self.rules = rules
            if mode is not None and mode != self.requested_mode:
                self.requested_mode = mode
                self._loaded = False
        self.ensure_loaded()

    # ------------------------------------------------------------------ status
    @property
    def mode(self) -> str | None:
        self.ensure_loaded()
        return self._mode

    def is_ready(self) -> bool:
        self.ensure_loaded()
        return self._detector is not None

    def status(self) -> dict:
        self.ensure_loaded()
        det = self._detector
        weights = Path(self.settings.model_weights_path)
        status = {
            "mode": self._mode,  # "real" | "demo" | None when real mode was requested but unavailable
            "requested_mode": self.requested_mode,
            "ready": det is not None,
            "reason": self._reason,
            "model_name": det.name if det else None,
            "model_version": det.version if det else None,
            "class_names": list(det.class_names) if det else [],
            "weights_path": str(weights),
            "weights_present": weights.is_file(),
            "confidence_threshold": self.confidence,
            "iou_threshold": self.iou,
            "image_size": self.settings.image_size,
            "decision_rules": self.rules.to_dict(),
            "metrics": self._read_json("metrics.json") if self._mode == MODE_REAL else None,
            "training": self._read_json("training_status.json"),
            "demo_notice": (
                "DEMO MODE: detections come from a classical OpenCV anomaly heuristic, not a trained "
                "defect model. Scores are normalised contrast values, not model confidences."
                if self._mode == MODE_DEMO else None
            ),
            "setup_instructions": None if self._mode == MODE_REAL else (
                "To enable REAL MODEL MODE: train or obtain YOLOv8 weights (see docs/MODEL_TRAINING.md), "
                "place them at MODEL_WEIGHTS_PATH (default models/best.pt or best.onnx with a class_names.json) "
                "and restart or call POST /api/v1/model/config."
            ),
        }
        m = status["metrics"]
        if m and det and m.get("weights_version") not in (None, det.version):
            status["metrics_warning"] = "metrics.json was produced for different weights than the ones loaded"
        return status

    def _read_json(self, name: str) -> dict | None:
        p = Path(self.settings.model_dir) / name
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except ValueError:
                return None
        return None

    # ------------------------------------------------------------------ analysis
    def analyze_bytes(self, data: bytes, *, conf: float | None = None, iou: float | None = None) -> AnalysisResult:
        validated = validate_and_decode(
            data, max_bytes=self.settings.max_upload_bytes, max_pixels=self.settings.max_image_pixels,
            min_side=self.settings.min_image_side,
        )
        return self.analyze_image(validated, conf=conf, iou=iou)

    def analyze_image(self, validated: ValidatedImage, *, conf: float | None = None, iou: float | None = None) -> AnalysisResult:
        self.ensure_loaded()
        det = self._detector
        if det is None:
            raise ModelNotReadyError(self._reason)
        c = self.confidence if conf is None else conf
        i = self.iou if iou is None else iou
        t0 = time.perf_counter()
        detections = det.detect(validated.image, c, i)
        decision = decide(detections, validated.width, validated.height, self.rules)
        elapsed = (time.perf_counter() - t0) * 1000.0
        annotated = encode_png(annotate(validated.image, detections, decision.result, demo=self._mode == MODE_DEMO))
        return AnalysisResult(
            detections=detections, decision=decision, duration_ms=round(elapsed, 2), width=validated.width,
            height=validated.height, mode=self._mode or "", model_name=det.name, model_version=det.version,
            confidence_threshold=c, iou_threshold=i, annotated_png=annotated, original_format=validated.fmt,
            original_extension=validated.extension,
        )
