import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.core import synthetic
from app.core.engine import DetectionEngine, ModelNotReadyError
from app.core.preprocessing import ImageValidationError
from app.db import MemoryRepository
from app.services.inspection_service import InspectionService, NotFound, display_name
from app.services.model_service import ModelService
from app.services.plc_service import PlcNotConnected, PlcService
from tests.helpers import png_bytes


def make(tmp, mode="demo", **kw):
    s = Settings(data_dir=Path(tmp), database_url="sqlite://", detection_mode=mode, model_weights_path=Path(tmp) / "none.pt",
                 model_dir=Path(tmp), plc_port=0, **kw)
    repo = MemoryRepository()
    eng = DetectionEngine(s)
    return s, repo, eng, InspectionService(s, eng, repo)


def defective_png(seed=3):
    return synthetic.encode_png(synthetic.make_sample(seed, True)[0])


def clean_png(seed=3):
    return synthetic.encode_png(synthetic.make_sample(seed, False)[0])


class InspectionServiceTests(unittest.TestCase):
    def test_upload_analyze_persist_and_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            s, repo, eng, svc = make(tmp)
            up = svc.save_upload("../../etc/passwd.png", defective_png())
            self.assertNotIn("/", up["filename"])
            rec = svc.analyze_upload(up["upload_id"])
            self.assertEqual((rec["decision"], rec["model_mode"], rec["is_demo"]), ("REJECT", "demo", True))
            self.assertNotIn("original_ref", rec)
            self.assertTrue(svc.image_path(rec["id"], "annotated").is_file())
            self.assertEqual(svc.get(rec["id"])["id"], rec["id"])
            self.assertEqual(rec["defect_count"], len([d for d in rec["defects"] if d["triggered"]]))
            self.assertTrue(rec["top_bbox"])

    def test_pass_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, svc = make(tmp)
            rec = svc.analyze_bytes(clean_png(), "clean.png")
            self.assertEqual((rec["decision"], rec["defect_count"], rec["top_class"]), ("PASS", 0, None))

    def test_invalid_uploads_rejected_and_nothing_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            s, repo, _, svc = make(tmp)
            for data in (b"", b"GARBAGE", png_bytes(8, 8)):
                with self.assertRaises(ImageValidationError):
                    svc.save_upload("x.png", data)
            self.assertEqual(repo.uploads, {})
            self.assertEqual(list(s.upload_dir.iterdir()), [])

    def test_unknown_ids_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, _, svc = make(tmp)
            with self.assertRaises(NotFound):
                svc.get("INS-nope")
            with self.assertRaises(NotFound):
                svc.analyze_upload("UPL-nope")
            with self.assertRaises(NotFound):
                svc.resolve("../outside.txt")
            rec = svc.analyze_bytes(clean_png(), "a.png")
            with self.assertRaises(NotFound):
                svc.image_path(rec["id"], "../../etc/passwd")

    def test_display_name_sanitised(self):
        self.assertEqual(display_name("C:\\evil\\..\\a b$.png"), "a b_.png")
        self.assertEqual(display_name(None), "image")

    def test_real_mode_without_model_raises_and_stores_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, _, svc = make(tmp, mode="real")
            with self.assertRaises(ModelNotReadyError):
                svc.analyze_bytes(clean_png(), "a.png")
            self.assertEqual(repo.inspections, {})

    def test_list_filters_and_stats_with_demo_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, _, svc = make(tmp)
            svc.analyze_bytes(defective_png(1), "bad.png")
            svc.analyze_bytes(clean_png(1), "good.png")
            self.assertEqual(svc.seed_demo(6)["created"], 6)
            self.assertEqual(svc.list(limit=100, offset=0)["total"], 8)
            self.assertEqual(svc.list(decision="PASS", limit=100, offset=0)["items"][0]["decision"], "PASS")
            self.assertEqual(svc.list(q="bad", limit=10, offset=0)["total"], 1)
            self.assertEqual(svc.list(source="demo_seed", limit=10, offset=0)["total"], 6)
            self.assertEqual(svc.list(limit=3, offset=2)["items"].__len__(), 3)
            st = repo.stats()
            self.assertEqual(st["total"], 8)
            self.assertEqual(st["passed"] + st["rejected"], 8)
            self.assertEqual(st["demo_records"], 8)
            self.assertEqual(len(st["trend"]), 14)
            self.assertEqual(sum(d["count"] for d in st["defect_distribution"]) > 0, True)
            self.assertEqual(repo.stats(include_demo=False)["total"], 0)
            self.assertTrue(any("seeded" in e["message"] for e in repo.list_system_events()))


class ModelServiceTests(unittest.TestCase):
    def test_configure_persists_and_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            s, repo, eng, _ = make(tmp)
            ms = ModelService(eng, repo)
            st = ms.configure(confidence=0.7, iou=0.4, decision_rules={"max_defects_allowed": 2})
            self.assertEqual((st["confidence_threshold"], st["decision_rules"]["max_defects_allowed"]), (0.7, 2))
            eng2 = DetectionEngine(s)
            ModelService(eng2, repo).restore_saved_config()
            self.assertEqual((eng2.confidence, eng2.rules.max_defects_allowed), (0.7, 2))
            with self.assertRaises(ValueError):
                ms.configure(confidence=2)


class PlcServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s, self.repo, self.eng, self.insp = make(self.tmp.name)
        self.plc = PlcService(self.s, self.insp, self.repo)

    def tearDown(self):
        self.plc.shutdown()
        self.tmp.cleanup()

    def test_requires_connection(self):
        st = self.plc.status()
        self.assertEqual((st["connected"], st["simulator"]), (False, True))
        with self.assertRaises(PlcNotConnected):
            self.plc.simulate_cycle("normal")

    def test_refuses_non_local_target(self):
        with self.assertRaises(ValueError):
            self.plc.connect("192.168.1.50", 502)

    def test_end_to_end_cycles_write_db_and_plc(self):
        st = self.plc.connect()
        self.assertTrue(st["connected"])
        self.assertIn("SIMULATED", st["label"])
        bad = self.plc.simulate_cycle("defective")
        good = self.plc.simulate_cycle("normal")
        self.assertEqual((bad["status"], bad["decision"]), ("completed", "REJECT"))
        self.assertEqual((good["status"], good["decision"]), ("completed", "PASS"))
        self.assertEqual(bad["plc_after"]["component_status"], "REJECTED")
        self.assertEqual(good["plc_after"]["component_status"], "INSPECTED_OK")
        rec = self.insp.get(bad["inspection_id"])
        self.assertEqual((rec["source"], rec["decision"]), ("plc_cycle", "REJECT"))
        self.assertTrue(rec["plc_event_id"])
        counters = self.plc.status()["plc"]["counters"]
        self.assertEqual((counters["passed"], counters["rejected"]), (1, 1))
        types = [e["type"] for e in self.repo.list_plc_events(100)]
        self.assertIn("cycle_start", types)
        self.assertIn("result_sent", types)
        self.assertEqual(self.repo.latest_machine_status()["rejected"], 1)

    def test_estop_blocks_cycle(self):
        self.plc.connect()
        self.assertTrue(self.plc.emergency_stop(True)["plc"]["estop"])
        res = self.plc.simulate_cycle("normal")
        self.assertEqual(res["status"], "blocked_estop")
        self.assertEqual(self.plc.status()["plc"]["machine_state"], "ESTOP")
        self.assertFalse(self.plc.emergency_stop(False)["plc"]["estop"])
        self.assertEqual(self.plc.simulate_cycle("normal")["status"], "completed")

    def test_real_model_missing_gives_failsafe_reject_to_plc(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            s, repo, eng, insp = make(tmp.name, mode="real")
            plc = PlcService(s, insp, repo)
            plc.connect()
            res = plc.simulate_cycle("normal")
            self.assertEqual((res["decision"], res["failsafe_reject"]), ("REJECT", True))
            self.assertEqual(res["plc_after"]["component_status"], "REJECTED")
            plc.shutdown()
        finally:
            tmp.cleanup()

    def test_upload_scenario_and_validation(self):
        self.plc.connect()
        up = self.insp.save_upload("p.png", defective_png(8))
        res = self.plc.simulate_cycle("upload", up["upload_id"])
        self.assertEqual(res["decision"], "REJECT")
        for args in (("bogus", None), ("upload", None)):
            with self.assertRaises(ValueError):
                self.plc.simulate_cycle(*args)

    def test_registers_and_disconnect(self):
        self.plc.connect()
        regs = self.plc.registers()
        self.assertTrue(regs["simulator"])
        self.assertEqual(len(regs["register_map"]), 18)
        self.assertFalse(self.plc.disconnect()["connected"])


if __name__ == "__main__":
    unittest.main()
