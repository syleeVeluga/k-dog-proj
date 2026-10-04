"""Current intake defaults, independent consents and immutable migration history."""

import hashlib
import json
from pathlib import Path
import tempfile

from app import maintenance
from app.api import create_app
from app.input_models import Manifest, Session
from app.storage import Store
from tests.support import AppCase


class IntakeV3Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")

    def test_current_defaults_and_legacy_consent_never_expand(self):
        response = self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": "new",
                                    "dog_name": "합성", "consent_confirmed": True})
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        session = item["manifest"]["sessions"][0]
        self.assertEqual((session["protocol_version"], session["survey_version"], session["protocol_source"]),
                         ("protocol-20261002-s1.1", "survey-20260929-v3", "new_session"))
        self.assertEqual(item["consents"], {"analysis_feedback": "unknown", "stranger_contact": "unknown"})
        self.assertEqual(session["comparison_eligibility"], "unconfirmed")

    def test_consent_edits_conflicts_history_backup_and_deletion(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}"
        payload = {"expected_revision": item["input_revision"], "participant_id": item["participant_id"],
                   "dog_name": item["dog_name"], "consents": {"analysis_feedback": "confirmed", "stranger_contact": "declined"}}
        saved = self.client.put(path, json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        saved = saved.json()
        self.assertEqual(self.client.put(path, json=payload).status_code, 409)
        del payload["consents"]
        payload["expected_revision"] = saved["input_revision"]
        again = self.client.put(path, json=payload).json()
        self.assertEqual(again["consents"], saved["consents"])
        with self.store.connect() as db:
            history = self.store.manifest(self.store.case(db, item["case_id"])).prior_inputs
            before = json.loads(db.execute("SELECT detail_json FROM changes WHERE action='case.identity' ORDER BY rowid").fetchone()[0])
        self.assertEqual(before["before"]["consents"]["analysis_feedback"], "unknown")
        self.assertEqual(len(history), 2)
        with tempfile.TemporaryDirectory(prefix="kdog-v3-backup-") as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            maintenance.restore(self.store, root / "backup", root / "restored")
            restored = Store(root / "restored")
            with restored.connect() as db:
                manifest = restored.manifest(restored.case(db, item["case_id"]))
                self.assertEqual(manifest.consents.model_dump(), saved["consents"])
                for prior in manifest.prior_inputs:
                    self.assertEqual(hashlib.sha256(restored.path(prior.ref).read_bytes()).hexdigest(), prior.hash)
            self.delete_case(again)
            maintenance.clean(self.store, purge_deleted=True)
            self.assertFalse(any(self.store.path(prior.ref).exists() for prior in history))
            maintenance.restore(self.store, root / "backup", root / "deleted")
            deleted = Store(root / "deleted")
            with deleted.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
                self.assertEqual(maintenance.deletion_records(deleted), {(item["case_id"], "TEST", "0001")})
        self.assertEqual(self.client.get(path).status_code, 404)

    def v2_manifest(self, item):
        raw = {key: value for key, value in item["manifest"].items() if key in Manifest.model_fields}
        raw["schema_version"] = "intake-2.0"
        raw["sessions"] = [{key: value for key, value in session.items() if key in Session.model_fields}
                           for session in raw["sessions"]]
        for session in raw["sessions"]:
            session["survey_version"] = "catalog-20260913-v2"
        return raw

    def test_v2_migration_preserves_values_and_only_recording_evidence_sets_protocol(self):
        items = {confirmed: self.upload(self.make_case(participant_id=str(confirmed))).json()
                 for confirmed in (False, True)}
        for confirmed, item in items.items():
            raw = self.v2_manifest(item)
            session = raw["sessions"][0]
            session["survey"]["s10"] = 5
            if confirmed:
                names = ["entry", "baseline", "alone", "stranger", "reunion", "ignore", "walk", "exit"]
                session["segments"] = {"video_id": session["videos"][0]["video_id"], "confirmed": True,
                    "windows": [{"segment": name, "start_sec": float(i * 20), "end_sec": float(i * 20 + 15)} for i, name in enumerate(names)]}
            data = Manifest.model_validate(raw).model_dump_json().encode()
            key = f"inputs/{item['case_id']}-v2.json"
            self.store.path(key).write_bytes(data)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE cases SET manifest_ref=?,manifest_hash=?,manifest_schema_version='intake-2.0',consent_confirmed=1 WHERE case_id=?",
                           (key, hashlib.sha256(data).hexdigest(), item["case_id"]))
            for _ in range(2):
                restarted = Store(self.root)
                with restarted.connect() as db:
                    migrated = restarted.manifest(restarted.case(db, item["case_id"]))
                current = migrated.sessions[0]
                self.assertEqual(current.protocol_version, "protocol-20260913-v2" if confirmed else "unconfirmed")
                self.assertEqual(current.survey["s10"], 5)
                self.assertEqual(current.segments.model_dump() if current.segments else None, session["segments"])
                self.assertEqual(migrated.input_revision, item["input_revision"] + 1)
                self.assertEqual(migrated.consents.analysis_feedback, "unknown")
                self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 409)
                self.assertEqual(self.store.path(key).read_bytes(), data)

    def test_corrupt_consent_metadata_isolated_as_conflict(self):
        item = self.make_case()
        healthy = self.make_case("healthy")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET consents_v3_json='[]' WHERE case_id=?", (item["case_id"],))
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 409)
        result = self.client.get("/api/cases")
        self.assertEqual(result.headers["X-KDOG-Unavailable-Cases"], "1")
        self.assertEqual([value["case_id"] for value in result.json()], [healthy["case_id"]])

    def test_unmigratable_v2_semantics_are_never_served_as_healthy(self):
        healthy = self.make_case("healthy")
        faults = ("version", "question", "duplicate", "timing_video")
        items = {fault: self.upload(self.make_case(fault)).json() for fault in faults}
        for fault in faults:
            with self.subTest(fault=fault):
                item = items[fault]
                legacy = self.v2_manifest(item)
                session = legacy["sessions"][0]
                if fault == "version":
                    session["survey_version"] = "unsupported-survey"
                elif fault == "question":
                    del session["survey"]["s01"]
                elif fault == "duplicate":
                    legacy["sessions"].append(session.copy())
                else:
                    session["stimuli"] = {"video_id": "missing", "input_revision": 1,
                                          "source": "operator_confirmed", "moments": {"entry": 1.0}}
                data = json.dumps(legacy).encode()
                key = f"inputs/{item['case_id']}-corrupt-v2.json"
                self.store.path(key).write_bytes(data)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE cases SET manifest_ref=?,manifest_hash=?,manifest_schema_version='intake-2.0' WHERE case_id=?",
                               (key, hashlib.sha256(data).hexdigest(), item["case_id"]))
                Store(self.root)
                self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 409)
                self.assertEqual(self.store.path(key).read_bytes(), data)
                listed = self.client.get("/api/cases")
                self.assertEqual(listed.status_code, 409)
                self.assertEqual(self.client.get(f"/api/cases/{healthy['case_id']}").status_code, 409)
