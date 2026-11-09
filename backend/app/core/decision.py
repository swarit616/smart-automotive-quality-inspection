"""PASS / REJECT decision logic (pure functions, no I/O)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .detectors import Detection

PASS = "PASS"
REJECT = "REJECT"


@dataclass
class DecisionRules:
    """Configurable acceptance criteria.

    A detection counts as a *reject-triggering defect* when its confidence is at least the
    class-specific threshold (or `min_confidence`) and its box covers at least
    `min_area_ratio` of the image. The part is rejected when the number of such defects
    exceeds `max_defects_allowed`.
    """

    min_confidence: float = 0.35
    class_min_confidence: dict[str, float] = field(default_factory=dict)
    ignore_classes: list[str] = field(default_factory=list)
    min_area_ratio: float = 0.0003
    max_defects_allowed: int = 0

    def validate(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        if not 0.0 <= self.min_area_ratio < 1.0:
            raise ValueError("min_area_ratio must be within [0, 1)")
        if self.max_defects_allowed < 0:
            raise ValueError("max_defects_allowed must be >= 0")
        for k, v in self.class_min_confidence.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"class threshold for {k!r} must be within [0, 1]")

    def to_dict(self) -> dict:
        return {
            "min_confidence": self.min_confidence,
            "class_min_confidence": dict(self.class_min_confidence),
            "ignore_classes": list(self.ignore_classes),
            "min_area_ratio": self.min_area_ratio,
            "max_defects_allowed": self.max_defects_allowed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRules":
        rules = cls(
            min_confidence=float(d.get("min_confidence", 0.35)),
            class_min_confidence={str(k): float(v) for k, v in (d.get("class_min_confidence") or {}).items()},
            ignore_classes=[str(x) for x in (d.get("ignore_classes") or [])],
            min_area_ratio=float(d.get("min_area_ratio", 0.0003)),
            max_defects_allowed=int(d.get("max_defects_allowed", 0)),
        )
        rules.validate()
        return rules


@dataclass(frozen=True)
class Decision:
    result: str  # PASS | REJECT
    triggering: list[Detection]
    reasons: list[str]

    @property
    def is_reject(self) -> bool:
        return self.result == REJECT


def decide(detections: Sequence[Detection], image_w: int, image_h: int, rules: DecisionRules) -> Decision:
    image_area = float(image_w * image_h)
    trig: list[Detection] = []
    for d in detections:
        if d.class_name in rules.ignore_classes:
            continue
        threshold = rules.class_min_confidence.get(d.class_name, rules.min_confidence)
        if d.confidence < threshold:
            continue
        if image_area > 0 and d.bbox.area / image_area < rules.min_area_ratio:
            continue
        trig.append(d)
    if len(trig) > rules.max_defects_allowed:
        names = ", ".join(sorted({d.class_name for d in trig}))
        return Decision(REJECT, trig, [f"{len(trig)} defect(s) above threshold (allowed: {rules.max_defects_allowed}): {names}"])
    return Decision(PASS, [], ["no defects above the configured thresholds"])
