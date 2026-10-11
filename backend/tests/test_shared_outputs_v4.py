"""AR05 synthetic common access with actual HTTP, Worker and immutable outputs."""
import asyncio
import unittest

from app import comparisons_v4 as comparisons, exports_v4 as exports, uploads, validation_data_v4 as validation
from app.domain.comparisons_v4 import ResearchConfirmationV4, ResearchReferenceV4
from app.storage import encode, now, uid
from tests import test_report_api_v4, test_exports_v4, test_validation_data_v4, test_uploads_v4, test_comparisons_v4


class SharedOutputsV4Tests(unittest.TestCase):
    def test_each_account_actually_requests_worker_issues_and_opens_shared_report(self):
        fixture = test_report_api_v4.ReportApiV4Tests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.fixture.historical_config.stop()
        from app.worker import Worker
        from tests.test_report_narrative_v4 import generated
        calls = []
        class Provider:
            def request_v4(inner, files, config, context, schema, guard):
                guard(); self.assertEqual(files, []); calls.append(context)
                return generated(context), {}
        # A separate unfinished independent sheet is no longer an access gate.
        draft = fixture.fixture.helper.assign("other")
        with fixture.store.connect() as db:
            before = dict(db.execute("SELECT * FROM score_sheets WHERE sheet_id=?", (draft["sheet_id"],)).fetchone())
        for actor in ("operator", "reviewer", "admin", "developer"):
            with self.subTest(actor=actor):
                client = fixture.client
                self.assertEqual(client.post("/api/auth/login", json={"username":actor,"password":"Synthetic-Password-2026!"}).status_code,200)
                request = fixture.fixture.request.model_dump(mode="json")
                request["request_id"] = "AR05-" + actor
                response = client.post(fixture.path, json=request)
                self.assertEqual(response.status_code,201,response.text)
                run_id = response.json()["run_id"]
                self.assertTrue(Worker(fixture.store, observer=Provider()).once())
                self.assertEqual(fixture.fixture.row(run_id)["status"],"succeeded")
                file_path = fixture.path + f"/{run_id}/files/"
                raw = client.get(file_path + "manifest").content
                self.assertEqual(client.get(file_path + "manifest", params={"purpose":"open"}).status_code,200)
                for fmt in ("html", "pdf"):
                    self.assertEqual(client.get(file_path + fmt).status_code,200)
                log = client.get(fixture.path + f"/{run_id}/access").json()
                self.assertEqual([(row["actor"],row["action"]) for row in log],
                    [(actor,"report.s1.create"),(actor,"report.s1.issue"),(actor,"report.s1.open"),(actor,"report.s1.open"),(actor,"report.s1.open")])
                self.assertEqual(client.post("/api/auth/login",json={"username":"other","password":"Synthetic-Password-2026!"}).status_code,200)
                self.assertEqual(client.get(file_path + "manifest").content,raw)
                self.assertEqual(client.get(fixture.path + f"/{run_id}/access").json(),log)
        with fixture.store.connect() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM score_sheets WHERE sheet_id=?",(draft["sheet_id"],)).fetchone()),before)
        self.assertEqual(len(calls), 4)

    def test_shared_validation_export_and_new_output_keep_original_bytes_and_actors(self):
        fixture = test_exports_v4.ExportV4Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        created = fixture.create()
        raw = exports.download(fixture.store,created["export_id"],fixture.user)[0]
        snapshot = fixture.snapshot(created["export_id"])
        other = fixture.fixture.helper.people["reviewer"]
        with fixture.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username=?",(snapshot.actor,))
        self.assertEqual(exports.download(fixture.store,created["export_id"],other)[0],raw)
        self.assertEqual(exports.list_exports(fixture.store,other)[0]["export_id"],created["export_id"])
        request = fixture.request.model_copy(update={"request_id":"AR05-shared-new","format":"xlsx"})
        newer = exports.create(fixture.store,request,other)
        self.assertEqual(fixture.snapshot(newer["export_id"]).actor,"reviewer")
        self.assertEqual(exports.download(fixture.store,created["export_id"],other)[0],raw)
        reference = test_validation_data_v4.ValidationDataV4Tests();reference.setUp();self.addCleanup(reference.doCleanups)
        value = validation.register(reference.store,reference.data,reference.request,reference.user)
        reviewer = reference.helper.people["reviewer"]
        self.assertEqual(validation.list_records(reference.store,reviewer)[0]["reference"],value["reference"])
        self.assertEqual(validation.view(reference.store,value["reference"]["validation_id"],reviewer)["document"]["actor"],reference.user.username)
        copy = validation.register(reference.store,reference.data,reference.request.model_copy(update={"request_id":"AR05-new-reference"}),reviewer)
        self.assertEqual(copy["document"]["actor"],"reviewer")

    def test_receipt_request_namespaces_and_cross_account_receive_keep_real_claim_actor(self):
        fixture = test_uploads_v4.UploadsV4Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        first = fixture.create(data=b"first",request_id="same")
        second = uploads.create_receipt(fixture.store, uploads.UploadCreateV4(request_id="same",filename="other.mp4",expected_size=6),"other")
        self.assertNotEqual(first.upload_id,second.upload_id)
        receipt = asyncio.run(uploads.receive(fixture.store,first.upload_id,first.request_id,test_uploads_v4.chunks(b"first"),"review"))
        self.assertEqual(receipt.creator,"op")
        self.assertEqual(uploads.download_path(fixture.store,first.upload_id,"other").read_bytes(),b"first")
        self.assertEqual(uploads.get_receipt(fixture.store,second.upload_id,"op").state,second.state)
        with fixture.store.connect() as db:
            event = db.execute("SELECT actor FROM changes WHERE target=? AND action='upload.complete'",(first.upload_id,)).fetchone()
            self.assertEqual(event[0],"review")

    def test_legacy_checks_and_absent_activation_are_provenance_not_approval(self):
        fixture = test_comparisons_v4.ComparisonFixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        from tests.test_external_comparisons_v4 import SOURCE
        from app import external_comparisons_v4 as external
        evidence = external.upload_evidence(fixture.store,b"SYNTHETIC LEGACY SOURCE","legacy.txt",fixture.user)
        scope = comparisons.target_scope(SOURCE)
        check = {"status":"pending","note":"SYNTHETIC HISTORICAL METADATA","evidence_location":"fixture"}
        data = {"source_id":SOURCE,"source_asset_hash":comparisons._source(SOURCE)[1],"confirmed_by":"HISTORICAL SYNTHETIC",
            "confirmed_at":"2026-10-04","evidence":[evidence.model_dump(mode="json")],"scope":scope.model_dump(mode="json"),
            "reason":"preserved metadata","confirmation_id":uid(),"revision":1,"actor":"operator","recorded_at":now(),
            **{key:check for key in ("numerical_table","question_equivalence","scale_direction","missing_policy","translation_usage","population_scope")}}
        doc = ResearchConfirmationV4.model_validate_json(encode(data))
        file = comparisons._write(fixture.store,"research",doc)
        pointer = ResearchReferenceV4(confirmation_id=doc.confirmation_id,revision=1,ref=file.ref,hash=file.hash)
        original = fixture.store.path(file.ref).read_bytes()
        with fixture.store.connect(write=True) as db:
            fixture.store.audit(db,"operator",SOURCE,comparisons.RESEARCH_ACTION,pointer.model_dump(mode="json"))
        gate = comparisons.external_for_report(fixture.store,SOURCE,scope,fixture.user)
        self.assertEqual(gate.status,"ready")
        self.assertEqual(gate.definition,pointer)
        self.assertEqual(fixture.store.path(file.ref).read_bytes(),original)
        self.assertEqual(comparisons.research_document(fixture.store,pointer).numerical_table.status,"pending")

    def test_original_independent_pair_survives_third_party_open_and_later_edit_is_separate(self):
        fixture = test_exports_v4.ExportV4Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        request, _ = fixture.synthetic_ai_pair()
        initial = exports.create(fixture.store,request,fixture.user)
        original = fixture.snapshot(initial["export_id"])
        expected = exports.tables(original)["item_denominators"]
        pointers = {member.selection.sheet.ref:fixture.store.path(member.selection.sheet.ref).read_bytes() for member in original.members}
        helper = fixture.fixture.helper
        human = fixture.fixture.sheet
        helper.reveal(human,human,"other")
        viewer = helper.people["other"]
        copied = exports.create(fixture.store,request.model_copy(update={"request_id":"AR05-after-third-open"}),viewer)
        self.assertEqual(exports.tables(fixture.snapshot(copied["export_id"]))["item_denominators"],expected)
        revised = helper.save(human,helper.view(human,"other")["document"]["sheet"]["observations"],"other")
        from app import sheets_v4 as sheets
        from tests.test_opinions_v4 import model
        revised = sheets.revise(fixture.store,revised["sheet_id"],model(sheets.SheetReasonV4,expected_revision=revised["revision"],reason="SYNTHETIC LATER EDIT"),viewer,"submit")
        selection = model(exports.ExportSelectionV4,case_id=fixture.case_id,session_id=fixture.session_id,
            sheet={"sheet_id":revised["sheet_id"],"revision":revised["revision"],"ref":revised["manifest_ref"],"hash":revised["manifest_hash"]})
        later = exports.create(fixture.store,request.model_copy(update={"request_id":"AR05-later-edit","members":[selection,request.members[1]]}),viewer)
        pairs = exports.tables(fixture.snapshot(later["export_id"]))["independent_pairs"]
        self.assertFalse(any(row["included"] for row in pairs))
        self.assertTrue(all("not_independent" in row["excluded_reasons"] for row in pairs))
        self.assertEqual(exports.tables(fixture.snapshot(initial["export_id"]))["item_denominators"],expected)
        for ref,raw in pointers.items():self.assertEqual(fixture.store.path(ref).read_bytes(),raw)

    def test_pre_submission_ai_open_excludes_only_new_human_pair(self):
        fixture = test_exports_v4.ExportV4Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        request, _ = fixture.synthetic_ai_pair()
        helper = fixture.fixture.helper
        ai = request.members[1].sheet
        draft = helper.assign("reviewer", source=ai.sheet_id)
        target = {"sheet_id":ai.sheet_id,"revision":ai.revision,"manifest_ref":ai.ref,"manifest_hash":ai.hash}
        helper.reveal(draft,target,"reviewer")
        draft = helper.save(draft,helper.view(fixture.fixture.sheet,"reviewer")["document"]["sheet"]["observations"],"reviewer")
        from app import sheets_v4 as sheets
        from tests.test_opinions_v4 import model
        submitted = sheets.revise(fixture.store,draft["sheet_id"],model(sheets.SheetReasonV4,expected_revision=draft["revision"],reason="SYNTHETIC PRE-EXPOSED SUBMISSION"),helper.people["reviewer"],"submit")
        doc = helper.view(submitted,"reviewer")["document"]
        self.assertTrue(doc["sheet"]["ai_exposed"]);self.assertEqual(doc["purpose"],"review")
        selection = model(exports.ExportSelectionV4,case_id=fixture.case_id,session_id=fixture.session_id,
            sheet={"sheet_id":submitted["sheet_id"],"revision":submitted["revision"],"ref":submitted["manifest_ref"],"hash":submitted["manifest_hash"]})
        created = exports.create(fixture.store,request.model_copy(update={"request_id":"AR05-preexposed","members":[selection,request.members[1]]}),helper.people["reviewer"])
        pairs = exports.tables(fixture.snapshot(created["export_id"]))["independent_pairs"]
        self.assertFalse(any(row["included"] for row in pairs))
        self.assertTrue(all("not_independent" in row["excluded_reasons"] for row in pairs))
