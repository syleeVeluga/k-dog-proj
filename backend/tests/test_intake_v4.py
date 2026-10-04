"""S1-only default entry and preservation of raw inputs/revisions."""

import hashlib
import json

from app.api import create_app
from app.input_models_v4 import ManifestV4, upgrade_to_s1
from tests.support import AppCase


class IntakeV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        self.version = self.client.get("/api/catalog/survey").json()["version"]

    def test_default_new_case_has_s1_contract_and_no_copied_scores(self):
        item = self.make_case()
        manifest = ManifestV4.model_validate(item["manifest"])
        self.assertEqual(manifest.sessions[0].scoring_catalog_version, "catalog-20261002-s1.1")
        self.assertEqual(manifest.sessions[0].protocol_version, "protocol-20261002-s1.1")
        self.assertTrue(all(value is None for value in manifest.sessions[0].survey.values()))
        self.assertEqual(item["scoring_status"], "reanalysis_required")
        self.assertIsNone(manifest.display_run_id)
        self.assertEqual(manifest.prior_inputs, [])
        self.assertEqual(self.client.get("/api/health").json()["spec"], "20261002")
        with self.assertRaises(ValueError):
            upgrade_to_s1(manifest)

    def test_raw_zero_video_hash_and_new_s1_revision_history_survive_updates(self):
        item = self.make_case()
        item = self.upload(item, b"synthetic-original-video").json()
        value = self.answers(item)
        value["answers"]["s10"] = 0
        value["answers"]["s11"] = None
        value["blank_reasons"] = {"s11": "합성 미응답"}
        response = self.client.put(f"/api/cases/{item['case_id']}/survey", json=value)
        self.assertEqual(response.status_code, 200, response.text)
        manifest = response.json()["manifest"]
        self.assertEqual(manifest["sessions"][0]["survey"]["s10"], 0)
        self.assertIsNone(manifest["sessions"][0]["survey"]["s11"])
        self.assertEqual(manifest["sessions"][0]["videos"][0]["sha256"], hashlib.sha256(b"synthetic-original-video").hexdigest())
        self.assertEqual(len(manifest["prior_inputs"]), 2)
        for prior in manifest["prior_inputs"]:
            raw = self.store.path(prior["ref"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), prior["hash"])
            self.assertEqual(json.loads(raw)["schema_version"], "intake-4.0")

    def test_pending_s1_features_never_fall_back_to_old_scoring(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}"
        for url in (path + "/sheets", path + "/runs-v3", path + "/preprocess", "/api/catalog/behavior-v3"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, response.text)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM score_sheets").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_previous_manifest_requires_explicit_reset_before_default_operations(self):
        item = self.make_old_case()
        self.app = create_app(self.root)
        current = self.client_for("operator")
        self.assertEqual(current.get("/api/cases").status_code, 409)
        self.assertEqual(current.get(f"/api/cases/{item['case_id']}").status_code, 409)

    def test_s1_readiness_follows_authentication_and_role_checks(self):
        self.make_old_case()
        self.app = create_app(self.root)
        anonymous = self.client_for()
        for path in ("/api/cases", "/api/score-sheets-s1/missing", "/api/scoring-ai-s1/readiness"):
            result = anonymous.get(path)
            self.assertEqual(result.status_code, 401, result.text)
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertEqual(result.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client_for("developer").get("/api/cases").status_code, 403)
        result = self.client_for("operator").get("/api/cases")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertEqual(result.headers["X-Content-Type-Options"], "nosniff")
