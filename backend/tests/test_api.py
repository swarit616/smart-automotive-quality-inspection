"""API tests. They need the web stack (fastapi, httpx, sqlalchemy); skipped when unavailable."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from app.core import synthetic
from tests.helpers import png_bytes

HAVE = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "multipart"))


@unittest.skipUnless(HAVE, "fastapi/httpx/sqlalchemy/python-multipart not installed in this environment")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from app.api.main import create_app
        from app.config import Settings

        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.settings = Settings(data_dir=t, database_url=f"sqlite:///{t / 'test.db'}", detection_mode="demo", model_dir=t,
                                model_weights_path=t / "none.pt", plc_port=0)
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app)
        cls.client.__enter__()  # runs lifespan

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_health_ready_and_status(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        r = self.client.get("/ready")
        self.assertEqual((r.status_code, r.json()["mode"]), (200, "demo"))
        st = self.client.get("/api/v1/model/status").json()
        self.assertEqual((st["mode"], st["ready"]), ("demo", True))

    def test_upload_analyze_detail_images_history(self):
        defective = synthetic.encode_png(synthetic.make_sample(3, True)[0])
        r = self.client.post("/api/v1/inspection/upload", files=[("files", ("a.png", defective, "image/png")),
                                                                  ("files", ("bad.txt", b"hello", "text/plain"))])
        self.assertEqual(r.status_code, 200)
        res = r.json()["results"]
        self.assertEqual((res[0]["ok"], res[1]["ok"]), (True, False))
        a = self.client.post("/api/v1/inspection/analyze", json={"upload_ids": [res[0]["upload_id"], "UPL-missing"]}).json()
        self.assertEqual((a["results"][0]["inspection"]["decision"], a["results"][1]["ok"]), ("REJECT", False))
        iid = a["results"][0]["inspection"]["id"]
        self.assertEqual(self.client.get(f"/api/v1/inspection/{iid}").json()["id"], iid)
        self.assertEqual(self.client.get(f"/api/v1/inspection/{iid}/image/annotated").headers["content-type"], "image/png")
        self.assertEqual(self.client.get("/api/v1/inspection/INS-none").status_code, 404)
        self.assertGreaterEqual(self.client.get("/api/v1/inspections", params={"decision": "REJECT"}).json()["total"], 1)
        self.assertEqual(self.client.get("/api/v1/inspections", params={"decision": "MAYBE"}).status_code, 422)
        self.assertGreaterEqual(self.client.get("/api/v1/dashboard/stats").json()["total"], 1)

    def test_validation_errors(self):
        self.assertEqual(self.client.post("/api/v1/inspection/analyze", json={"upload_ids": []}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/model/config", json={"confidence_threshold": 5}).status_code, 422)

    def test_plc_workflow_through_api(self):
        self.assertFalse(self.client.get("/api/v1/plc/status").json()["connected"])
        self.assertEqual(self.client.post("/api/v1/plc/simulate-cycle", json={"scenario": "normal"}).status_code, 409)
        self.assertTrue(self.client.post("/api/v1/plc/connect").json()["connected"])
        c = self.client.post("/api/v1/plc/simulate-cycle", json={"scenario": "defective"}).json()
        self.assertEqual((c["status"], c["decision"]), ("completed", "REJECT"))
        self.assertEqual(len(self.client.get("/api/v1/plc/registers").json()["register_map"]), 18)
        self.assertTrue(self.client.post("/api/v1/plc/emergency-stop", json={"active": True}).json()["plc"]["estop"])
        self.assertEqual(self.client.post("/api/v1/plc/simulate-cycle", json={"scenario": "normal"}).json()["status"], "blocked_estop")
        self.client.post("/api/v1/plc/emergency-stop", json={"active": False})
        self.assertFalse(self.client.post("/api/v1/plc/disconnect").json()["connected"])

    def test_control_endpoints_need_key_when_configured(self):
        from dataclasses import replace

        from fastapi.testclient import TestClient

        from app.api.main import create_app

        s = replace(self.settings, api_key="k" * 24, database_url="sqlite://")
        with TestClient(create_app(s)) as c:
            self.assertEqual(c.post("/api/v1/plc/connect").status_code, 401)
            self.assertEqual(c.post("/api/v1/plc/connect", headers={"X-API-Key": "wrong"}).status_code, 401)
            self.assertEqual(c.get("/api/v1/plc/status").status_code, 200)  # read-only stays open
            self.assertEqual(c.post("/api/v1/plc/connect", headers={"X-API-Key": "k" * 24}).status_code, 200)

    def test_real_mode_not_ready_returns_503(self):
        from dataclasses import replace

        from fastapi.testclient import TestClient

        from app.api.main import create_app

        s = replace(self.settings, detection_mode="real", database_url="sqlite://")
        with TestClient(create_app(s)) as c:
            self.assertEqual(c.get("/ready").status_code, 503)
            up = c.post("/api/v1/inspection/upload", files=[("files", ("a.png", png_bytes(64, 64), "image/png"))]).json()["results"][0]
            self.assertEqual(c.post("/api/v1/inspection/analyze", json={"upload_ids": [up["upload_id"]]}).status_code, 503)


if __name__ == "__main__":
    unittest.main()
