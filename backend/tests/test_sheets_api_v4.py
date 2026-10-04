import json
from unittest.mock import patch

from app.api import create_app
from app.domain.catalog_v4 import OPTIONAL_CODES, load_catalog_v4
from tests.support import AppCase
from tests.test_recording_v4 import fixture


class SheetsApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")
        self.probe = patch("app.recording_v4.probe", return_value={"duration_sec": 300})
        self.probe.start()
        self.addCleanup(self.probe.stop)
        item = self.make_case()
        content = b"synthetic source for API contract"
        receipt = self.client.post("/api/uploads", json={"request_id": "source", "filename": "source.mp4",
            "expected_size": len(content)}).json()
        self.client.put(f"/api/uploads/{receipt['upload_id']}/content?request_id=source", content=content)
        self.client.post(f"/api/uploads/{receipt['upload_id']}/link", json={"case_id": item["case_id"],
            "session_id": item["selected_session_id"], "expected_revision": item["input_revision"], "camera_id": "CAM1"})
        self.item = self.get_case(item)
        video = self.item["manifest"]["sessions"][0]["videos"][0]
        record = json.loads(json.dumps(fixture()).replace('"v1"', json.dumps(video["video_id"])))
        self.base = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}"
        response = self.client.put(self.base + "/recording-s1", json={"expected_revision": self.item["input_revision"], "recording": record})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()

    def assign(self, username):
        response = self.client.post(self.base + "/sheets-s1", json={"expected_revision": self.item["input_revision"],
            "assigned_username": username, "rater_id": username, "rater_name": "합성 평가자"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_independent_owner_submit_reopen_history_and_strict_values_over_http(self):
        own, other = self.assign("operator"), self.assign("reviewer")
        path = f"/api/score-sheets-s1/{own['sheet_id']}"
        self.assertEqual(len(self.client.get(self.base + "/sheets-s1").json()), 2)
        self.assertEqual(self.client.get(f"/api/score-sheets-s1/{other['sheet_id']}").status_code, 403)
        self.assertEqual(self.client_for("reviewer").get(path).status_code, 403)
        view = self.client.get(path)
        self.assertEqual(view.status_code, 200, view.text)
        self.assertEqual(view.json()["document"]["sheet"]["observations"], [])
        bad = self.client.put(path, json={"expected_revision": 1, "observations": [{"code": "개5", "value": True, "status": "observed"}]})
        self.assertEqual(bad.status_code, 422)
        observations = [{"code": item.code, "value": None, "status": "unobserved", "reason": "합성 관찰 미실시"}
                        for item in load_catalog_v4().rated_items() if item.code not in OPTIONAL_CODES]
        saved = self.client.put(path, json={"expected_revision": 1, "observations": observations})
        self.assertEqual(saved.status_code, 200, saved.text)
        submitted = self.client.post(path + "/submit", json={"expected_revision": 2, "reason": "합성 원자료 제출"})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["state"], "submitted")
        self.assertEqual(self.client.put(path, json={"expected_revision": 3, "observations": observations}).status_code, 409)
        reopened = self.client.post(path + "/reopen", json={"expected_revision": 3, "reason": "원기록 보존하고 재확인"})
        self.assertEqual(reopened.status_code, 200, reopened.text)
        historical = self.client.get(path + "/revisions/3")
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["state"], "submitted")
        self.assertEqual(len(historical.json()["sheet"]["observations"]), 86)
        self.assertEqual(self.client.get("/api/catalog/behavior-s1").status_code, 200)
        self.assertFalse(self.client.get("/api/import/s1-workbook/status").json()["excel_import_enabled"])

    def test_nonowners_cannot_bypass_assignment_through_history_or_mutations(self):
        sheet = self.assign("reviewer")
        path = f"/api/score-sheets-s1/{sheet['sheet_id']}"
        self.assertEqual(self.client.get(path + "/revisions/1").status_code, 403)
        self.assertEqual(self.client.put(path, json={"expected_revision": 1, "observations": []}).status_code, 403)
        self.assertEqual(self.client_for("developer").get("/api/catalog/behavior-s1").status_code, 403)
        self.assertEqual(self.client_for().get(path).status_code, 401)
