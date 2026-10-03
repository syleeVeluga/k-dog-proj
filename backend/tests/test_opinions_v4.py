"""S1 event-opinion fixtures use synthetic raw observations only."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import judgements_v4 as basics, opinions_v4 as opinions, sheets_v4 as sheets
from app.domain.catalog_v4 import OPTIONAL_CODES, load_catalog_v4
from app.storage import encode
from tests import test_sheets_v4 as support


def model(cls, **values):
    return cls.model_validate_json(encode(values))


def setup_case(test):
    test.helper = support.SheetsV4Tests()
    test.helper.setUp()
    test.addCleanup(test.helper.doCleanups)
    test.store = test.helper.store
    test.user = test.helper.people["operator"]
    test.case_id, test.session_id = test.helper.case_id, test.helper.session_id
    test.sheet = test.helper.assign("operator")
    raw = [{"code": item.code, "value": None, "status": "unobserved", "reason": "synthetic missing"}
           for item in load_catalog_v4().rated_items() if item.code not in OPTIONAL_CODES]
    raw = [test.helper.observe("보23", 2, "stranger_whole", 215, 245, True) if item["code"] == "보23" else item for item in raw]
    test.sheet = test.helper.save(test.sheet, raw, "operator")
    test.sheet = sheets.revise(test.store, test.sheet["sheet_id"], model(sheets.SheetReasonV4, expected_revision=test.sheet["revision"], reason="synthetic submit"), test.user, "submit")
    source = {"sheet_id": test.sheet["sheet_id"], "revision": test.sheet["revision"], "ref": test.sheet["manifest_ref"], "hash": test.sheet["manifest_hash"]}
    test.basic = basics.create(test.store, test.sheet["sheet_id"], model(basics.CalculateV4, input=source), test.user)
    test.basic_ref = result_reference(test.basic)


def result_reference(value):
    summary = value["summary"]
    return {"result_id": summary["result_id"], "revision": summary["revision"], "ref": summary["manifest_ref"], "hash": summary["manifest_hash"]}


def save_opinion(test, **kwargs):
    request = {"expected_revision": 0, "basic": test.basic_ref, "evaluator": "Synthetic evaluator", "completion_requested": True,
               "domains": [{"domain": "education_attitude", "text": "실제로 지시를 반복한 장면을 관찰했습니다."}], "reason": "synthetic opinion"}
    request.update(kwargs)
    return opinions.save(test.store, test.case_id, test.session_id, model(opinions.OpinionWriteV4, **request), test.user)


class OpinionV4Tests(unittest.TestCase):
    setUp = setup_case

    def test_one_domain_suffices_and_help_is_auxiliary(self):
        value = save_opinion(self, priority_help="기다림 연습")
        self.assertEqual(value["document"]["state"], "complete")
        self.assertEqual(len(value["document"]["domains"]), 1)
        self.assertEqual(value["document"]["entry_completion_policy"], "pending_G01")

    def test_requested_only_help_only_type_only_and_no_evaluator_never_complete(self):
        for changes in ({"domains": []}, {"domains": [], "priority_help": "도움만"}, {"evaluator": "  "},
                        {"domains": [{"domain": "education_attitude", "label": "통제형", "reason": "선택 근거", "evidence_codes": ["보23"], "counter_note": "반대 근거 검토"}]}):
            with self.subTest(changes=changes):
                current = opinions.view(self.store, self.case_id, self.session_id, self.user)
                revision = current["reference"]["revision"] if current["reference"] else 0
                value = save_opinion(self, expected_revision=revision, **changes)
                self.assertEqual(value["document"]["state"], "draft")
                self.assertTrue(value["document"]["completion_issues"])

    def test_draft_complete_reopen_withdraw_history_and_lock(self):
        draft = save_opinion(self, completion_requested=False)
        completed = save_opinion(self, expected_revision=draft["reference"]["revision"])
        with self.assertRaises(HTTPException):
            save_opinion(self, expected_revision=completed["reference"]["revision"])
        withdrawn = opinions.action(self.store, self.case_id, self.session_id,
            model(opinions.OpinionActionV4, expected_revision=completed["reference"]["revision"], reason="synthetic withdrawal"), self.user, "withdraw")
        self.assertEqual(withdrawn["document"]["state"], "withdrawn")
        self.assertEqual(opinions.read_document(self.store, completed["reference"]["ref"], completed["reference"]["hash"]).state, "complete")
        reopened = opinions.action(self.store, self.case_id, self.session_id,
            model(opinions.OpinionActionV4, expected_revision=withdrawn["reference"]["revision"], reason="synthetic reopen"), self.user, "reopen")
        self.assertEqual(reopened["document"]["state"], "draft")
        self.assertFalse(reopened["document"]["completion_requested"])
        self.assertEqual(len(reopened["document"]["previous"]), 3)

    def test_unknown_type_and_duplicate_domains_reject(self):
        for domains in ([{"domain":"attachment", "label":"찾고, 차분히 재회", "text":"요약"}],
                        [{"domain":"tendency", "text":"하나"},{"domain":"tendency", "text":"둘"}]):
            with self.assertRaises(ValueError):
                save_opinion(self, domains=domains)

    def test_optimistic_revision_account_deletion_and_corrupt_parents_reject(self):
        value = save_opinion(self, completion_requested=False)
        with self.assertRaises(HTTPException):
            save_opinion(self)
        self.store.path(self.basic_ref["ref"]).write_text("{}")
        with self.assertRaises(HTTPException):
            opinions.view(self.store, self.case_id, self.session_id, self.user)

    def test_privilege_change_between_write_and_adoption_rejects(self):
        write = opinions.write_document
        def revoke(store, data):
            result = write(store, data)
            with store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
            return result
        with patch.object(opinions, "write_document", side_effect=revoke), self.assertRaises(HTTPException):
            save_opinion(self)
        with self.store.connect() as db:
            self.assertIsNone(opinions.latest(self.store, db, self.case_id, self.session_id))

    def test_other_rater_and_admin_cannot_read_by_manager_role(self):
        save_opinion(self)
        for who in ("reviewer", "admin", "developer"):
            with self.assertRaises(HTTPException):
                opinions.view(self.store, self.case_id, self.session_id, self.helper.people[who])

    def test_explicit_scene_refs_require_selected_exact_original_evidence(self):
        import copy
        basis = next(item for item in self.basic["document"]["input_document"]["sheet"]["observations"] if item["code"] == "보23")["evidence"][0]
        domain = {"domain":"education_attitude", "text":"실제 반복 지시 장면", "evidence_codes":["보23"], "scene_refs":[basis]}
        value = save_opinion(self, completion_requested=False, domains=[domain])
        self.assertEqual(value["document"]["domains"][0]["scene_refs"], [basis])
        for field, changed in (("video_id","other-video"), ("video_sha256","0"*64), ("camera_id","CAM9"), ("start_seconds",216.0)):
            altered = copy.deepcopy(domain)
            altered["scene_refs"][0][field] = changed
            with self.assertRaises((HTTPException, ValueError)):
                save_opinion(self, expected_revision=1, domains=[altered])
        domain["evidence_codes"] = []
        with self.assertRaises(HTTPException):
            save_opinion(self, expected_revision=1, domains=[domain])

    def test_new_opinion_blob_tamper_before_adoption_never_becomes_current(self):
        write = opinions.write_document
        def tamper(store, data):
            link = write(store, data)
            store.path(link.ref).write_text("{}")
            return link
        with patch.object(opinions, "write_document", side_effect=tamper), self.assertRaises(HTTPException):
            save_opinion(self)
        with self.store.connect() as db:
            self.assertIsNone(opinions.latest(self.store, db, self.case_id, self.session_id))

    def test_new_state_blob_tamper_preserves_last_valid_opinion(self):
        initial = save_opinion(self)
        write = opinions.write_document
        def tamper(store, data):
            link = write(store, data)
            store.path(link.ref).write_text("{}")
            return link
        with patch.object(opinions, "write_document", side_effect=tamper), self.assertRaises(HTTPException):
            opinions.action(self.store, self.case_id, self.session_id,
                model(opinions.OpinionActionV4, expected_revision=1, reason="withdraw synthetic"), self.user, "withdraw")
        self.assertEqual(opinions.view(self.store, self.case_id, self.session_id, self.user)["reference"], initial["reference"])
