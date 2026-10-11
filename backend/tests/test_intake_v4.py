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
        self.assertEqual(self.client_for("developer").get("/api/cases").status_code, 409)
        result = self.client_for("operator").get("/api/cases")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertEqual(result.headers["X-Content-Type-Options"], "nosniff")

class IntakeFieldConflictTests(AppCase):
    """U04: 중복은 어느 칸인지, 누가 쓰고 있는지 알려 준다."""

    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")

    def add(self, participant, sequence=None, event="U04", dog="초코"):
        body = {"event_id": event, "participant_id": participant, "dog_name": dog}
        if sequence is not None:
            body["sequence_no"] = sequence
        return self.client.post("/api/cases", json=body)

    def test_duplicate_id_and_sequence_name_the_field_and_the_existing_participant(self):
        self.assertEqual(self.add("0001", 1).status_code, 201)
        response = self.add("0001", 2, dog="다른견")
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual((body["field"], body["existing"]), ("participant_id", {"participant_id": "0001", "dog_name": "초코"}))
        self.assertIn("0001", body["detail"])
        response = self.add("0002", 1, dog="콩이")
        body = response.json()
        self.assertEqual((response.status_code, body["field"]), (409, "sequence_no"))
        self.assertEqual(body["existing"], {"participant_id": "0001", "dog_name": "초코"})
        self.assertIn("순번 1은 이미 0001(초코)이 쓰고 있습니다", body["detail"])
        self.assertEqual(len(self.client.get("/api/cases").json()), 1)

    def test_same_sequence_in_another_event_and_blank_sequences_are_allowed(self):
        self.assertEqual(self.add("0001", 1).status_code, 201)
        self.assertEqual(self.add("0001", 1, event="U04-OTHER").status_code, 201)
        self.assertEqual(self.add("0002").status_code, 201)
        self.assertEqual(self.add("0003").status_code, 201)

    def test_correction_excludes_itself_and_reports_other_participants(self):
        first = self.add("0001", 1).json()
        second = self.add("0002", 2, dog="콩이").json()
        same = {"expected_revision": first["input_revision"], "participant_id": "0001", "dog_name": "초코", "sequence_no": 1}
        self.assertEqual(self.client.put(f"/api/cases/{first['case_id']}", json=same).status_code, 200)
        current = self.client.get(f"/api/cases/{first['case_id']}").json()
        clash = {**same, "expected_revision": current["input_revision"], "sequence_no": 2}
        response = self.client.put(f"/api/cases/{first['case_id']}", json=clash)
        self.assertEqual((response.status_code, response.json()["field"]), (409, "sequence_no"))
        self.assertEqual(response.json()["existing"]["dog_name"], "콩이")
        clash = {**same, "expected_revision": current["input_revision"], "participant_id": "0002"}
        response = self.client.put(f"/api/cases/{first['case_id']}", json=clash)
        self.assertEqual((response.status_code, response.json()["field"]), (409, "participant_id"))
        self.assertEqual(self.client.get(f"/api/cases/{second['case_id']}").json()["participant_id"], "0002")

    def test_a_deletion_requested_participant_is_not_named(self):
        item = self.add("0001", 1).json()
        self.delete_case(item)
        for response, field in ((self.add("0001"), "participant_id"), (self.add("0009", 1), "sequence_no")):
            self.assertEqual((response.status_code, response.json()["field"], response.json()["existing"]), (409, field, None))
            self.assertIn("삭제 요청된 참가자", response.json()["detail"])
