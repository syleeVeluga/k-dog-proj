import json
from unittest.mock import patch

from app.api import create_app
from app.capture_v4 import validate_recording_media_v4
from tests.support import AppCase
from tests.test_recording_v4 import coverage, event, fixture


class RecordingApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")
        self.item = self.upload(self.make_case()).json()
        self.video = self.item["manifest"]["sessions"][0]["videos"][0]
        self.path = f"/api/cases/{self.item['case_id']}/sessions/{self.item['selected_session_id']}/recording-s1"
        self.record = json.loads(json.dumps(fixture()).replace('"v1"', json.dumps(self.video["video_id"])))
        self.probe = patch("app.recording_v4.probe", return_value={"duration_sec": 300})
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def save(self, record=None):
        return self.client.put(self.path, json={"expected_revision": self.item["input_revision"],
                                               "recording": self.record if record is None else record})

    def test_strict_json_arrays_save_and_old_procedure_facts_remain_exact(self):
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.item["case_id"])
            manifest = self.store.manifest(row)
            manifest.sessions[0].protocol_version = "unconfirmed"
            manifest.sessions[0].protocol_source = "unconfirmed"
            self.store.save(db, row, manifest, "operator", "test.raw-facts")
        self.item = self.get_case(self.item)
        before = self.item["manifest"]["sessions"][0]
        self.assertIsNone(self.client.get(self.path).json()["recording"])
        response = self.save()
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()["manifest"]["sessions"][0]
        for field in ("recording", "segments", "stimuli", "protocol_version", "protocol_source", "videos"):
            self.assertEqual(after[field], before[field])
        self.assertTrue(after["recording_s1"]["confirmed"])
        self.assertFalse(after["recording_review_required"])
        state = self.client.get(self.path).json()
        self.assertTrue(state["windows"])
        self.assertTrue(state["gates"])
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.client.get("/api/catalog/protocol-s1").status_code, 200)

    def test_previous_session_is_readable_but_cannot_be_edited(self):
        saved = self.save()
        self.assertEqual(saved.status_code, 200, saved.text)
        selected = self.client.post(f"/api/cases/{self.item['case_id']}/sessions",
            json={"expected_revision": saved.json()["input_revision"], "note": "synthetic next session"})
        self.assertEqual(selected.status_code, 200, selected.text)
        historical = self.client_for("reviewer").get(self.path)
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()["recording"], saved.json()["manifest"]["sessions"][0]["recording_s1"])
        self.item = selected.json()
        self.assertEqual(self.save().status_code, 409)

    def test_preserved_video_registration_keeps_bytes_identity_and_retries_once(self):
        path = self.path.removesuffix("recording-s1") + f"videos/{self.video['video_id']}/registration"
        value = {"request_id": "preserved-registration", "expected_revision": self.item["input_revision"], "camera_id": "CAM2"}
        self.assertEqual(self.client.put(path, json=value).status_code, 422)
        value["source_kind"] = "original"
        response = self.client.put(path, json=value)
        self.assertEqual(response.status_code, 200, response.text)
        current = response.json()["manifest"]["sessions"][0]["videos"][0]
        for field in ("video_id", "storage_ref", "sha256", "size_bytes", "original_name"):
            self.assertEqual(current[field], self.video[field])
        self.assertEqual((current["camera_id"], current["source_original_number"]), ("CAM2", "3"))
        self.assertEqual(self.client.put(path, json=value).json()["input_revision"], response.json()["input_revision"])
        self.assertEqual(self.client_for("reviewer").put(path, json=value).status_code, 403)

    def test_invalid_cross_session_and_beyond_media_times_do_not_publish(self):
        record = json.loads(json.dumps(self.record).replace(self.video["video_id"], "foreign-video"))
        self.assertEqual(self.save(record).status_code, 422)
        with patch("app.recording_v4.probe", return_value={"duration_sec": 20}):
            self.assertEqual(self.save().status_code, 422)
        record = {**self.record, "fabricated_rule": True}
        self.assertEqual(self.save(record).status_code, 422)
        self.assertIsNone(self.client.get(self.path).json()["recording"])

    def test_late_revision_or_file_mutation_blocks_adoption(self):
        def revise(*args):
            value = validate_recording_media_v4(*args)
            with self.store.connect(write=True) as db:
                row = self.store.case(db, self.item["case_id"])
                self.store.save(db, row, self.store.manifest(row), "operator", "test.other-save")
            return value
        with patch("app.capture_v4.validate_recording_media_v4", side_effect=revise):
            self.assertEqual(self.save().status_code, 409)
        self.item = self.get_case(self.item)

        def mutate(*args):
            value = validate_recording_media_v4(*args)
            self.store.path(self.video["storage_ref"]).write_bytes(b"changed synthetic bytes")
            return value
        with patch("app.capture_v4.validate_recording_media_v4", side_effect=mutate):
            self.assertEqual(self.save().status_code, 409)
        self.assertIsNone(self.client.get(self.path).json()["recording"])

    def test_invalid_logical_window_is_rejected_before_publication(self):
        record = {**self.record, "coverage": [coverage("retired-window", 0, 5, video=self.video["video_id"])]}
        self.assertEqual(self.save(record).status_code, 422)
        record = {**self.record, "events": [
            event("free-a", "free_movement", "entry", 0, 10, video=self.video["video_id"]),
            event("free-b", "free_movement", "entry", 5, 15, video=self.video["video_id"])]}
        self.assertEqual(self.save(record).status_code, 422)
        self.assertEqual(self.get_case(self.item)["input_revision"], self.item["input_revision"])
        self.assertIsNone(self.client.get(self.path).json()["recording"])

    def test_confirmed_legacy_procedure_still_needs_s1_review(self):
        response = self.save({**self.record, "procedure_edition": "legacy"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["manifest"]["sessions"][0]["recording_review_required"])

    def test_access_changes_during_probe_and_roles_are_rechecked(self):
        for role, expected in ((None, 401), ("reviewer", 403), ("developer", 403)):
            self.assertEqual(self.client_for(role).put(self.path, json={}).status_code, expected)
        def deactivate(*args):
            value = validate_recording_media_v4(*args)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
            return value
        with patch("app.capture_v4.validate_recording_media_v4", side_effect=deactivate):
            self.assertEqual(self.save().status_code, 401)

    def test_consent_and_deletion_rechecked_after_probe(self):
        def decline(*args):
            value = validate_recording_media_v4(*args)
            with self.store.connect(write=True) as db:
                row = self.store.case(db, self.item["case_id"])
                manifest = self.store.manifest(row)
                manifest.consents.analysis_feedback = "declined"
                self.store.save(db, row, manifest, "operator", "test.decline")
            return value
        with patch("app.capture_v4.validate_recording_media_v4", side_effect=decline):
            self.assertIn(self.save().status_code, (403, 409))
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.item = self.get_case(self.item)
        self.delete_case(self.item)
        self.assertEqual(self.client.get(self.path).status_code, 403)
