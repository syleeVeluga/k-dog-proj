"""Synthetic reference XLSX preservation; no customer files or app-score restoration."""
import hashlib
from io import BytesIO
import re
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import HTTPException
from openpyxl import Workbook

from app import validation_data_v4 as validation, s1_workbook, maintenance
from app.storage import Store, encode
from tests.test_opinions_v4 import setup_case, model


def workbook_bytes():
    workbook = Workbook(); sheet = workbook.active; sheet.title = "Synthetic"
    sheet["A1"], sheet["A2"], sheet["A3"] = 0, -2, 99
    sheet["B1"] = "=SUM(A1:A2)"
    sheet["C1"] = "예시: synthetic sample"
    data = BytesIO(); workbook.save(data); workbook.close()
    output = BytesIO()
    with ZipFile(BytesIO(data.getvalue())) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                raw = re.sub(rb'(<c r="B1"[^>]*><f>.*?</f>)(?:<v\s*/>|<v>.*?</v>)', rb'\g<1><v>-2</v>', raw)
            target.writestr(name, raw)
    return output.getvalue()


class ValidationDataV4Tests(unittest.TestCase):
    def setUp(self):
        setup_case(self)
        self.data = workbook_bytes()
        with self.store.connect() as db:
            revision = self.store.case(db, self.case_id)["input_revision"]
        self.request = model(validation.ValidationImportV4, request_id="synthetic-reference", filename="synthetic.xlsx",
            expected_sha256=hashlib.sha256(self.data).hexdigest(), reason="synthetic explicit correspondence",
            bindings=[{"source_subject":"source-alias", "case_id":self.case_id, "session_id":self.session_id,
                "expected_revision":revision, "match_basis":"explicit_alias", "reason":"stable synthetic ID checked", "participation":"withdrawn"}],
            selections=[{"source_subject":"source-alias", "sheet":"Synthetic", "cell":cell, "code":code,
                "source_edition":"unknown", "reason":"synthetic reference only"} for cell, code in
                (("A1","개5"), ("A2","개13"), ("A3","개32"), ("B1","개30"), ("C1","개59"), ("D1","개10"))])

    def test_raw_zero_negative_null_formula_and_cache_are_distinct_reference_only(self):
        result = validation.preview(self.store, self.data, self.request, self.user)
        rows = {row["source"]["cell"]: row for row in result["rows"]}
        self.assertEqual(rows["A1"]["source"]["value"], 0)
        self.assertEqual(rows["A2"]["source"]["value"], -2)
        self.assertIsNone(rows["D1"]["source"]["value"])
        self.assertEqual(rows["B1"]["source"]["formula"], "=SUM(A1:A2)")
        self.assertEqual(rows["B1"]["source"]["cached_value"], -2)
        self.assertIsNone(rows["B1"]["source"]["value"])
        self.assertEqual(rows["A3"]["effective_status"], "legacy_semantics")
        self.assertEqual(rows["C1"]["effective_status"], "example")
        self.assertTrue(all(not row["independent_ground_truth"] and not row["current_s1_score"] for row in rows.values()))
        self.assertTrue(all("participant_withdrawn" in row["exclusion_reasons"] for row in rows.values()))
        self.assertFalse(result["profile"]["cache_is_recalculation"])

    def test_registration_idempotency_never_changes_current_scores_or_source_bytes(self):
        before = self.store.path(self.basic_ref["ref"]).read_bytes()
        first = validation.register(self.store, self.data, self.request, self.user)
        second = validation.register(self.store, self.data, self.request, self.user)
        self.assertEqual(first["reference"], second["reference"])
        self.assertEqual(self.store.path(first["document"]["source"]["ref"]).read_bytes(), self.data)
        self.assertEqual(self.store.path(self.basic_ref["ref"]).read_bytes(), before)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM score_sheets").fetchone()[0], 1)
        self.assertEqual(len(validation.list_records(self.store, self.user)), 1)

    def test_unmatched_and_unidentified_evaluator_are_never_guessed_from_names(self):
        request = self.request.model_copy(update={"bindings": []})
        result = validation.preview(self.store, self.data, request, self.user)
        self.assertTrue(all("unmatched_subject" in row["exclusion_reasons"] and "evaluator_unknown" in row["exclusion_reasons"] for row in result["rows"]))

    def test_hash_wrong_subject_session_or_private_actor_access_rejected(self):
        with self.assertRaises(HTTPException):
            validation.register(self.store, self.data+b"changed", self.request, self.user)
        result = validation.register(self.store, self.data, self.request, self.user)
        with self.assertRaises(HTTPException):
            validation.view(self.store, result["reference"]["validation_id"], self.helper.people["admin"])
        request = self.request.model_copy(update={"request_id":"different", "bindings":[self.request.bindings[0].model_copy(update={"session_id":"other"})]})
        with self.assertRaises(HTTPException):
            validation.preview(self.store, self.data, request, self.user)

    def test_new_blob_tamper_prevents_reference_adoption(self):
        write = validation._write_bytes
        def corrupt(store, ref, data):
            result = write(store, ref, data)
            if ref.endswith("reference.json"):
                store.path(ref).write_bytes(b"{}")
            return result
        with patch.object(validation, "_write_bytes", side_effect=corrupt), self.assertRaises(HTTPException):
            validation.register(self.store, self.data, self.request, self.user)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action=?", (validation.ACTION,)).fetchone()[0], 0)

    def test_macro_external_link_and_entity_packages_are_rejected(self):
        for name, data in (("xl/vbaProject.bin", b"synthetic"), ("xl/externalLinks/externalLink1.xml", b"<x/>")):
            stream = BytesIO(self.data)
            with ZipFile(stream, "a") as archive:
                archive.writestr(name, data)
            with self.assertRaises(ValueError):
                s1_workbook.reference_cells(stream.getvalue())
        target = BytesIO()
        with ZipFile(BytesIO(self.data)) as source,ZipFile(target,"w",ZIP_DEFLATED) as output:
            for name in source.namelist():
                raw = source.read(name)
                if name == "xl/worksheets/sheet1.xml":raw = b'<!DOCTYPE sheet [<!ENTITY synthetic "x">]>'+raw
                output.writestr(name,raw)
        with self.assertRaises(ValueError):s1_workbook.reference_cells(target.getvalue())

    def test_late_deletion_rejects_registration_and_preserved_reference_cleanup(self):
        write = validation._write_bytes
        def deleted(store,ref,data):
            result = write(store,ref,data)
            if ref.endswith("reference.json"):
                with store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.case_id,))
            return result
        with patch.object(validation,"_write_bytes",side_effect=deleted),self.assertRaises(HTTPException):
            validation.register(self.store,self.data,self.request,self.user)
        with self.store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=0 WHERE case_id=?",(self.case_id,))
        value = validation.register(self.store,self.data,self.request,self.user)
        root = Path(self.helper.temp.name)
        maintenance.backup(self.store,root/"reference-backup","operator")
        maintenance.restore(self.store,root/"reference-backup",root/"reference-restored")
        restored = Store(root/"reference-restored")
        self.assertEqual(validation.view(restored,value["reference"]["validation_id"],self.user)["document"],value["document"])
        with restored.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.case_id,))
        maintenance.clean(restored,purge_deleted=True)
        self.assertFalse(restored.path(value["document"]["source"]["ref"]).exists())

    def test_same_source_unbound_copy_and_old_backup_cannot_restore_deleted_cells(self):
        unbound_request = self.request.model_copy(update={"request_id":"unbound-copy","bindings":[]})
        unbound = validation.register(self.store,self.data,unbound_request,self.user)
        root = Path(self.helper.temp.name)
        maintenance.backup(self.store,root/"before-source-delete","operator")
        bound = validation.register(self.store,self.data,self.request,self.user)
        with self.store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.case_id,))
        with self.assertRaises(HTTPException):validation.view(self.store,unbound["reference"]["validation_id"],self.user)
        with self.assertRaises(HTTPException):validation.preview(self.store,self.data,unbound_request,self.user)
        maintenance.clean(self.store,purge_deleted=True)
        for value in (bound,unbound):self.assertFalse(self.store.path(value["document"]["source"]["ref"]).exists())
        with self.assertRaises(HTTPException):validation.register(self.store,self.data,unbound_request.model_copy(update={"request_id":"after-delete"}),self.user)
        maintenance.restore(self.store,root/"before-source-delete",root/"after-source-restore")
        restored = Store(root/"after-source-restore")
        self.assertFalse(restored.path(unbound["document"]["source"]["ref"]).exists())
        with self.assertRaises(HTTPException):validation.preview(restored,self.data,unbound_request,self.user)
        with restored.connect() as db:
            tombstones = list(db.execute("SELECT detail_json FROM changes WHERE action=?",(validation.DELETED_SOURCE,)))
            self.assertEqual(len(tombstones),1)
            self.assertEqual(tombstones[0][0],encode({"source_sha256":self.request.expected_sha256}))

    def test_duplicate_cell_or_sheet_name_is_rejected_without_last_value_wins(self):
        for duplicate in ("cell","sheet"):
            stream = BytesIO()
            with ZipFile(BytesIO(self.data)) as source,ZipFile(stream,"w",ZIP_DEFLATED) as output:
                for name in source.namelist():
                    raw = source.read(name)
                    if duplicate == "cell" and name == "xl/worksheets/sheet1.xml":
                        raw = raw.replace(b'</row>',b'<c r="A1" t="n"><v>99</v></c></row>',1)
                    if duplicate == "sheet" and name == "xl/workbook.xml":
                        entry = re.search(rb'<sheet\b[^>]*/>',raw).group(0)
                        raw = raw.replace(b'</sheets>',entry+b'</sheets>')
                    output.writestr(name,raw)
            with self.subTest(duplicate=duplicate),self.assertRaises(ValueError):s1_workbook.reference_cells(stream.getvalue())

    def test_reference_candidates_include_declined_consent_but_never_deleted_cases(self):
        with self.store.connect(write=True) as db:
            case = self.store.case(db,self.case_id); manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db,case,manifest,self.user.username,"synthetic.consent.declined")
            revision = self.store.case(db,self.case_id)["input_revision"]
        candidates = validation.candidates(self.store,self.user)
        self.assertEqual([item.case_id for item in candidates],[self.case_id])
        self.assertIn(self.session_id,[session.session_id for session in candidates[0].sessions])
        request = self.request.model_copy(update={"bindings":[self.request.bindings[0].model_copy(update={"expected_revision":revision})]})
        result = validation.register(self.store,self.data,request,self.user)
        self.assertTrue(all("participant_withdrawn" in row["exclusion_reasons"] and not row["independent_ground_truth"] for row in result["document"]["rows"]))
        with self.store.connect(write=True) as db:db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?",(self.case_id,))
        self.assertEqual(validation.candidates(self.store,self.user),[])
        with self.assertRaises(HTTPException):validation.preview(self.store,self.data,request,self.user)
