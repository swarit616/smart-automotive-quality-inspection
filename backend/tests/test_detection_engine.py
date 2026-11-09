import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.config import Settings
from app.core import synthetic
from app.core.boxes import BBox
from app.core.decision import DecisionRules, decide
from app.core.detectors import DemoDetector, Detection, postprocess_yolov8
from app.core.engine import DetectionEngine, ModelNotReadyError
from app.core.metrics import GroundTruth, evaluate_detections
from app.core.preprocessing import letterbox


def settings(tmp, mode="auto", weights="missing.pt"):
    return Settings(data_dir=Path(tmp), database_url="sqlite://", detection_mode=mode,
                    model_weights_path=Path(tmp) / weights, model_dir=Path(tmp))


def det(cls="scratch", conf=0.8, box=(10, 10, 60, 40)):
    return Detection(0, cls, conf, BBox(*box))


class DecisionTests(unittest.TestCase):
    def test_pass_when_no_detections(self):
        self.assertEqual(decide([], 100, 100, DecisionRules()).result, "PASS")

    def test_reject_on_confident_defect(self):
        d = decide([det()], 100, 100, DecisionRules())
        self.assertEqual(d.result, "REJECT")
        self.assertEqual(len(d.triggering), 1)

    def test_low_confidence_ignored(self):
        self.assertEqual(decide([det(conf=0.2)], 100, 100, DecisionRules(min_confidence=0.5)).result, "PASS")

    def test_class_threshold_and_ignore(self):
        rules = DecisionRules(min_confidence=0.9, class_min_confidence={"scratch": 0.5})
        self.assertEqual(decide([det(conf=0.6)], 100, 100, rules).result, "REJECT")
        self.assertEqual(decide([det()], 100, 100, DecisionRules(ignore_classes=["scratch"])).result, "PASS")

    def test_tiny_area_ignored_and_tolerance(self):
        self.assertEqual(decide([det(box=(1, 1, 2, 2))], 1000, 1000, DecisionRules(min_area_ratio=0.01)).result, "PASS")
        self.assertEqual(decide([det()], 100, 100, DecisionRules(max_defects_allowed=1)).result, "PASS")
        self.assertEqual(decide([det(), det(box=(0, 0, 30, 30))], 100, 100, DecisionRules(max_defects_allowed=1)).result, "REJECT")

    def test_rules_validation_and_roundtrip(self):
        with self.assertRaises(ValueError):
            DecisionRules(min_confidence=1.5).validate()
        r = DecisionRules.from_dict(DecisionRules(min_confidence=0.6, ignore_classes=["x"]).to_dict())
        self.assertEqual((r.min_confidence, r.ignore_classes), (0.6, ["x"]))


class PostprocessTests(unittest.TestCase):
    def test_decodes_yolov8_head(self):
        names = ["a", "b"]
        lb = letterbox(np.zeros((640, 640, 3), np.uint8), 640)
        out = np.zeros((1, 6, 4))  # 4 candidate anchors
        out[0, :, 0] = [100, 100, 80, 40, 0.9, 0.1]   # class a, strong
        out[0, :, 1] = [102, 101, 80, 40, 0.8, 0.1]   # duplicate -> NMS
        out[0, :, 2] = [400, 300, 50, 50, 0.1, 0.7]   # class b
        out[0, :, 3] = [500, 500, 20, 20, 0.05, 0.05]  # below confidence
        res = postprocess_yolov8(out, names, 0.25, 0.45, lb, 640, 640)
        self.assertEqual(sorted(d.class_name for d in res), ["a", "b"])
        a = next(d for d in res if d.class_name == "a")
        self.assertAlmostEqual(a.bbox.x1, 60); self.assertAlmostEqual(a.confidence, 0.9, places=5)

    def test_empty_when_below_threshold_and_bad_shape(self):
        lb = letterbox(np.zeros((64, 64, 3), np.uint8), 64)
        self.assertEqual(postprocess_yolov8(np.zeros((1, 6, 5)), ["a", "b"], 0.25, 0.5, lb, 64, 64), [])
        with self.assertRaises(ValueError):
            postprocess_yolov8(np.zeros((1, 9, 5)), ["a", "b"], 0.25, 0.5, lb, 64, 64)


class DemoDetectorTests(unittest.TestCase):
    """Sanity checks on SYNTHETIC images only; not a measure of real-world performance."""

    def test_flags_synthetic_defects_not_clean_surfaces(self):
        d = DemoDetector()
        flagged = sum(bool(d.detect(synthetic.make_sample(s, True)[0], 0.25, 0.45)) for s in range(15))
        false_alarms = sum(bool(d.detect(synthetic.make_sample(s, False)[0], 0.25, 0.45)) for s in range(15))
        self.assertGreaterEqual(flagged, 13)
        self.assertEqual(false_alarms, 0)


class EngineModeTests(unittest.TestCase):
    def test_auto_without_weights_falls_back_to_demo_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = DetectionEngine(settings(tmp))
            st = eng.status()
            self.assertEqual((st["mode"], st["ready"]), ("demo", True))
            self.assertIn("DEMO MODE", st["demo_notice"])
            self.assertFalse(st["weights_present"])
            self.assertIsNone(st["metrics"])
            self.assertIn("MODEL_TRAINING", st["setup_instructions"])

    def test_real_mode_without_weights_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = DetectionEngine(settings(tmp, mode="real"))
            st = eng.status()
            self.assertEqual((st["mode"], st["ready"]), (None, False))
            self.assertIn("not found", st["reason"])
            with self.assertRaises(ModelNotReadyError):
                eng.analyze_bytes(synthetic.encode_png(synthetic.make_sample(1, False)[0]))

    def test_unsupported_weights_extension_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "w.bin").write_bytes(b"x")
            eng = DetectionEngine(settings(tmp, mode="real", weights="w.bin"))
            self.assertFalse(eng.is_ready())
            self.assertIn("unsupported", eng.status()["reason"])

    def test_metrics_only_reported_in_real_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "metrics.json").write_text(json.dumps({"map50": 0.5}))
            self.assertIsNone(DetectionEngine(settings(tmp)).status()["metrics"])  # demo mode hides metrics

    def test_demo_analysis_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = DetectionEngine(settings(tmp, mode="demo"))
            bad = eng.analyze_bytes(synthetic.encode_png(synthetic.make_sample(4, True)[0]))
            good = eng.analyze_bytes(synthetic.encode_png(synthetic.make_sample(4, False)[0]))
            self.assertEqual((bad.decision.result, good.decision.result), ("REJECT", "PASS"))
            self.assertEqual(bad.mode, "demo")
            self.assertTrue(bad.annotated_png.startswith(b"\x89PNG"))
            self.assertGreater(bad.duration_ms, 0)

    def test_configure_validates_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng = DetectionEngine(settings(tmp, mode="demo"))
            eng.configure(confidence=0.6, iou=0.3)
            self.assertEqual((eng.confidence, eng.iou), (0.6, 0.3))
            for kw in ({"confidence": 0.0}, {"iou": 1.5}, {"mode": "bogus"}):
                with self.assertRaises(ValueError):
                    eng.configure(**kw)


class MetricsTests(unittest.TestCase):
    def test_perfect_predictions(self):
        gts = [[GroundTruth(0, BBox(0, 0, 10, 10))], [GroundTruth(1, BBox(5, 5, 20, 20))]]
        preds = [[Detection(0, "a", 0.9, BBox(0, 0, 10, 10))], [Detection(1, "b", 0.8, BBox(5, 5, 20, 20))]]
        r = evaluate_detections(preds, gts, ["a", "b"])
        self.assertEqual((r["precision"], r["recall"], r["f1"], r["map50"], r["map50_95"]), (1.0, 1.0, 1.0, 1.0, 1.0))

    def test_missed_and_spurious(self):
        gts = [[GroundTruth(0, BBox(0, 0, 10, 10))], []]
        preds = [[], [Detection(0, "a", 0.9, BBox(0, 0, 10, 10))]]
        r = evaluate_detections(preds, gts, ["a"])
        self.assertEqual((r["precision"], r["recall"], r["map50"]), (0.0, 0.0, 0.0))
        self.assertEqual(r["confusion_matrix"], [[0, 1], [1, 0]])

    def test_ap_known_value(self):
        # 2 GT; predictions ranked TP, FP, TP -> precision envelope gives AP = (1.0*0.5 + (2/3)*0.5) approx via 101 points
        gts = [[GroundTruth(0, BBox(0, 0, 10, 10)), GroundTruth(0, BBox(50, 50, 60, 60))]]
        preds = [[Detection(0, "a", 0.9, BBox(0, 0, 10, 10)), Detection(0, "a", 0.8, BBox(100, 100, 110, 110)),
                  Detection(0, "a", 0.7, BBox(50, 50, 60, 60))]]
        r = evaluate_detections(preds, gts, ["a"], conf_threshold=0.0)
        self.assertAlmostEqual(r["map50"], (51 * 1.0 + 50 * (2 / 3)) / 101, places=3)
        self.assertEqual(r["recall"], 1.0)
        self.assertAlmostEqual(r["precision"], 2 / 3, places=3)

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            evaluate_detections([[]], [[], []], ["a"])


if __name__ == "__main__":
    unittest.main()
