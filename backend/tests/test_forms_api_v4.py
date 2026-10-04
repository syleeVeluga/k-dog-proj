"""S1 Forms transport, roles, survey policy and maintenance integration."""

import base64
import json

from app.api import create_app
from app.maintenance import clean, references
from tests.support import AppCase


class FormsApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")
        self.version = self.client.get("/api/catalog/survey").json()["version"]

    def config(self, **columns):
        return {"request_id": "preview-1", "event_id": "S1FORMS", "filename": "synthetic.csv", "format": "csv",
                "mapping": {"version": "map-1", "source_profile": "synthetic-forms", "survey_version": self.version,
                            "columns": columns, "answer_labels": {}}, "targets": []}

    def stage(self, source, config):
        return self.client.post("/api/forms/preview", json={"config": config,
            "file_base64": base64.b64encode(source.encode()).decode()})

    def apply(self, preview):
        return self.client.post("/api/forms/commit", json={"request_id": "commit-1",
            "preview_id": preview["preview_id"], "preview_hash": preview["preview_hash"]})

    def test_file_transport_creates_once_and_survey_calculates_zero_without_fallback(self):
        config = self.config(dog_name="반려견", s10="Q10", s11="Q11", s12="Q12", s13="Q13", s14="Q14", s26="Q26", s27="Q27", s28="Q28")
        response = self.stage("반려견,Q10,Q11,Q12,Q13,Q14,Q26,Q27,Q28\n합성견,0,2,0,1,2,1,3,5\n", config)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview["errors"], [])
        committed = self.apply(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(self.apply(preview).json(), committed.json())
        self.assertEqual(len(self.client.get("/api/cases").json()), 1)
        case_id = committed.json()["rows"][0]["case_id"]
        result = self.client.get(f"/api/cases/{case_id}/survey/result")
        self.assertEqual(result.status_code, 200, result.text)
        result = result.json()
        self.assertEqual(result["policy_version"], "survey-policy-20261002-s1.1")
        fear = [d for d in result["domains"] if d["question_ids"][0] in ("s10", "s12")]
        self.assertEqual([d["mean"] for d in fear], [1, 1])
        self.assertEqual([q["converted"] for q in result["items"][-3:]], [5, 3, 1])
        self.assertIsNone(result["registration_complete"])
        self.assertEqual(result["external_comparison_status"], "pending_approval")

    def test_invalid_base64_and_roles_never_create_preview_artifacts(self):
        payload = {"config": self.config(dog_name="name"), "file_base64": "@not-base64"}
        self.assertEqual(self.client.post("/api/forms/preview", json=payload).status_code, 422)
        for role, status in ((None, 401), ("reviewer", 403), ("developer", 403)):
            response = self.client_for(role).post("/api/forms/preview", json=payload)
            self.assertEqual(response.status_code, status)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='forms.preview'").fetchone()[0], 0)

    def test_column_inspection_respects_transposed_layout_and_rejects_formula(self):
        response = self.client.post("/api/forms/columns?format=csv&layout=transposed", content="항목,참가자1\n반려견,합성견\nQ10,0\n".encode())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([c["key"] for c in response.json()["columns"]], ["항목", "반려견", "Q10"])
        response = self.client.post("/api/forms/columns?format=csv", content=b"name\n=1+1\n")
        self.assertEqual(response.status_code, 422)

    def test_raw_header_names_are_data_during_backup_and_deleted_case_cleanup(self):
        config = self.config(dog_name="ref", guardian_name="storage_ref", s01="metadata_json")
        config["mapping"]["answer_labels"] = {"s01": {"unparsed raw label": 3}}
        response = self.stage("ref,storage_ref,metadata_json\nSyntheticDog,SyntheticGuardian,unparsed raw label\n", config)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        with self.store.connect() as db:
            before = references(self.store, db)
        self.assertTrue(any("source" in ref for ref in before))
        response = self.apply(preview)
        self.assertEqual(response.status_code, 200, response.text)
        with self.store.connect() as db:
            refs = references(self.store, db)
        self.assertTrue(any("row" in ref for ref in refs))
        case_id = response.json()["rows"][0]["case_id"]
        item = self.client.get(f"/api/cases/{case_id}").json()
        self.delete_case(item)
        clean(self.store, purge_deleted=True)
        self.assertTrue(all(not self.store.path(ref).exists() for ref in refs))
        with self.store.connect() as db:
            tombstones = [json.loads(r[0]) for r in db.execute("SELECT detail_json FROM changes WHERE action='forms.purged'")]
        self.assertTrue(tombstones)
        self.assertNotIn("SyntheticGuardian", json.dumps(tombstones))
        config["request_id"] = "retry-deleted"
        self.assertEqual(self.stage("ref,storage_ref,metadata_json\nSyntheticDog,SyntheticGuardian,unparsed raw label\n", config).status_code, 409)
