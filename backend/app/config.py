"""Runtime configuration, read from environment variables (see .env.example).

Kept dependency-free (dataclass + os.environ) so the core logic and its tests run
without installing the web stack.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- storage -------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "./data")).resolve())
    database_url: str = ""  # resolved in __post_init__ below via build()
    # --- detection -----------------------------------------------------
    detection_mode: str = "auto"  # auto | real | demo
    model_weights_path: Path = field(default_factory=lambda: Path(os.environ.get("MODEL_WEIGHTS_PATH", "./models/best.pt")))
    model_dir: Path = field(default_factory=lambda: Path(os.environ.get("MODEL_DIR", "./models")).resolve())
    class_names_path: str = ""
    confidence_threshold: float = 0.25
    iou_threshold: float = 0.45
    image_size: int = 640
    # --- upload limits -------------------------------------------------
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 25_000_000
    min_image_side: int = 32
    # --- PLC (simulator by default) ------------------------------------
    plc_host: str = "127.0.0.1"
    plc_port: int = 5020
    plc_unit_id: int = 1
    plc_timeout_s: float = 2.0
    plc_retries: int = 3
    plc_autostart_simulator: bool = True
    plc_allow_non_local_host: bool = False
    # --- security / serving --------------------------------------------
    api_key: str = ""
    cors_origins: tuple[str, ...] = ("http://localhost:8000", "http://localhost:8080", "http://localhost:5173")
    frontend_dist: str = ""
    log_level: str = "INFO"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def original_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def annotated_dir(self) -> Path:
        return self.data_dir / "annotated"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.original_dir, self.annotated_dir, self.model_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
        db = os.environ.get("DATABASE_URL") or f"sqlite:///{data_dir / 'inspection.db'}"
        origins = tuple(o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()) or cls.cors_origins
        return cls(
            data_dir=data_dir,
            database_url=db,
            detection_mode=os.environ.get("DETECTION_MODE", "auto").lower(),
            model_weights_path=Path(os.environ.get("MODEL_WEIGHTS_PATH", "./models/best.pt")),
            model_dir=Path(os.environ.get("MODEL_DIR", "./models")).resolve(),
            class_names_path=os.environ.get("CLASS_NAMES_PATH", ""),
            confidence_threshold=_float("CONFIDENCE_THRESHOLD", 0.25),
            iou_threshold=_float("IOU_THRESHOLD", 0.45),
            image_size=_int("IMAGE_SIZE", 640),
            max_upload_bytes=_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_image_pixels=_int("MAX_IMAGE_PIXELS", 25_000_000),
            plc_host=os.environ.get("PLC_HOST", "127.0.0.1"),
            plc_port=_int("PLC_PORT", 5020),
            plc_unit_id=_int("PLC_UNIT_ID", 1),
            plc_timeout_s=_float("PLC_TIMEOUT_S", 2.0),
            plc_retries=_int("PLC_RETRIES", 3),
            plc_autostart_simulator=_bool("PLC_AUTOSTART_SIMULATOR", True),
            plc_allow_non_local_host=_bool("PLC_ALLOW_NON_LOCAL_HOST", False),
            api_key=os.environ.get("API_KEY", ""),
            cors_origins=origins,
            frontend_dist=os.environ.get("FRONTEND_DIST", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
