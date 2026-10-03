import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from app import judgements_v4 as results, sheets_v4 as sheets
from app.domain.catalog_v4 import OPTIONAL_CODES, load_catalog_v4
from app.domain.results_v4 import BasicResultV4
from app.storage import encode
from tests import test_sheets_v4 as support


def model(cls, **values):
    return cls.model_validate_json(encode(values))


class JudgementsV4Tests(unittest.TestCase):
    def setUp(self):
        self.helper=support.SheetsV4Tests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.store=self.helper.store
        self.user=self.helper.people["reviewer"]
        self.sheet=self.helper.assign()
        observations=[{"code":item.code,"value":None,"status":"unobserved","reason":"synthetic missing"} for item in load_catalog_v4().rated_items() if item.code not in OPTIONAL_CODES]
        observations=[self.helper.observe("보23",2,"stranger_whole",215,245,True) if item["code"]=="보23" else item for item in observations]
        self.sheet=self.helper.save(self.sheet,observations)
        self.sheet=sheets.revise(self.store,self.sheet["sheet_id"],model(sheets.SheetReasonV4,expected_revision=self.sheet["revision"],reason="synthetic submit"),self.user,"submit")
        self.request=model(results.CalculateV4,input={"sheet_id":self.sheet["sheet_id"],"revision":self.sheet["revision"],"ref":self.sheet["manifest_ref"],"hash":self.sheet["manifest_hash"]})

    def create(self, **kwargs):
        request=model(results.CalculateV4,**{**self.request.model_dump(mode="json"),**kwargs})
        return results.create(self.store,self.sheet["sheet_id"],request,self.user)

    def edit(self, result, status="complete", **kwargs):
        edit={"key":"owner_type","label":"통제형" if status!="held" else None,"status":status,"evidence_codes":["보23"],"counter_note":"synthetic opposing evidence reviewed","reason":"synthetic judgement"}
        edit.update(kwargs)
        value=model(results.JudgementEditV4,expected_revision=result["summary"]["revision"],reason="synthetic revision",decisions=[edit])
        return results.revise(self.store,result["summary"]["result_id"],value,self.user)

    def test_result_fixes_submitted_input_rules_conditions_and_automatic(self):
        value=self.create(same_object=True,same_object_reason="synthetic identity confirmation")
        doc=BasicResultV4.model_validate_json(encode(value["document"]))
        self.assertEqual(doc.input,self.request.input)
        self.assertEqual(doc.rule_hash,doc.input_document.source.asset_hashes["scoring"])
        self.assertTrue(doc.conditions.same_object)
        self.assertEqual(doc.decisions,doc.automatic_decisions)
        self.assertIsNone(doc.calculations.owner.ratios)
        self.assertEqual(len(results.list_results(self.store,self.sheet["sheet_id"],self.user)),1)
        self.assertEqual(results.ResultViewV4.model_validate(value).summary.revision,1)

    def test_manual_complete_preserves_automatic_and_input_old_revision(self):
        initial=self.create()
        updated=self.edit(initial)
        doc=updated["document"]
        self.assertEqual(doc["revision"],2)
        self.assertEqual(doc["actor"],self.user.username)
        self.assertEqual(doc["automatic_decisions"],initial["document"]["automatic_decisions"])
        self.assertEqual(doc["calculations"],initial["document"]["calculations"])
        self.assertEqual(doc["decision_sources"]["owner_type"],"human")
        self.assertEqual(next(x for x in doc["decisions"] if x["key"]=="owner_type")["label"],"통제형")
        old=results.view(self.store,doc["result_id"],self.user,1)
        self.assertEqual(old["document"],initial["document"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='basic.judgement'").fetchone()[0],1)

    def test_counter_codes_survive_identical_scene_evidence(self):
        self.sheet = sheets.revise(self.store, self.sheet["sheet_id"], model(sheets.SheetReasonV4,
            expected_revision=self.sheet["revision"], reason="synthetic correction"), self.helper.people["operator"], "reopen")
        observations = [item.model_dump(mode="json") for item in sheets.document_for(self.store, self.sheet).sheet.observations]
        basis = next(item for item in observations if item["code"] == "보23")
        observations = [{**copy.deepcopy(basis), "code": "보24"} if item["code"] == "보24" else item for item in observations]
        self.sheet = self.helper.save(self.sheet, observations)
        self.sheet = sheets.revise(self.store, self.sheet["sheet_id"], model(sheets.SheetReasonV4,
            expected_revision=self.sheet["revision"], reason="synthetic resubmit"), self.user, "submit")
        self.request = model(results.CalculateV4, input={"sheet_id": self.sheet["sheet_id"], "revision": self.sheet["revision"],
            "ref": self.sheet["manifest_ref"], "hash": self.sheet["manifest_hash"]})
        edited = self.edit(self.create(), evidence_codes=["보23", "보24"], counter_codes=["보24"], counter_note=None)
        result = results.view(self.store, edited["summary"]["result_id"], self.user)
        decision = result["document"]["manual_decisions"][0]
        self.assertEqual(decision["counter_codes"], ["보24"])
        self.assertEqual(decision["evidence"], decision["counter_evidence"])
        revised = self.edit(result, evidence_codes=decision["evidence_codes"], counter_codes=decision["counter_codes"], counter_note=None)
        self.assertEqual(revised["document"]["manual_decisions"][0]["counter_codes"], ["보24"])

    def test_incomplete_draft_does_not_override_automatic(self):
        initial=self.create()
        updated=self.edit(initial,"draft",evidence_codes=[],counter_note=None)
        self.assertEqual(updated["document"]["decisions"],initial["document"]["automatic_decisions"])
        self.assertEqual(updated["document"]["decision_sources"]["owner_type"],"automatic")
        self.assertEqual(updated["document"]["manual_decisions"][0]["label"],"통제형")
        with self.assertRaises(HTTPException) as caught:self.edit(initial,evidence_codes=[])
        self.assertEqual(caught.exception.status_code,409)
        with self.assertRaises(HTTPException) as caught:self.edit(updated,evidence_codes=[])
        self.assertEqual(caught.exception.status_code,422)

    def test_manual_missing_opposing_basis_foreign_code_and_unknown_type_reject(self):
        result=self.create()
        for kwargs in ({"counter_note":None},{"evidence_codes":["개9"]},{"label":"새로운 유형"},{"counter_codes":["개9"]}):
            with self.subTest(kwargs=kwargs),self.assertRaises(HTTPException) as caught:self.edit(result,**kwargs)
            self.assertEqual(caught.exception.status_code,422)
        with self.assertRaises(ValidationError):
            data=copy.deepcopy(result["document"]);data["decisions"][0]["rater_id"]=" ";BasicResultV4.model_validate_json(encode(data))

    def test_exact_sheet_pin_and_submitted_state_required(self):
        other=self.helper.assign("other")
        wrong=model(results.CalculateV4,input={"sheet_id":other["sheet_id"],"revision":other["revision"],"ref":other["manifest_ref"],"hash":other["manifest_hash"]})
        with self.assertRaises(HTTPException) as caught:results.create(self.store,self.sheet["sheet_id"],wrong,self.user)
        self.assertEqual(caught.exception.status_code,409)
        with self.assertRaises(HTTPException) as caught:results.create(self.store,other["sheet_id"],wrong,self.helper.people["other"])
        self.assertEqual(caught.exception.status_code,409)
        with self.assertRaises(HTTPException) as caught:self.create(same_object=True)
        self.assertEqual(caught.exception.status_code,422)

    def test_owner_and_account_permissions_freshly_checked(self):
        result=self.create()
        with self.assertRaises(HTTPException) as caught:results.view(self.store,result["summary"]["result_id"],self.helper.people["other"])
        self.assertEqual(caught.exception.status_code,403)
        with self.store.connect(write=True) as db:db.execute("UPDATE users SET active=0 WHERE username=?",(self.user.username,))
        with self.assertRaises(HTTPException) as caught:results.view(self.store,result["summary"]["result_id"],self.user)
        self.assertEqual(caught.exception.status_code,403)

    def test_adoption_rechecks_account_and_deletion_after_file_write(self):
        original=results.write_result
        def deactivate(store,data):
            value=original(store,data)
            with store.connect(write=True) as db:db.execute("UPDATE users SET active=0 WHERE username=?",(self.user.username,))
            return value
        with patch.object(results,"write_result",side_effect=deactivate),self.assertRaises(HTTPException) as caught:self.create()
        self.assertEqual(caught.exception.status_code,403)
        with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM basic_results").fetchone()[0],0)

    def test_adoption_detects_media_mutation_and_never_adopts_result(self):
        original=results.write_result
        def tamper(store,data):
            value=original(store,data)
            store.path("videos/v1.mp4").write_bytes(b"tampered")
            return value
        with patch.object(results,"write_result",side_effect=tamper),self.assertRaises(HTTPException) as caught:self.create()
        self.assertEqual(caught.exception.status_code,409)
        with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM basic_results").fetchone()[0],0)

    def test_input_and_result_hash_damage_reject_reads(self):
        result=self.create()
        path=self.store.path(result["summary"]["manifest_ref"])
        original=path.read_bytes();path.write_bytes(original+b" ")
        with self.assertRaises(HTTPException) as caught:results.view(self.store,result["summary"]["result_id"],self.user)
        self.assertEqual(caught.exception.status_code,409)
        path.write_bytes(original)
        source=self.store.path(self.request.input.ref);source.write_bytes(source.read_bytes()+b" ")
        with self.assertRaises(HTTPException) as caught:results.view(self.store,result["summary"]["result_id"],self.user)
        self.assertEqual(caught.exception.status_code,409)

    def test_deleted_case_blocks_existing_result_and_revision(self):
        result=self.create()
        with self.store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.helper.case_id,))
        for operation in (lambda:results.view(self.store,result["summary"]["result_id"],self.user),lambda:self.edit(result)):
            with self.assertRaises(HTTPException):operation()

    def test_revision_conflict_preserves_first_successful_edit(self):
        first=self.create();second=self.edit(first)
        with self.assertRaises(HTTPException) as caught:self.edit(first,"held")
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(results.view(self.store,second["summary"]["result_id"],self.user)["summary"],second["summary"])

    def test_audio_probe_absent_and_partial_ranges_cannot_claim_full_audio(self):
        doc=results.pinned_sheet(self.store,{**self.sheet},self.request.input)
        data=doc.model_dump(mode="json")
        observation=self.helper.observe("개11",1,"alone_whole",52,112,True)
        observation["vocalization"]={"listened_seconds":60,"cumulative_vocal_seconds":20,"whole_interval_judged":True,"note":"synthetic audio"}
        data["sheet"]["observations"]=[observation]
        doc=sheets.SheetDocumentV4.model_validate_json(encode(data))
        for ranges,status,expected in [([],"absent",False),([{"start_sec":52,"end_sec":80}],"present",False),([{"start_sec":52,"end_sec":112}],"present",True)]:
            with patch.object(results,"probe",return_value={"duration_sec":300,"audio_status":status,"audio_ranges":ranges}):
                audio,facts=results.audio_amounts(self.store,doc)
                self.assertEqual(audio["개11"],expected)
                self.assertEqual(facts["v1"]["video_sha256"],self.helper.video_hash)

    def test_backup_restore_keeps_pinned_result_revisions_and_deletion_purges_files(self):
        from app import maintenance
        from app.storage import Store
        first=self.create()
        latest=self.edit(first)
        root=Path(self.helper.temp.name)
        maintenance.backup(self.store,root/"backup","operator")
        maintenance.restore(self.store,root/"backup",root/"restored")
        restored=Store(root/"restored")
        shown=results.view(restored,latest["summary"]["result_id"],self.user)
        self.assertEqual(shown["document"],latest["document"])
        old=results.view(restored,latest["summary"]["result_id"],self.user,1)
        self.assertEqual(old["document"],first["document"])
        with restored.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.helper.case_id,))
        maintenance.clean(restored,purge_deleted=True)
        for result in (first,latest):
            self.assertFalse(restored.path(result["summary"]["manifest_ref"]).exists())
        with self.assertRaises(HTTPException):results.view(restored,latest["summary"]["result_id"],self.user)
