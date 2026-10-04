"""S1 product routes cannot enter historical import or pipeline execution."""
from app.api import create_app
from tests.support import AppCase


class RetirementV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")

    def test_old_partial_import_never_writes_s1_rows(self):
        source = b"event_id,participant_id,dog_name\nTEST,0001,Synthetic\nTEST,0001,Duplicate\n"
        response = self.client.post("/api/imports/preview?kind=participants&format=csv", content=source)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post("/api/imports/columns?format=csv", content=source).status_code, 404)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": []}).status_code, 404)
        self.assertEqual(self.client.get("/api/cases").json(), [])

    def test_key_state_works_without_loading_old_pipeline_and_changes_are_blocked(self):
        self.client = self.client_for("developer")
        response = self.client.get("/api/developer/settings")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {"keys"})
        self.assertEqual({key["provider"] for key in response.json()["keys"]}, {"gemini", "openai", "anthropic"})
        for method, path, body in (
            ("post", "/api/developer/settings/drafts", {}),
            ("get", "/api/developer/settings/legacy", None),
            ("post", "/api/developer/settings/legacy/activate", {"expected_active": "legacy"}),
            ("post", "/api/developer/settings/legacy/trial", {"stage": "dog", "mode": "provider"}),
        ):
            with self.subTest(path=path):
                result = getattr(self.client, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(result.status_code, 404, result.text)
        self.assertEqual(self.client.get("/api/settings-s1").status_code, 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action IN ('settings.draft','settings.activate','settings.trial')").fetchone()[0], 0)

    def test_api_schema_has_only_current_routes_and_no_unknown_catchall(self):
        paths = self.app.openapi()["paths"]
        self.assertIn("/api/settings-s1", paths)
        self.assertNotIn("/api/{path}", paths)
        self.assertNotIn("/api/cases/{case_id}/runs-v3", paths)
        self.assertNotIn("/api/imports/preview", paths)
        self.assertNotIn("/api/developer/settings/drafts", paths)
        for method in ("get", "post", "put", "delete", "patch"):
            response = getattr(self.client, method)("/api/retired-unknown")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "API 경로가 없습니다."})
