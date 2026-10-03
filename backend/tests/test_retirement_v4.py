"""S1 product routes cannot enter historical import or pipeline execution."""
from unittest.mock import patch

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
        with patch("app.api.preview") as preview:
            response = self.client.post("/api/imports/preview?kind=participants&format=csv", content=source)
            self.assertEqual(response.status_code, 409)
            preview.assert_not_called()
        self.assertEqual(self.client.post("/api/imports/columns?format=csv", content=source).status_code, 409)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": []}).status_code, 409)
        self.assertEqual(self.client.get("/api/cases").json(), [])

    def test_key_state_works_without_loading_old_pipeline_and_changes_are_blocked(self):
        self.client = self.client_for("developer")
        with patch("app.settings.view", side_effect=AssertionError("historical pipeline loaded")):
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
                self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.client.get("/api/settings-s1").status_code, 200)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action IN ('settings.draft','settings.activate','settings.trial')").fetchone()[0], 0)
