"""Repository contract: the same assertions run against every Repository implementation."""
from datetime import timedelta

from app.db.common import utcnow


def rec(i, decision="REJECT", mode="real", source="upload", ago_days=0, cls="scratch"):
    defects = [{"class_id": 0, "class_name": cls, "confidence": 0.9, "bbox": [1, 2, 30, 40], "triggered": True}] if decision == "REJECT" else []
    return {
        "id": f"INS-test-{i}", "created_at": utcnow() - timedelta(days=ago_days), "original_ref": f"originals/{i}.png",
        "annotated_ref": f"annotated/{i}.png", "original_filename": f"part_{i}.png", "decision": decision, "reasons": "r",
        "top_class": cls if defects else None, "top_confidence": 0.9 if defects else None, "top_bbox": [1, 2, 30, 40] if defects else None,
        "defect_count": len(defects), "model_mode": mode, "model_name": "m", "model_version": "v1", "confidence_threshold": 0.25,
        "iou_threshold": 0.45, "duration_ms": 12.5, "width": 100, "height": 100, "source": source, "plc_event_id": None, "defects": defects,
    }


class RepositoryContract:
    """Mixin; subclasses provide self.repo."""

    def test_inspection_roundtrip(self):
        saved = self.repo.add_inspection(rec(1))
        self.assertEqual(saved["id"], "INS-test-1")
        got = self.repo.get_inspection("INS-test-1")
        self.assertEqual((got["decision"], got["top_bbox"], len(got["defects"])), ("REJECT", [1, 2, 30, 40], 1))
        self.assertIsNone(self.repo.get_inspection("nope"))

    def test_list_filters_and_paging(self):
        self.repo.add_inspection(rec(1, "REJECT", "real", ago_days=0))
        self.repo.add_inspection(rec(2, "PASS", "real", ago_days=1))
        self.repo.add_inspection(rec(3, "REJECT", "demo", "demo_seed", ago_days=2, cls="pit"))
        items, total = self.repo.list_inspections()
        self.assertEqual((total, [i["id"] for i in items]), (3, ["INS-test-1", "INS-test-2", "INS-test-3"]))  # newest first
        self.assertEqual(self.repo.list_inspections(decision="PASS")[1], 1)
        self.assertEqual(self.repo.list_inspections(class_name="pit")[1], 1)
        self.assertEqual(self.repo.list_inspections(include_demo=False)[1], 2)
        self.assertEqual(self.repo.list_inspections(q="part_2")[1], 1)
        self.assertEqual(self.repo.list_inspections(source="demo_seed")[1], 1)
        self.assertEqual(self.repo.list_inspections(mode="real")[1], 2)
        self.assertEqual(self.repo.list_inspections(date_from=utcnow() - timedelta(hours=36))[1], 2)
        page, total = self.repo.list_inspections(limit=1, offset=1)
        self.assertEqual((len(page), total, page[0]["id"]), (1, 3, "INS-test-2"))

    def test_stats(self):
        self.repo.add_inspection(rec(1, "REJECT", "real"))
        self.repo.add_inspection(rec(2, "PASS", "real"))
        self.repo.add_inspection(rec(3, "REJECT", "demo", "demo_seed", cls="pit"))
        st = self.repo.stats()
        self.assertEqual((st["total"], st["passed"], st["rejected"], st["demo_records"]), (3, 1, 2, 1))
        self.assertEqual({d["class_name"]: d["count"] for d in st["defect_distribution"]}, {"scratch": 1, "pit": 1})
        self.assertEqual(sum(t["total"] for t in st["trend"]), 3)
        self.assertEqual(self.repo.stats(include_demo=False)["total"], 2)

    def test_uploads_events_status_config(self):
        self.repo.add_upload({"id": "UPL-1", "original_filename": "a.png", "stored_ref": "uploads/UPL-1.png", "fmt": "png",
                              "width": 10, "height": 10, "size_bytes": 5, "sha256": "x" * 64})
        self.assertEqual(self.repo.get_upload("UPL-1")["stored_ref"], "uploads/UPL-1.png")
        self.assertIsNone(self.repo.get_upload("none"))
        e = self.repo.add_plc_event({"type": "connect", "ok": True, "detail": "d"})
        self.assertTrue(e["id"])
        self.assertEqual(self.repo.list_plc_events()[0]["type"], "connect")
        self.repo.add_system_event("INFO", "hello", {"a": 1})
        self.assertEqual(self.repo.list_system_events()[0]["message"], "hello")
        self.assertIsNone(self.repo.latest_machine_status())
        self.repo.save_machine_status({"machine_state": "RUNNING", "conveyor_running": True, "estop": False, "components": 1,
                                       "passed": 1, "rejected": 0, "simulated": True})
        self.assertEqual(self.repo.latest_machine_status()["machine_state"], "RUNNING")
        self.assertIsNone(self.repo.latest_model_config())
        self.repo.save_model_config({"confidence_threshold": 0.3})
        self.repo.save_model_config({"confidence_threshold": 0.4})
        self.assertEqual(self.repo.latest_model_config()["confidence_threshold"], 0.4)
        self.assertTrue(self.repo.ping())
