"""Synthetic conditional approvals in research files; never real research approval."""
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook

from app import comparisons_v4 as comparisons, external_comparisons_v4 as external, exports_v4 as exports, maintenance
from app.domain.comparisons_v4 import CohortSelectionV4
from app.domain.exports_v4 import ExportSnapshotV4
from app.domain.sheets_v4 import InputPointerV4
from app.storage import Store, encode
from tests import test_external_comparisons_v4 as external_fixture
from tests.test_opinions_v4 import model


class ExternalExportTests(unittest.TestCase):
    def setUp(self):
        self.helper = external_fixture.ExternalReportTests(); self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture
        self.store, self.user = self.helper.store, self.helper.user
        self.reference = self.helper.external.reference
        self.request = model(exports.ExportCreateV4, request_id="external-export", format="csv_zip", reason="SYNTHETIC ONLY",
            members=[{"case_id":self.fixture.case_id,"session_id":self.fixture.session_id,
                "sheet":self.fixture.basic["document"]["input"],"basic":self.fixture.basic_ref,"final":self.fixture.final["reference"]}],
            external_comparisons=[self.reference.model_dump(mode="json")])

    def load(self, export_id):
        with self.store.connect() as db:
            return exports._load(self.store,exports._record(db,export_id))

    def withdraw(self):
        comparisons.activate_external(self.store, comparisons.ActivateExternalV4(source_id=external_fixture.SOURCE, expected_revision=1,
            confirmation=self.helper.research, enabled=False, reason="SYNTHETIC WITHDRAWAL"), SimpleNamespace(username="admin"))

    def test_csv_and_xlsx_pin_approved_scope_numbers_and_pseudonymous_target(self):
        created = exports.create(self.store,self.request,self.user)
        self.assertEqual(exports.create(self.store,self.request,self.user),created)
        snapshot = self.load(created["export_id"])
        self.assertEqual(snapshot.external_comparisons[0].reference,self.reference)
        parents = {file.ref:file.hash for file in snapshot.parent_files}
        for file in external.files(self.store,self.reference):self.assertEqual(parents[file.ref],file.hash)
        data,_,_=exports.download(self.store,created["export_id"],self.user)
        with ZipFile(BytesIO(data)) as archive:
            rows=list(csv.DictReader(StringIO(archive.read("comparisons.csv").decode("utf-8-sig"))))
        row=rows[0]
        self.assertEqual((row["source"],row["participant"],row["session"]),("external_reference","P001","S001"))
        self.assertEqual((float(row["local_mean"]),float(row["mean"]),float(row["standard_deviation"])),(0,.66,.91))
        self.assertEqual((row["valid_n"],row["total_n"],row["research_revision"],row["activation_revision"]),("42926","43517","1","1"))
        self.assertEqual((row["local_n_label"],row["external_valid_n_label"]),("유효 응답 문항","외부 유효 표본"))
        self.assertEqual(row["research_sha256"],self.helper.research.hash)
        self.assertNotIn(self.fixture.case_id,encode(row));self.assertNotIn(self.reference.ref,encode(row))
        xlsx=exports.create(self.store,self.request.model_copy(update={"request_id":"external-xlsx","format":"xlsx"}),self.user)
        data,_,_=exports.download(self.store,xlsx["export_id"],self.user)
        book=load_workbook(BytesIO(data));values=list(book["comparisons"].values);book.close()
        actual=dict(zip(values[0],values[1],strict=True))
        self.assertEqual((actual["local_mean"],actual["mean"],actual["valid_n"]),(0,.66,42926))

    def test_different_input_and_duplicate_external_pins_cannot_join_old_raw_sheet(self):
        with self.store.connect(write=True) as db:
            case=self.store.case(db,self.fixture.case_id);manifest=self.store.manifest(case)
            manifest.sessions[0].survey["s10"]=4
            self.store.save(db,case,manifest,"operator","synthetic.changed")
            current=self.store.case(db,self.fixture.case_id)
            target=CohortSelectionV4(case_id=current["case_id"],session_id=current["selected_session_id"],expected_revision=current["input_revision"],
                input=InputPointerV4(manifest_ref=current["manifest_ref"],manifest_hash=current["manifest_hash"]))
        other=external.create(self.store,external.ExternalCreateV4(request_id="different-input",target=target,source_ids=[external_fixture.SOURCE],reason="SYNTHETIC ONLY"),self.user)
        with self.assertRaises(HTTPException) as caught:
            exports.create(self.store,self.request.model_copy(update={"external_comparisons":[other.reference]}),self.user)
        self.assertEqual(caught.exception.status_code,409)
        with self.assertRaises(HTTPException) as caught:
            exports.create(self.store,self.request.model_copy(update={"external_comparisons":[self.reference,self.reference]}),self.user)
        self.assertEqual(caught.exception.status_code,422)

    def test_withdrawal_blocks_existing_download_and_late_export_adoption(self):
        created=exports.create(self.store,self.request,self.user)
        before=self.store.path(self.load(created["export_id"]).output.ref).read_bytes()
        real=exports.render
        def withdraw_during_render(snapshot):
            data=real(snapshot);self.withdraw();return data
        with patch.object(exports,"render",side_effect=withdraw_during_render),self.assertRaises(HTTPException):
            exports.create(self.store,self.request.model_copy(update={"request_id":"late"}),self.user)
        with self.assertRaises(HTTPException):exports.download(self.store,created["export_id"],self.user)
        self.assertEqual(self.store.path(self.load(created["export_id"]).output.ref).read_bytes(),before)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action=?",(exports.ACTION,)).fetchone()[0],1)

    def test_typed_backup_and_delete_restore_close_external_dependents(self):
        created=exports.create(self.store,self.request,self.user)
        snapshot=self.load(created["export_id"])
        public=snapshot.external_comparisons[0].model_dump(mode="json")
        public["entries"][0]["population"]={"ref":"not-a-file","raw_json":"not-json"}
        with self.store.connect(write=True) as db:
            self.store.audit(db,"operator",self.fixture.case_id,"synthetic.inline",{"external_comparison":public})
        destination=Path(self.fixture.helper.temp.name)/"external-backup"
        maintenance.backup(self.store,destination,"operator")
        restored=maintenance.restore(self.store,destination,Path(self.fixture.helper.temp.name)/"before-delete")
        restored_store=Store(Path(restored["path"]))
        self.assertEqual(exports.download(restored_store,created["export_id"],self.user)[0],self.store.path(snapshot.output.ref).read_bytes())
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.fixture.case_id,))
        maintenance.clean(self.store,purge_deleted=True)
        self.assertFalse(self.store.path(self.reference.ref).exists());self.assertFalse(self.store.path(snapshot.output.ref).exists())
        restored=maintenance.restore(self.store,destination,Path(self.fixture.helper.temp.name)/"after-delete")
        restored_store=Store(Path(restored["path"]))
        self.assertFalse(restored_store.path(self.reference.ref).exists());self.assertFalse(restored_store.path(snapshot.output.ref).exists())

    def test_empty_optional_fields_preserve_pre_extension_request_and_snapshot_bytes(self):
        request=self.request.model_copy(update={"external_comparisons":[]})
        self.assertNotIn("external_comparisons",request.model_dump())
        self.assertEqual(exports.ExportCreateV4.model_validate_json(request.model_dump_json()).model_dump_json(),request.model_dump_json())
        created=exports.create(self.store,request,self.user)
        snapshot=self.load(created["export_id"])
        self.assertNotIn("external_comparisons",snapshot.model_dump())
        self.assertEqual(ExportSnapshotV4.model_validate_json(snapshot.model_dump_json()).model_dump_json(),snapshot.model_dump_json())
