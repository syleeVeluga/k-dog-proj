"""Conditional comparison fixtures only; these are not real research approvals."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import comparisons_v4 as comparisons, external_comparisons_v4 as external, report_runs_v4 as reports
from app.domain.comparisons_v4 import CohortSelectionV4, ResearchReviewV4
from app.domain.sheets_v4 import InputPointerV4
from app.storage import encode
from tests import test_comparisons_v4 as comparison_fixture
from tests import test_report_runs_v4 as report_fixture
from tests import test_sheets_v4 as sheet_fixture


SOURCE = "us2026-stranger-fear"


def approve(store, *, revision=0, activation_revision=0, status="confirmed", population=None, source_id=SOURCE):
    admin = SimpleNamespace(username="admin")
    evidence = external.upload_evidence(store, b"SYNTHETIC TEST ONLY; NOT A RESEARCH APPROVAL", "synthetic.txt", admin)
    scope = comparisons.target_scope(source_id).model_copy(update={"population_requirements": population or {}})
    check = {"status": status, "note": "SYNTHETIC TEST ONLY", "evidence_location": "synthetic section"}
    review = ResearchReviewV4.model_validate_json(encode({"source_id": source_id,
        "source_asset_hash": comparisons._source(source_id)[1], "confirmed_by": "SYNTHETIC ONLY", "confirmed_at": "2026-10-04",
        "evidence": [evidence.model_dump(mode="json")], "scope": scope.model_dump(mode="json"),
        "reason": "synthetic conditional mechanism", **{name: check for name in comparisons.CHECKS}}))
    pointer = comparisons.confirm_research(store, comparisons.ConfirmResearchV4(expected_revision=revision, document=review), admin)
    if status == "confirmed":
        comparisons.activate_external(store, comparisons.ActivateExternalV4(source_id=source_id, expected_revision=activation_revision,
            confirmation=pointer, enabled=True, reason="SYNTHETIC ONLY"), admin)
    return pointer, evidence


class ExternalSnapshotTests(comparison_fixture.ComparisonFixture):
    def setUp(self):
        super().setUp()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET consent_confirmed=1")

    def request(self, index=0, request_id="external"):
        return external.ExternalCreateV4(request_id=request_id, target=self.selection(self.ids[index]),
            source_ids=[SOURCE], reason="synthetic explicit comparison")

    def test_default_and_unconfirmed_source_never_creates_numeric_snapshot(self):
        with self.assertRaises(HTTPException): external.create(self.store, self.request(), self.user)
        approve(self.store, status="pending")
        with self.assertRaises(HTTPException): external.create(self.store, self.request(), self.user)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action=?", (external.ACTION,)).fetchone()[0], 0)

    def test_explicit_snapshot_preserves_zero_exact_scope_hashes_and_idempotency(self):
        approve(self.store)
        value = external.create(self.store, self.request(), self.user)
        self.assertEqual(external.create(self.store, self.request(), self.user).reference, value.reference)
        public = external.for_output(self.store, value.reference, self.user)
        self.assertEqual((public.entries[0].local_mean, public.entries[0].local_n), (0, 2))
        self.assertEqual((public.entries[0].gate.values.mean, public.entries[0].gate.values.valid_n), (.66, 42926))
        self.assertEqual(len(external.files(self.store, value.reference)), 4)
        with self.assertRaises(HTTPException): external.create(self.store, self.request(index=1), self.user)
        self.assertNotIn('0.66', encode(comparisons.public_sources(self.store, self.user)))
        self.assertEqual(comparisons.public_sources(self.store, self.user)["sources"][0]["status"], "conditionally_available")

    def test_unknown_population_missing_answers_and_different_edition_stay_blocked(self):
        approve(self.store, population={"unverified_research_profile": "required"})
        with self.assertRaises(HTTPException): external.create(self.store, self.request(), self.user)
        approve(self.store, revision=1, activation_revision=1)
        with self.assertRaises(HTTPException): external.create(self.store, self.request(index=2), self.user)
        def historical(manifest):
            manifest.sessions[0].survey_version = "catalog-20260913-v2"
            manifest.sessions[0].survey = {key: 2 if value is not None else None for key, value in manifest.sessions[0].survey.items()}
        self.edit(0, historical)
        with self.assertRaises(HTTPException): external.create(self.store, self.request(), self.user)

    def test_revocation_keeps_old_bytes_masks_detail_and_records_impact(self):
        pointer, _ = approve(self.store)
        value = external.create(self.store, self.request(), self.user)
        before = self.store.path(value.reference.ref).read_bytes()
        comparisons.activate_external(self.store, comparisons.ActivateExternalV4(source_id=SOURCE, expected_revision=1,
            confirmation=pointer, enabled=False, reason="SYNTHETIC WITHDRAWAL"), self.admin)
        with self.assertRaises(HTTPException): external.for_output(self.store, value.reference, self.user)
        shown = external.view(self.store, value.reference.snapshot_id, self.user)
        self.assertEqual(shown.status, "blocked"); self.assertIsNone(shown.document)
        self.assertEqual(len(shown.impact_history), 1)
        self.assertNotIn('0.66', shown.model_dump_json())
        self.assertEqual(self.store.path(value.reference.ref).read_bytes(), before)

    def test_new_confirmation_requires_new_exact_snapshot_and_tampered_evidence_blocks(self):
        approve(self.store)
        old = external.create(self.store, self.request(), self.user)
        _, evidence = approve(self.store, revision=1, activation_revision=1)
        with self.assertRaises(HTTPException): external.for_output(self.store, old.reference, self.user)
        fresh = external.create(self.store, self.request(request_id="new-version"), self.user)
        self.assertEqual(fresh.document.entries[0].gate.confirmation.revision, 2)
        self.store.path(evidence.ref).write_bytes(b"tampered")
        with self.assertRaises(HTTPException): external.for_output(self.store, fresh.reference, self.user)

    def test_withdrawal_during_final_document_read_masks_same_response(self):
        research,_=approve(self.store)
        shown=external.create(self.store,self.request(),self.user)
        original=external.document
        calls=0
        def withdraw_on_second_read(store,pointer):
            nonlocal calls
            result=original(store,pointer);calls+=1
            if calls==2:
                comparisons.activate_external(store,comparisons.ActivateExternalV4(source_id=SOURCE,expected_revision=1,
                    confirmation=research,enabled=False,reason="SYNTHETIC LATE WITHDRAWAL"),SimpleNamespace(username="admin"))
            return result
        with patch.object(external,"document",side_effect=withdraw_on_second_read):
            blocked=external.view(self.store,shown.reference.snapshot_id,self.user)
        self.assertEqual(blocked.status,"blocked")
        self.assertIsNone(blocked.document)
        self.assertNotIn("42926",blocked.model_dump_json())

    def test_evidence_role_late_change_and_unadopted_snapshot_cannot_bypass(self):
        with self.assertRaises(HTTPException): external.upload_evidence(self.store,b"data","test.txt",self.user)
        approve(self.store)
        original = comparisons._write
        def corrupt(store, kind, doc):
            pointer = original(store,kind,doc)
            store.path(pointer.ref).write_bytes(b"tampered")
            return pointer
        with patch.object(comparisons,"_write",side_effect=corrupt), self.assertRaises(HTTPException):
            external.create(self.store,self.request(),self.user)
        self.assertEqual(external.list_snapshots(self.store,self.user),[])


class ExternalReportTests(unittest.TestCase):
    def setUp(self):
        original = sheet_fixture.SheetsV4Tests.setUp
        def survey_before_scores(helper):
            original(helper)
            with helper.store.connect(write=True) as db:
                case = helper.store.case(db,helper.case_id)
                manifest = helper.store.manifest(case)
                manifest.consents.analysis_feedback = "confirmed"
                manifest.sessions[0].survey.update(s10=0,s11=0,s12=0,s13=0,s14=0)
                helper.store.save(db,case,manifest,"operator","synthetic.survey")
                db.execute("UPDATE cases SET consent_confirmed=1 WHERE case_id=?",(helper.case_id,))
        self.fixture = report_fixture.ReportRunV4Tests()
        with patch.object(sheet_fixture.SheetsV4Tests,"setUp",survey_before_scores):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store,self.user=self.fixture.store,self.fixture.user
        self.research,_=approve(self.store)
        source=self.fixture.basic["document"]["input_document"]["source"]
        target=CohortSelectionV4.model_validate_json(encode({"case_id":self.fixture.case_id,"session_id":self.fixture.session_id,
            "expected_revision":source["input_revision"],"input":source["input"]}))
        self.external=external.create(self.store,external.ExternalCreateV4(request_id="external",target=target,source_ids=[SOURCE],reason="synthetic"),self.user)
        self.fixture.request=self.fixture.request.model_copy(update={"external_comparison":self.external.reference})

    def test_actual_content_html_pdf_and_withdrawal_keep_issued_bytes_immutable(self):
        from app.report_render_v4 import external_notice, render_html
        from app.report_pdf_v4 import render_pdf
        other="us2026-nonsocial-fear"
        approve(self.store,source_id=other)
        self.external=external.create(self.store,external.ExternalCreateV4(request_id="both-sources",target=self.external.target,
            source_ids=[SOURCE,other],reason="SYNTHETIC TWO-SOURCE OUTPUT"),self.user)
        self.fixture.request=self.fixture.request.model_copy(update={"external_comparison":self.external.reference})
        self.fixture.render.side_effect=lambda profile,header,images: (render_html(profile,header,images),render_pdf(profile,header,images))
        run_id=self.fixture.publish()
        row=self.fixture.row(run_id)
        raw,_,_=reports.download(self.store,self.fixture.case_id,self.fixture.session_id,run_id,"manifest",self.user)
        doc=json.loads(raw)
        self.assertEqual(doc["profile"]["external_comparison"]["reference"]["hash"],self.external.reference.hash)
        html,_,_=reports.download(self.store,self.fixture.case_id,self.fixture.session_id,run_id,"html",self.user)
        for text in ("0.66","0.91","42926","43517","본인 설문 평균 0","유효 응답 문항 2개","외부 유효 표본"):
            self.assertIn(text,html.decode())
        self.assertEqual(html.decode().count(external_notice(reports.snapshot_for(row).profile)),1)
        pdf,_,_=reports.download(self.store,self.fixture.case_id,self.fixture.session_id,run_id,"pdf",self.user)
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b",pdf)),6)
        if shutil.which("pdftotext"):
            pdf_path=Path(self.fixture.helper.temp.name)/"approved.pdf";pdf_path.write_bytes(pdf)
            extracted=subprocess.check_output(["pdftotext","-enc","UTF-8",str(pdf_path),"-"]).decode("utf-8")
            for text in ("0.66","0.91","42926","43517"):self.assertIn(text,extracted)
        comparisons.activate_external(self.store,comparisons.ActivateExternalV4(source_id=SOURCE,expected_revision=1,
            confirmation=self.research,enabled=False,reason="SYNTHETIC WITHDRAWAL"),SimpleNamespace(username="admin"))
        for kind in ("html","pdf","manifest"):
            with self.assertRaises(HTTPException):reports.download(self.store,self.fixture.case_id,self.fixture.session_id,run_id,kind,self.user)
        metadata=reports.view(self.store,run_id,self.user)
        self.assertEqual(metadata["status"],"succeeded")
        self.assertEqual(metadata["external_comparison_status"],"blocked")
        self.assertFalse(metadata["result_available"])
        self.assertEqual(self.store.path(row["result_ref"]).read_bytes(),raw)
        with self.assertRaises(HTTPException):self.fixture.enqueue(self.fixture.request.model_copy(update={"request_id":"revoked"}))

    def test_different_input_snapshot_and_revocation_before_worker_reject(self):
        with self.store.connect(write=True) as db:
            case=self.store.case(db,self.fixture.case_id);manifest=self.store.manifest(case)
            manifest.sessions[0].survey.update(s10=4)
            self.store.save(db,case,manifest,"operator","synthetic.changed")
            current=self.store.case(db,self.fixture.case_id)
            target=CohortSelectionV4(case_id=current["case_id"],session_id=current["selected_session_id"],expected_revision=current["input_revision"],
                input=InputPointerV4(manifest_ref=current["manifest_ref"],manifest_hash=current["manifest_hash"]))
        other=external.create(self.store,external.ExternalCreateV4(request_id="different-input",target=target,source_ids=[SOURCE],reason="synthetic"),self.user)
        request=self.fixture.request.model_copy(update={"expected_revision":current["input_revision"],"external_comparison":other.reference})
        with self.assertRaises(HTTPException):self.fixture.enqueue(request)
        request=request.model_copy(update={"external_comparison":self.external.reference})
        run=self.fixture.enqueue(request)
        comparisons.activate_external(self.store,comparisons.ActivateExternalV4(source_id=SOURCE,expected_revision=1,
            confirmation=self.research,enabled=False,reason="SYNTHETIC WITHDRAWAL"),SimpleNamespace(username="admin"))
        from app.worker import Worker
        self.assertFalse(Worker(self.store).once())
        self.assertNotEqual(self.fixture.row(run["run_id"])["status"],"succeeded")
        self.assertIsNone(self.fixture.row(run["run_id"])["result_ref"])

    def test_unselected_external_does_not_change_prior_s1_serialization(self):
        request=self.fixture.request.model_copy(update={"external_comparison":None})
        self.assertNotIn("external_comparison",request.model_dump(mode="json"))
        run=self.fixture.enqueue(request)
        snapshot=reports.snapshot_for(self.fixture.row(run["run_id"]))
        self.assertNotIn("external_comparison",snapshot.profile.model_dump(mode="json"))
        self.assertNotIn("external_comparison",json.loads(self.fixture.row(run["run_id"])["config_snapshot_json"]))
        self.fixture.work()
        self.assertEqual(self.fixture.row(run["run_id"])["status"],"succeeded")


class ExternalApiTests(unittest.TestCase):
    def test_explicit_http_research_activation_target_snapshot_and_revocation(self):
        from tests import test_comparisons_api_v4 as api_fixture
        fixture=api_fixture.ComparisonApiV4Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        client=fixture.client
        with fixture.store.connect(write=True) as db:db.execute("UPDATE cases SET consent_confirmed=1")
        endpoint="/api/comparisons-s1"
        self.assertEqual(client.post(endpoint+"/evidence?filename=synthetic.txt",content=b"synthetic").status_code,403)
        fixture.login("admin")
        evidence=client.post(endpoint+"/evidence?filename=synthetic.txt",content=b"SYNTHETIC TEST ONLY")
        self.assertEqual(evidence.status_code,201,evidence.text)
        inventory=client.get(endpoint+"/research").json()
        source=next(row for row in inventory["sources"] if row["source_id"]==SOURCE)
        check={"status":"confirmed","note":"SYNTHETIC ONLY","evidence_location":"synthetic fixture"}
        document={"source_id":SOURCE,"source_asset_hash":inventory["asset_hash"],"confirmed_by":"SYNTHETIC ONLY",
            "confirmed_at":"2026-10-04","evidence":[evidence.json()],"scope":source["scope"],"reason":"synthetic mechanism",
            **{name:check for name in comparisons.CHECKS}}
        confirmation=client.post(endpoint+"/research",json={"expected_revision":0,"document":document})
        self.assertEqual(confirmation.status_code,200,confirmation.text)
        activation={"source_id":SOURCE,"expected_revision":0,"confirmation":confirmation.json(),"enabled":True,"reason":"synthetic"}
        response=client.post(endpoint+"/activation",json=activation)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(client.get(endpoint+"/research").json()["documents"][SOURCE]["confirmed_by"],"SYNTHETIC ONLY")
        fixture.login("operator")
        self.assertNotIn("reference_values",client.get(endpoint+"/sources").text)
        request={"request_id":"http-external","target":fixture.fixture.selection(fixture.fixture.ids[0]).model_dump(mode="json"),
            "source_ids":[SOURCE],"reason":"synthetic selected scope"}
        response=client.post(endpoint+"/external-snapshots",json=request)
        self.assertEqual(response.status_code,201,response.text)
        saved=response.json();identifier=saved["reference"]["snapshot_id"]
        self.assertEqual(saved["document"]["entries"][0]["local_mean"],0)
        self.assertNotIn("42926",client.get(endpoint+"/external-snapshots").text)
        self.assertEqual(client.get(endpoint+"/external-snapshots/"+identifier).json()["status"],"approved")
        fixture.login("admin")
        activation.update(expected_revision=1,enabled=False,reason="SYNTHETIC WITHDRAWAL")
        self.assertEqual(client.post(endpoint+"/activation",json=activation).status_code,200)
        fixture.login("operator")
        blocked=client.get(endpoint+"/external-snapshots/"+identifier)
        self.assertEqual(blocked.status_code,200,blocked.text)
        self.assertIsNone(blocked.json()["document"])
        self.assertEqual(blocked.json()["status"],"blocked")
        self.assertNotIn("42926",blocked.text)
