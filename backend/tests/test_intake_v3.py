"""Current intake defaults, independent consents and immutable migration history."""

import hashlib
import json
from io import BytesIO
from pathlib import Path
import tempfile

from openpyxl import Workbook

from app import maintenance
from app.api import create_app
from app.input_models import Manifest
from app.storage import Store
from tests.support import AppCase


class IntakeV3Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root, intake_spec="20260929")
        self.client = self.client_for("operator")

    def test_current_defaults_and_legacy_consent_never_expand(self):
        response = self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": "new",
                                    "dog_name": "합성", "consent_confirmed": True})
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        session = item["manifest"]["sessions"][0]
        self.assertEqual((session["protocol_version"], session["survey_version"], session["protocol_source"]),
                         ("protocol-20260929-v3", "survey-20260929-v3", "new_session"))
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
                self.assertEqual(maintenance.deletion_records(deleted), {("TEST", "0001")})
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_csv_and_xlsx_consent_states_match_and_invalid_values_reject(self):
        columns = ["event_id", "participant_id", "dog_name", "consent_confirmed", "consent_analysis_feedback", "consent_stranger_contact"]
        rows = [["TEST", "import", "합성", "예", "확인", "거절"], ["TEST", "bad", "합성", "예", "maybe", ""]]
        csv_data = (",".join(columns) + "\n" + "\n".join(",".join(row) for row in rows)).encode()
        workbook = Workbook()
        workbook.active.append(columns)
        for row in rows:
            workbook.active.append(row)
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        previews = []
        for format, data in (("csv", csv_data), ("xlsx", output.getvalue())):
            result = self.client.post(f"/api/imports/preview?kind=participants&format={format}", content=data).json()
            self.assertEqual((len(result["rows"]), len(result["errors"])), (1, 1))
            previews.append(result["rows"])
        self.assertEqual(previews[0], previews[1])
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": previews[0]}).status_code, 200)
        item = self.client.get("/api/cases").json()[0]
        self.assertEqual(item["consents"], {"analysis_feedback": "confirmed", "stranger_contact": "declined"})

    def test_v2_migration_preserves_values_and_only_recording_evidence_sets_protocol(self):
        for confirmed in (False, True):
            item = self.upload(self.make_case(participant_id=str(confirmed))).json()
            raw = item["manifest"]
            raw.update(schema_version="intake-2.0", consents=None)
            for field in ("consents", "prior_inputs"):
                del raw[field]
            session = raw["sessions"][0]
            for field in ("protocol_version", "protocol_source", "survey_blank_reasons", "comparison_eligibility", "recording"):
                del session[field]
            session["survey_version"] = "catalog-20260913-v2"
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
                Store(self.root)
                migrated = self.get_case(item)
                current = migrated["manifest"]["sessions"][0]
                self.assertEqual(current["protocol_version"], "protocol-20260913-v2" if confirmed else "unconfirmed")
                self.assertEqual(current["survey"]["s10"], 5)
                self.assertEqual(current["segments"], session["segments"])
                self.assertEqual(migrated["input_revision"], item["input_revision"] + 1)
                self.assertEqual(migrated["consents"]["analysis_feedback"], "unknown")
                self.assertEqual(self.store.path(key).read_bytes(), data)
            header = "event_id,participant_id,survey_version," + ",".join(session["survey"])
            values = ["5" if question == "s10" else "" for question in session["survey"]]
            imported = self.client.post("/api/imports/preview?kind=survey&format=csv",
                content=(header + "\nTEST," + str(confirmed) + ",catalog-20260913-v2," + ",".join(values)).encode()).json()
            self.assertEqual(imported["errors"], [])
            self.assertEqual(self.client.post("/api/imports/commit", json={"rows": imported["rows"]}).status_code, 200)
            if confirmed:
                draft = self.client.put(f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}/segments", json={
                    "expected_revision": migrated["input_revision"], "video_id": session["videos"][0]["video_id"],
                    "windows": session["segments"]["windows"]})
                self.assertEqual(draft.status_code, 200, draft.text)
                self.assertEqual(draft.json()["manifest"]["sessions"][0]["protocol_version"], "protocol-20260913-v2")

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
        for fault in ("version", "question", "duplicate", "timing_video"):
            with self.subTest(fault=fault):
                item = self.upload(self.make_case(fault)).json()
                session = item["manifest"]["sessions"][0]
                legacy = {key: value for key, value in item["manifest"].items() if key not in ("consents", "prior_inputs")}
                legacy["schema_version"] = "intake-2.0"
                for field in ("protocol_version", "protocol_source", "survey_blank_reasons", "comparison_eligibility", "recording"):
                    del session[field]
                session["survey_version"] = "catalog-20260913-v2"
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
                self.assertEqual([value["case_id"] for value in listed.json()], [healthy["case_id"]])
