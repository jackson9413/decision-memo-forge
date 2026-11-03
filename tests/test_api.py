"""HTTP API tests for Decision Memo Forge."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as dmf_app  # noqa: E402
import samples  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dmf_app.app.config["TESTING"] = True
        cls.client = dmf_app.app.test_client()

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_index_page_renders(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("Decision Memo Forge", body)

    def test_options_endpoint_lists_archetypes(self):
        data = self.client.get("/api/options").get_json()
        self.assertIn("doc_types", data)
        self.assertTrue(len(data["doc_types"]) >= 5)

    def test_samples_endpoint(self):
        data = self.client.get("/api/samples").get_json()
        self.assertEqual(len(data["samples"]), len(samples.SAMPLE_ORDER))

    def test_single_sample(self):
        resp = self.client.get("/api/sample/checkout-postgres-memo")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text", resp.get_json())

    def test_unknown_sample_is_404(self):
        self.assertEqual(self.client.get("/api/sample/nope").status_code, 404)

    def test_analyze_rejects_empty_text(self):
        resp = self.client.post("/api/analyze", json={"text": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_analyze_returns_a_report(self):
        resp = self.client.post("/api/analyze", json={
            "text": samples.SAMPLES["checkout-postgres-memo"]["text"],
            "doc_type": "memo", "stakes": "high", "reversibility": "two_way",
            "audience": "exec"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("score", data)
        self.assertIn("axes", data)
        self.assertIn("findings", data)
        self.assertIn("markdown", data)
        self.assertEqual(len(data["axes"]), 5)

    def test_analyze_ignores_bad_enum_values(self):
        resp = self.client.post("/api/analyze", json={
            "text": "Decision\n\nWe need to decide something today.\n",
            "stakes": "wat", "reversibility": "wat", "audience": "wat",
            "doc_type": "wat"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["meta"]["stakes"], "medium")
        self.assertEqual(data["meta"]["reversibility"], "unknown")
        self.assertEqual(data["meta"]["audience"], "mixed")
        self.assertTrue(data["meta"]["doc_type_detected"])

    def test_session_round_trip(self):
        resp = self.client.post("/api/analyze", json={
            "text": samples.SAMPLES["checkout-postgres-memo"]["text"],
            "doc_type": "memo", "save": True, "title": "Round trip test"})
        sid = resp.get_json()["session_id"]
        self.assertIsNotNone(sid)

        listing = self.client.get("/api/sessions").get_json()
        self.assertTrue(any(s["id"] == sid for s in listing["sessions"]))

        detail = self.client.get("/api/sessions/%d" % sid).get_json()
        self.assertIn("report", detail)
        self.assertEqual(detail["report"]["verdict"]["key"], "decision_ready")

        patch = self.client.patch("/api/sessions/%d" % sid,
                                  json={"self_rating": 4, "notes": "useful"})
        self.assertEqual(patch.get_json()["self_rating"], 4)
        self.assertEqual(patch.get_json()["notes"], "useful")

        again = self.client.get("/api/sessions/%d" % sid).get_json()
        self.assertEqual(again["self_rating"], 4)

    def test_rating_is_validated(self):
        resp = self.client.post("/api/analyze", json={
            "text": "Decision\n\nWe need to decide.\n", "save": True})
        sid = resp.get_json()["session_id"]
        patch = self.client.patch("/api/sessions/%d" % sid, json={"self_rating": 99})
        self.assertIsNone(patch.get_json()["self_rating"])

    def test_missing_session_is_404(self):
        self.assertEqual(self.client.get("/api/sessions/999999").status_code, 404)
        self.assertEqual(self.client.get("/api/export/999999").status_code, 404)

    def test_exports(self):
        resp = self.client.post("/api/analyze", json={
            "text": samples.SAMPLES["checkout-postgres-memo"]["text"],
            "doc_type": "memo", "save": True})
        sid = resp.get_json()["session_id"]

        md = self.client.get("/api/export/%d?fmt=md" % sid)
        self.assertEqual(md.status_code, 200)
        self.assertIn("text/markdown", md.headers["Content-Type"])
        self.assertIn("Decision Memo Review", md.get_data(as_text=True))

        js = self.client.get("/api/export/%d?fmt=json" % sid)
        self.assertEqual(js.status_code, 200)
        payload = json.loads(js.get_data(as_text=True))
        self.assertIn("verdict", payload)


if __name__ == "__main__":
    unittest.main()
