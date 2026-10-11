"""U06 Q03: 교수/검토자는 발급된 리포트를 조회만 할 수 있고, 발급·중지·재시도와 운영 정보는 받지 못한다."""
import unittest

from fastapi.testclient import TestClient

from app.api import create_app
from app.auth import password_hash
from app.report_pdf_v4 import render_pdf
from app.report_render_v4 import render_html
from tests import test_report_runs_v4 as support

PASSWORD = "Synthetic-Password-2026!"


class ReportReviewerReadV4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.ReportRunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.fixture.render.side_effect = lambda profile, header, images: (render_html(profile, header, images), render_pdf(profile, header, images))
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET password_hash=?", (password_hash(PASSWORD),))
        self.app = create_app(self.store.root)
        self.operator = self.login("operator")
        self.reviewer = self.login("reviewer")
        f = self.fixture
        self.path = f"/api/cases/{f.case_id}/sessions/{f.session_id}/report-runs-s1"

    def login(self, name):
        client = TestClient(self.app, base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"})
        self.addCleanup(client.close)
        self.assertEqual(client.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code, 200)
        return client

    def issue(self):
        created = self.operator.post(self.path, json=self.fixture.request.model_dump(mode="json"))
        self.assertEqual(created.status_code, 201, created.text)
        self.fixture.work()
        return created.json()["run_id"]

    def test_reviewer_can_list_and_view_without_operating_details_but_cannot_issue_or_change(self):
        run_id = self.issue()
        listed = self.reviewer.get(self.path)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["run_id"] for item in listed.json()], [run_id])
        shown = self.reviewer.get(f"/api/report-runs-s1/{run_id}")
        self.assertEqual(shown.status_code, 200, shown.text)
        for value in (listed.json()[0], shown.json()):
            self.assertEqual((value["steps"], value["planned_provider_calls"], value["max_ai_calls"]), ([], 0, 0))
            self.assertEqual(value["publication_state"], "issued")
        operator_view = self.operator.get(f"/api/report-runs-s1/{run_id}").json()
        self.assertTrue(operator_view["steps"])
        request = self.fixture.request.model_copy(update={"request_id": "reviewer-attempt"}).model_dump(mode="json")
        self.assertEqual(self.reviewer.post(self.path, json=request).status_code, 403)
        body = {"expected_updated_at": shown.json()["updated_at"], "reason": "synthetic reviewer attempt"}
        self.assertEqual(self.reviewer.post(f"/api/report-runs-s1/{run_id}/stop", json=body).status_code, 403)
        self.assertEqual(self.reviewer.post(f"/api/report-runs-s1/{run_id}/retry", json=body).status_code, 403)

    def test_reviewer_download_still_needs_the_existing_disclosure_rules(self):
        run_id = self.issue()
        url = f"{self.path}/{run_id}/files/"
        self.assertEqual(self.operator.get(url + "html").status_code, 200)
        for kind in ("html", "pdf", "manifest"):
            denied = self.reviewer.get(url + kind)
            self.assertIn(denied.status_code, (403, 409), (kind, denied.text))
        anonymous = TestClient(self.app, base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"})
        self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.get(self.path).status_code, 401)
        developer = self.login("developer")
        self.assertEqual(developer.get(self.path).status_code, 403)
