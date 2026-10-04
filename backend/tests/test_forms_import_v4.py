"""Synthetic Forms exports only; no customer participant files are fixtures."""

import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from openpyxl import Workbook
from pydantic import ValidationError

from app.domain.catalog_v4 import SURVEY_VERSION
from app.forms_v4 import (FormsCommitRequestV4, FormsMappingV4, FormsPreviewRequestV4,
                          FormsTargetV4, commit, inspect_columns, preview, purge_case_imports)
from app.input_models_v4 import new_session_v4
from app.maintenance import backup, clean, references, restore
from app.storage import Store


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def xlsx_bytes(rows, sheet="응답"):
    book = Workbook()
    book.active.title = sheet
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


class FormsImportV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-forms-v4-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        with self.store.connect(write=True) as db:
            for name, role in (("operator", "operator"), ("reviewer", "reviewer")):
                db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)", (name, "unused", role))
        self.data = csv_bytes([["반려견", "문항1", "두려움"], ["합성견", "보통", "0"]])
        self.request = FormsPreviewRequestV4(request_id="preview-1", event_id="TEST", filename="synthetic.csv", format="csv",
            mapping=FormsMappingV4(version="mapping-1", source_profile="합성 표준 응답", survey_version=SURVEY_VERSION,
                                  columns={"dog_name": "반려견", "s01": "문항1", "s10": "두려움"}))

    def stage(self, data=None, request=None):
        return preview(self.store, self.data if data is None else data, request or self.request, "operator")

    def apply(self, result, request_id="commit-1", actor="operator"):
        return commit(self.store, FormsCommitRequestV4(request_id=request_id, preview_id=result.preview_id,
                                                      preview_hash=result.preview_hash), actor)

    def manifest(self, case_id):
        with self.store.connect() as db:
            return self.store.manifest(self.store.case(db, case_id))

    def count(self, table="cases"):
        with self.store.connect() as db:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def audit(self, action, target=None):
        with self.store.connect() as db:
            sql = "SELECT detail_json FROM changes WHERE action=?" + (" AND target=?" if target else "")
            return [json.loads(row[0]) for row in db.execute(sql, (action, target) if target else (action,))]

    def expect_http(self, code, callable_, *args, **kwargs):
        with self.assertRaises(HTTPException) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(caught.exception.status_code, code, caught.exception.detail)

    def linked(self, first, **columns):
        row = first.rows[0]
        request = self.request.model_copy(deep=True)
        request.request_id = "preview-update"
        request.targets = [FormsTargetV4(row_number=2, case_id=row.case_id, session_id=row.session_id,
                                         expected_revision=self.manifest(row.case_id).input_revision)]
        if columns:
            request.mapping.columns = columns
        return request

    def test_ids_are_fixed_in_preview_and_create_and_survey_commit_together(self):
        staged = self.stage()
        self.assertFalse(staged.errors)
        self.assertEqual(self.count(), 0)
        self.assertEqual(staged.rows[0].answers["s10"], 0)
        self.assertEqual(staged.rows[0].registration_status, "partial")
        result = self.apply(staged)
        self.assertEqual((result.rows[0].case_id, result.rows[0].session_id, result.rows[0].participant_id),
                         (staged.rows[0].case_id, staged.rows[0].session_id, staged.rows[0].participant_id))
        manifest = self.manifest(result.rows[0].case_id)
        self.assertEqual(manifest.sessions[0].survey["s01"], 3)
        self.assertIsNone(manifest.sessions[0].survey["s02"])
        self.assertEqual(manifest.consents.analysis_feedback, "unknown")
        self.assertEqual(manifest.consents.stranger_contact, "unknown")

    def test_same_names_and_timestamps_do_not_merge_participants(self):
        data = csv_bytes([["반려견", "문항1", "두려움", "타임스탬프"],
                          ["동명이견", "3", "0", "2026-01-01"], ["동명이견", "3", "0", "2026-01-01"]])
        staged = self.stage(data)
        self.assertFalse(staged.errors)
        self.assertEqual(len({row.participant_id for row in staged.rows}), 2)
        self.apply(staged)
        self.assertEqual(self.count(), 2)

    def test_request_and_file_idempotency_preserve_ids_and_revision(self):
        staged = self.stage()
        self.assertEqual(self.stage(), staged)
        different_request = self.request.model_copy(deep=True)
        different_request.request_id, different_request.filename = "retry-preview", "renamed.csv"
        self.assertEqual(self.stage(request=different_request).preview_id, staged.preview_id)
        result = self.apply(staged)
        self.assertEqual(self.apply(staged), result)
        self.assertEqual(self.apply(staged, "retry-commit"), result)
        self.assertTrue(self.stage(request=different_request).already_committed)
        self.assertEqual(self.manifest(result.rows[0].case_id).input_revision, 1)
        self.assertEqual(self.count(), 1)
        self.assertEqual(len(self.audit("forms.source_row")), 1)

    def test_request_id_different_body_is_rejected_for_preview_and_commit(self):
        staged = self.stage()
        self.expect_http(409, self.stage, self.data + b"\n")
        changed = self.request.model_copy(deep=True)
        changed.filename = "different.csv"
        self.expect_http(409, self.stage, request=changed)
        self.apply(staged)
        self.expect_http(409, commit, self.store, FormsCommitRequestV4(request_id="commit-1", preview_id=staged.preview_id,
                                                                    preview_hash="0" * 64), "operator")

    def test_error_in_later_row_blocks_entire_commit(self):
        staged = self.stage(csv_bytes([["반려견", "문항1", "두려움"], ["정상합성", "3", "0"], ["오류합성", "maybe", "0"]]))
        self.assertEqual(staged.errors[0].row_number, 3)
        self.expect_http(422, self.apply, staged)
        self.assertEqual(self.count(), 0)
        self.assertFalse(self.audit("forms.source_row"))

    def test_storage_failure_on_second_row_rolls_back_all_rows(self):
        staged = self.stage(csv_bytes([["반려견", "문항1", "두려움"], ["합성1", "3", "0"], ["합성2", "3", "0"]]))
        original = self.store.write_manifest
        calls = []
        def fail_second(manifest):
            calls.append(manifest.case_id)
            if len(calls) == 2:
                raise OSError("synthetic storage failure")
            return original(manifest)
        with patch.object(self.store, "write_manifest", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.apply(staged)
        self.assertEqual(self.count(), 0)
        self.assertFalse(self.audit("forms.source_row"))
        self.assertFalse(self.audit("forms.commit"))
        self.assertEqual(len(self.apply(staged).rows), 2)

    def test_existing_target_shows_before_after_and_adds_revision(self):
        first = self.stage()
        self.apply(first)
        request = self.linked(first, s01="문항1", s10="두려움", s02_reason="결측사유")
        updated = self.stage(csv_bytes([["문항1", "두려움", "결측사유"], ["5", "2", "합성 미응답"]]), request)
        self.assertFalse(updated.errors)
        self.assertEqual(updated.rows[0].previous_answers["s01"], 3)
        self.assertEqual(updated.rows[0].answers["s01"], 5)
        self.assertIn("s02", updated.rows[0].changed_questions)
        result = self.apply(updated, "update-commit")
        self.assertEqual(result.rows[0].input_revision, 2)
        manifest = self.manifest(first.rows[0].case_id)
        self.assertEqual(manifest.sessions[0].survey_blank_reasons, {"s02": "합성 미응답"})
        self.assertEqual(len(manifest.prior_inputs), 1)
        self.assertEqual(len(self.audit("forms.source_row")), 2)

    def test_revision_changed_after_preview_blocks_every_write(self):
        first = self.stage()
        self.apply(first)
        updated = self.stage(self.data, self.linked(first))
        with self.store.connect(write=True) as db:
            row = self.store.case(db, first.rows[0].case_id)
            manifest = self.store.manifest(row)
            manifest.sessions[0].note = "동시 변경"
            self.store.save(db, row, manifest, "operator", "test.change")
        self.expect_http(409, self.apply, updated, "update-commit")
        self.assertEqual(self.manifest(first.rows[0].case_id).input_revision, 2)

    def test_selected_session_changed_after_preview_blocks_commit(self):
        first = self.stage()
        self.apply(first)
        updated = self.stage(self.data, self.linked(first))
        with self.store.connect(write=True) as db:
            row = self.store.case(db, first.rows[0].case_id)
            manifest = self.store.manifest(row)
            manifest.sessions.append(new_session_v4("other-session"))
            manifest.selected_session_id = "other-session"
            self.store.save(db, row, manifest, "operator", "test.session")
        self.expect_http(409, self.apply, updated, "update-commit")

    def test_deleted_participant_blocks_commit_and_idempotent_response(self):
        first = self.stage()
        self.apply(first)
        updated = self.stage(self.data, self.linked(first))
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (first.rows[0].case_id,))
        self.expect_http(403, self.apply, updated, "update-commit")
        self.expect_http(403, self.apply, first)
        self.expect_http(403, self.stage)

    def test_permissions_are_rechecked_even_for_completed_requests(self):
        staged = self.stage()
        self.expect_http(403, self.apply, staged, actor="reviewer")
        self.apply(staged)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='operator'")
        self.expect_http(403, self.apply, staged)
        self.expect_http(403, self.stage)

    def test_explicit_id_collision_is_shown_without_name_matching(self):
        request = self.request.model_copy(deep=True)
        request.mapping.columns["participant_id"] = "ID"
        data = csv_bytes([["ID", "반려견", "문항1", "두려움"], ["0001", "합성견", "3", "0"]])
        first = self.stage(data, request)
        self.apply(first)
        request.request_id = "new-attempt"
        staged = self.stage(data + b"\n", request)
        self.assertEqual(len(staged.errors), 1)
        self.assertIn("명시", staged.errors[0].message)
        self.assertEqual(self.count(), 1)

    def test_duplicate_headers_formulas_and_missing_mapping_headers_fail(self):
        for rows in ([["반려견", "문항1", "문항1"], ["합성", "3", "0"]],
                     [["반려견", "문항1", " 문항1 "], ["합성", "3", "0"]],
                     [["반려견", "문항1", "두려움", "미사용"], ["합성", "3", "0", "=SUM(1,2)"]],
                     [["반려견", "누락"], ["합성", "3"]]):
            with self.subTest(rows=rows):
                self.expect_http(422, self.stage, csv_bytes(rows))

    def test_labels_are_explicit_and_ambiguous_or_wrong_scale_mappings_fail(self):
        request = self.request.model_copy(deep=True)
        request.mapping.answer_labels = {"s01": {"예시 응답": 4}}
        staged = self.stage(csv_bytes([["반려견", "문항1", "두려움"], ["합성", "예시 응답", "0"]]), request)
        self.assertEqual(staged.rows[0].answers["s01"], 4)
        for labels in ({"3": 5}, {"예시": 0}):
            request.request_id += "x"
            request.mapping.answer_labels = {"s01": labels}
            self.expect_http(422, self.stage, request=request)
        with self.assertRaises(ValidationError):
            FormsMappingV4.model_validate({**request.mapping.model_dump(), "answer_labels": {"s01": {"예시": 1, " 예시 ": 2}}})

    def test_xlsx_sheet_labels_and_raw_integer_zero_are_supported(self):
        request = self.request.model_copy(deep=True)
        request.format, request.filename, request.mapping.sheet = "xlsx", "synthetic.xlsx", "응답"
        data = xlsx_bytes([["반려견", "문항1", "두려움"], ["합성견", 3, 0]])
        staged = self.stage(data, request)
        self.assertEqual(staged.source_sheet, "응답")
        self.assertEqual(staged.rows[0].raw_values["문항1"], 3)
        self.assertEqual(staged.rows[0].answers["s10"], 0)
        self.apply(staged)

    def test_column_inspection_shares_layout_header_and_formula_checks(self):
        inspected = inspect_columns(csv_bytes([["반려견", "합성견"], ["문항1", "3"], ["두려움", "0"]]),
                                    "csv", layout="transposed")
        self.assertEqual(inspected["columns"], [{"key": x, "label": x} for x in ("반려견", "문항1", "두려움")])
        self.assertEqual(inspected["sheets"], [])
        self.assertIsNone(inspected["selected_sheet"])
        inspected = inspect_columns(xlsx_bytes([["반려견", "문항1"], ["합성견", 3]]), "xlsx", "응답")
        self.assertEqual(inspected["sheets"], ["응답"])
        self.assertEqual(inspected["selected_sheet"], "응답")
        self.expect_http(422, inspect_columns, csv_bytes([["반려견", "반려견"]]), "csv")
        self.expect_http(422, inspect_columns, xlsx_bytes([["문항1"], ["=1+2"]]), "xlsx")

    def test_xlsx_formula_and_boolean_answer_are_rejected(self):
        request = self.request.model_copy(deep=True)
        request.format = "xlsx"
        self.expect_http(422, self.stage, xlsx_bytes([["반려견", "문항1", "두려움"], ["합성", "=1+2", 0]]), request)
        staged = self.stage(xlsx_bytes([["반려견", "문항1", "두려움"], ["합성", True, 0]]), request)
        self.assertEqual(staged.errors[0].row_number, 2)
        self.expect_http(422, self.apply, staged)

    def test_unsupported_scale_is_reference_only_and_never_converted(self):
        request = self.request.model_copy(deep=True)
        request.mapping.survey_version = "historical-comfort-1-to-5"
        request.mapping.historical_reference_only = True
        request.mapping.source_profile = "합성 과거 전치표"
        request.mapping.layout = "transposed"
        staged = self.stage(csv_bytes([["반려견", "과거합성"], ["문항1", "5"], ["두려움", "1"]]), request)
        self.assertFalse(staged.errors)
        self.assertEqual(staged.rows[0].registration_status, "reference_only")
        self.assertTrue(all(value is None for value in staged.rows[0].answers.values()))
        result = self.apply(staged)
        self.assertEqual(result.rows[0].registration_status, "reference_only")
        self.assertTrue(all(value is None for value in self.manifest(result.rows[0].case_id).sessions[0].survey.values()))
        link = self.audit("forms.source_row")[0]
        capsule = json.loads(self.store.path(link["ref"]).read_bytes())
        self.assertEqual(capsule["raw_values"]["두려움"], "1")
        self.assertEqual(capsule["mapping"]["survey_version"], "historical-comfort-1-to-5")

    def test_unsupported_scale_requires_reference_only_flag(self):
        with self.assertRaises(ValidationError):
            FormsMappingV4.model_validate({**self.request.mapping.model_dump(), "survey_version": "unknown-edition"})

    def test_missing_target_row_or_duplicate_target_is_rejected(self):
        first = self.stage()
        self.apply(first)
        request = self.linked(first)
        request.targets[0].row_number = 3
        staged = self.stage(self.data, request)
        self.assertTrue(any(issue.row_number == 3 for issue in staged.errors))
        self.expect_http(422, self.apply, staged, "update-commit")
        with self.assertRaises(ValidationError):
            FormsPreviewRequestV4.model_validate({**request.model_dump(), "targets": [request.targets[0].model_dump()] * 2})

    def test_source_bytes_hash_mapping_and_rows_are_reachable_for_backup(self):
        staged = self.stage()
        self.assertEqual(staged.source_hash, hashlib.sha256(self.data).hexdigest())
        record_link = self.audit("forms.preview")[0]
        record = json.loads(self.store.path(record_link["ref"]).read_bytes())
        self.assertEqual(self.store.path(record["source"]["ref"]).read_bytes(), self.data)
        self.assertEqual(record["request"]["mapping"]["version"], "mapping-1")
        self.assertEqual(record["original_rows"][1][0], "합성견")
        self.apply(staged)
        with self.store.connect() as db:
            refs = references(self.store, db)
        self.assertIn(record_link["ref"], refs)
        self.assertIn(record["source"]["ref"], refs)
        self.assertIn(self.audit("forms.source_row")[0]["ref"], refs)

    def test_tampered_original_blocks_commit(self):
        staged = self.stage()
        record = json.loads(self.store.path(self.audit("forms.preview")[0]["ref"]).read_bytes())
        self.store.path(record["source"]["ref"]).write_bytes(b"corrupt synthetic file")
        self.expect_http(409, self.apply, staged)
        self.assertEqual(self.count(), 0)

    def test_tampered_preview_blocks_commit(self):
        staged = self.stage()
        self.store.path(self.audit("forms.preview")[0]["ref"]).write_bytes(b"{}")
        self.expect_http(409, self.apply, staged)

    def test_partial_deletion_purges_shared_source_but_preserves_other_row(self):
        data = csv_bytes([["반려견", "문항1", "두려움"], ["삭제합성", "3", "0"], ["보존합성", "4", "1"]])
        staged = self.stage(data)
        self.apply(staged)
        record_link = self.audit("forms.preview")[0]
        record = json.loads(self.store.path(record_link["ref"]).read_bytes())
        deleted, retained = staged.rows
        kept_link = self.audit("forms.source_row", retained.case_id)[0]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (deleted.case_id,))
            purge_case_imports(self.store, db, deleted.case_id)
        clean(self.store, purge_deleted=True)
        self.assertFalse(self.store.path(record_link["ref"]).exists())
        self.assertFalse(self.store.path(record["source"]["ref"]).exists())
        self.assertTrue(self.store.path(kept_link["ref"]).exists())
        self.assertEqual(self.manifest(retained.case_id).sessions[0].survey["s01"], 4)
        self.expect_http(409, self.apply, staged)
        request = self.request.model_copy(deep=True)
        request.request_id = "reimport"
        request.mapping.version = "mapping-after-deletion"
        self.expect_http(409, self.stage, data, request)
        tombstones = self.audit("forms.purged")
        self.assertTrue(tombstones)
        self.assertTrue(all(set(value) == {"source_hash"} for value in tombstones))

    def test_error_only_previews_are_purged_by_explicit_target_or_stable_identity(self):
        first = self.stage()
        self.apply(first)
        linked = self.linked(first)
        invalid = self.stage(csv_bytes([["반려견", "문항1", "두려움"], ["오류합성", "invalid", "0"]]), linked)
        self.assertFalse(invalid.rows)
        self.assertTrue(invalid.errors)
        collision = self.request.model_copy(deep=True)
        collision.request_id = "collision"
        collision.mapping.columns["participant_id"] = "ID"
        staged = self.stage(csv_bytes([["ID", "반려견", "문항1", "두려움"],
                                      [first.rows[0].participant_id, "중복합성", "3", "0"]]), collision)
        self.assertFalse(staged.rows)
        links = self.audit("forms.preview")
        sources = [json.loads(self.store.path(link["ref"]).read_bytes())["source"] for link in links]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (first.rows[0].case_id,))
        self.expect_http(403, self.stage, csv_bytes([["반려견", "문항1", "두려움"], ["오류합성", "invalid", "0"]]), linked)
        self.expect_http(403, self.apply, invalid, "commit-error-after-deletion")
        with self.store.connect(write=True) as db:
            purge_case_imports(self.store, db, first.rows[0].case_id)
        clean(self.store, purge_deleted=True)
        self.assertFalse(self.audit("forms.preview"))
        self.assertTrue(all(not self.store.path(link["ref"]).exists() for link in links + sources))

    def test_already_deleted_target_cannot_leave_a_new_preview_blob(self):
        first = self.stage()
        self.apply(first)
        request = self.linked(first)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (first.rows[0].case_id,))
        initial = len(self.audit("forms.preview"))
        self.expect_http(403, self.stage, self.data, request)
        self.assertEqual(len(self.audit("forms.preview")), initial)

    def test_failed_new_identity_then_corrected_registration_purges_both_sources(self):
        request = self.request.model_copy(deep=True)
        request.mapping.columns["participant_id"] = "ID"
        failed = self.stage(csv_bytes([["ID", "반려견", "문항1", "두려움"], ["P001", "합성견", "bad", "0"]]), request)
        self.assertFalse(failed.rows)
        self.assertTrue(failed.errors)
        request.request_id = "corrected"
        good = self.stage(csv_bytes([["ID", "반려견", "문항1", "두려움"], ["P001", "합성견", "3", "0"]]), request)
        self.apply(good)
        links = self.audit("forms.preview")
        sources = [json.loads(self.store.path(link["ref"]).read_bytes())["source"] for link in links]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (good.rows[0].case_id,))
        request.request_id = "failed-retry"
        self.expect_http(403, self.stage,
                         csv_bytes([["ID", "반려견", "문항1", "두려움"], ["P001", "합성견", "bad", "0"]]), request)
        with self.store.connect(write=True) as db:
            purge_case_imports(self.store, db, good.rows[0].case_id)
        clean(self.store, purge_deleted=True)
        self.assertFalse(self.audit("forms.preview"))
        self.assertTrue(all(not self.store.path(link["ref"]).exists() for link in links + sources))

    def test_deletion_purges_other_sheet_preview_that_references_same_workbook_bytes(self):
        book = Workbook()
        book.active.title = "첫시트"
        book.create_sheet("둘째시트")
        for index, sheet in enumerate(book.worksheets, 1):
            sheet.append(["ID", "반려견", "문항1", "두려움"])
            sheet.append([f"P00{index}", f"합성{index}", 3, 0])
        out = io.BytesIO()
        book.save(out)
        book.close()
        request = self.request.model_copy(deep=True)
        request.mapping.columns["participant_id"] = "ID"
        request.format = "xlsx"
        request.mapping.sheet = "첫시트"
        first = self.stage(out.getvalue(), request)
        self.apply(first)
        request.request_id = "second-sheet"
        request.mapping.sheet = "둘째시트"
        second = self.stage(out.getvalue(), request)
        self.apply(second, "commit-second")
        links = self.audit("forms.preview")
        sources = [json.loads(self.store.path(link["ref"]).read_bytes())["source"] for link in links]
        kept_link = self.audit("forms.source_row", second.rows[0].case_id)[0]
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (first.rows[0].case_id,))
            purge_case_imports(self.store, db, first.rows[0].case_id)
        clean(self.store, purge_deleted=True)
        self.assertFalse(self.audit("forms.preview"))
        self.assertTrue(all(not self.store.path(link["ref"]).exists() for link in links + sources))
        self.assertTrue(self.store.path(kept_link["ref"]).exists())
        self.assertEqual(self.manifest(second.rows[0].case_id).input_revision, 1)
        self.expect_http(409, self.apply, second, "commit-second")

    def restore_preview_before_case_existed(self, *, failed_first):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-forms-backup-v4-")
        self.addCleanup(temporary.cleanup)
        destination = Path(temporary.name)
        request = self.request.model_copy(deep=True)
        if failed_first:
            request.mapping.columns["participant_id"] = "ID"
            bad = self.stage(csv_bytes([["ID", "반려견", "문항1", "두려움"], ["P001", "합성", "bad", "0"]]), request)
            self.assertTrue(bad.errors)
        else:
            staged = self.stage()
        backup(self.store, destination / "snapshot", "operator")
        if failed_first:
            request.request_id = "corrected"
            staged = self.stage(csv_bytes([["ID", "반려견", "문항1", "두려움"], ["P001", "합성", "3", "0"]]), request)
        self.apply(staged)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (staged.rows[0].case_id,))
        clean(self.store, purge_deleted=True)
        restore(self.store, destination / "snapshot", destination / "restored")
        restored = Store(destination / "restored")
        with restored.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM changes WHERE action='deletion.record'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='forms.preview'").fetchone()[0], 0)
            self.assertFalse(any("forms-" in ref for ref in references(restored, db)))
        self.assertFalse(list(restored.path("inputs").glob("forms-*")))

    def test_restore_deletion_ledger_purges_error_preview_before_case_existed(self):
        self.restore_preview_before_case_existed(failed_first=True)

    def test_restore_deletion_ledger_purges_generated_identity_preview_before_case_existed(self):
        self.restore_preview_before_case_existed(failed_first=False)


if __name__ == "__main__":
    unittest.main()
