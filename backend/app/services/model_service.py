from __future__ import annotations

from ..core.decision import DecisionRules
from ..core.engine import DetectionEngine


class ModelService:
    def __init__(self, engine: DetectionEngine, repo):
        self.engine, self.repo = engine, repo

    def restore_saved_config(self) -> None:
        saved = self.repo.latest_model_config()
        if not saved:
            return
        try:
            rules = DecisionRules.from_dict(saved["decision_rules"]) if saved.get("decision_rules") else None
            self.engine.configure(confidence=saved.get("confidence_threshold"), iou=saved.get("iou_threshold"), rules=rules)
        except (ValueError, KeyError):
            self.repo.add_system_event("WARNING", "ignored invalid saved model configuration")

    def status(self) -> dict:
        return self.engine.status()

    def configure(self, *, confidence=None, iou=None, mode=None, decision_rules: dict | None = None) -> dict:
        rules = DecisionRules.from_dict({**self.engine.rules.to_dict(), **decision_rules}) if decision_rules else None
        self.engine.configure(confidence=confidence, iou=iou, mode=mode, rules=rules)
        st = self.engine.status()
        self.repo.save_model_config({"confidence_threshold": st["confidence_threshold"], "iou_threshold": st["iou_threshold"],
                                     "requested_mode": st["requested_mode"], "decision_rules": st["decision_rules"],
                                     "model_version": st["model_version"]})
        self.repo.add_system_event("INFO", "model configuration changed", {k: st[k] for k in ("confidence_threshold", "iou_threshold", "requested_mode")})
        return st

    def reload(self) -> dict:
        self.engine.reload()
        return self.engine.status()
