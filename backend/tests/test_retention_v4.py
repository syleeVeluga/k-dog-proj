"""AR04 legacy metadata is provenance; actual source and execution guards stay active."""
import hashlib
from itertools import product
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from app import comparisons_v4 as comparisons, exports_v4 as exports, maintenance
from app.storage import Store, encode
from tests import test_report_runs_v4 as report_fixture, test_run_v4 as run_fixture
from tests.support import AppCase


class RetentionApiV4Tests(AppCase):
    def test_every_legacy_state_lists_and_serves_original_and_omitted_edit_preserves_metadata(self):
        for state, confirmed, deleted in product(("unknown", "declined", "confirmed"), (0, 1), (0, 1)):
            with self.subTest(state=state, confirmed=confirmed, deleted=deleted):
                item = self.make_case(f"{state}-{confirmed}-{deleted}")
                item = self.upload(item).json()
                with self.store.connect(write=True) as db:
                    row = self.store.case(db, item["case_id"])
                    manifest = self.store.manifest(row)
                    manifest.consents.analysis_feedback = state
                    manifest.consents.stranger_contact = state
                    self.store.save(db, row, manifest, "operator", "synthetic.legacy_metadata")
                    db.execute("UPDATE cases SET consent_confirmed=?,deletion_requested=? WHERE case_id=?", (confirmed, deleted, item["case_id"]))
                    self.store.audit(db, "operator", item["case_id"], "deletion.record", {"event_id": item["event_id"], "participant_id": item["participant_id"]})
                shown = self.get_case(item)
                self.assertNotIn("consents", shown)
                self.assertNotIn("consent_confirmed", shown)
                self.assertNotIn("deletion_requested", shown)
                self.assertIn(item["case_id"], [row["case_id"] for row in self.client.get('/api/cases').json()])
                video = shown["manifest"]["sessions"][0]["videos"][0]
                self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}").status_code, 200)
                response = self.client.put(f"/api/cases/{item['case_id']}", json={"expected_revision":shown["input_revision"], "participant_id":item["participant_id"], "dog_name":item["dog_name"]})
                self.assertEqual(response.status_code, 200, response.text)
                with self.store.connect() as db:
                    row = self.store.case(db, item["case_id"])
                    self.assertEqual(row["consent_confirmed"], confirmed)
                    self.assertEqual(row["deletion_requested"], deleted)
                    self.assertEqual(self.store.manifest(row).consents.analysis_feedback, state)

    def test_missing_reference_is_truthful_and_clean_does_not_delete_other_files(self):
        item = self.upload(self.make_case()).json()
        video = item["manifest"]["sessions"][0]["videos"][0]
        source = self.store.path(video["storage_ref"])
        raw = source.read_bytes()
        source.unlink()
        orphan = self.store.path("clips/synthetic-orphan.bin")
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"synthetic unattached bytes")
        with self.assertRaises(FileNotFoundError):
            maintenance.clean(self.store)
        self.assertTrue(orphan.exists())
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}").status_code, 409)
        source.write_bytes(raw)
        maintenance.clean(self.store)
        self.assertFalse(orphan.exists())
        self.assertEqual(source.read_bytes(), raw)


class RetentionWorkflowV4Tests(unittest.TestCase):
    def test_full_legacy_matrix_scoring_report_cohort_export_clean_and_repeated_restore(self):
        original_save = Store.save
        for state, confirmed, deleted in product(("unknown", "declined", "confirmed"), (0, 1), (0, 1)):
            with self.subTest(state=state, confirmed=confirmed, deleted=deleted):
                def legacy_save(store, db, row, manifest, *args, **kwargs):
                    manifest.consents.analysis_feedback = state
                    manifest.consents.stranger_contact = state
                    result = original_save(store, db, row, manifest, *args, **kwargs)
                    db.execute("UPDATE cases SET consent_confirmed=?,deletion_requested=? WHERE case_id=?", (confirmed, deleted, row["case_id"]))
                    return result
                fixture = report_fixture.ReportRunV4Tests()
                with patch.object(Store, "save", legacy_save):
                    fixture.setUp()
                try:
                    store, user = fixture.store, fixture.user
                    run_id = fixture.publish()  # Actual Worker, synthetic local renderer, no paid provider.
                    issued = report_fixture.reports.download(store, fixture.case_id, fixture.session_id, run_id, "pdf", user)[0]
                    current = fixture.current()
                    cohort = comparisons.create(store, comparisons.CohortCreateV4(request_id='legacy-cohort', title='synthetic', reason='legacy matrix', members=[{
                        'case_id':fixture.case_id, 'session_id':fixture.session_id, 'expected_revision':current['input_revision'],
                        'input':{'manifest_ref':current['manifest_ref'], 'manifest_hash':current['manifest_hash']}}]), user)
                    self.assertTrue(comparisons.for_report(store, cohort.reference, user))
                    export = exports.create(store, exports.ExportCreateV4.model_validate_json(encode({'request_id':'legacy-export', 'format':'csv_zip', 'reason':'synthetic matrix', 'members':[{
                        'case_id':fixture.case_id, 'session_id':fixture.session_id, 'sheet':fixture.basic['document']['input'], 'basic':fixture.basic_ref, 'final':fixture.final['reference']}]})), user)
                    output = exports.download(store, export['export_id'], user)[0]
                    with store.connect(write=True) as db:
                        store.audit(db, user.username, fixture.case_id, 'deletion.record', {'event_id':current['event_id'], 'participant_id':current['participant_id']})
                        refs = maintenance.references(store, db)
                        before_events = [tuple(row) for row in db.execute('SELECT * FROM changes ORDER BY rowid')]
                    maintenance.clean(store)
                    self.assertEqual({ref:hashlib.sha256(store.path(ref).read_bytes()).hexdigest() for ref in refs}, refs)
                    root = Path(fixture.helper.temp.name)
                    maintenance.backup(store, root/'snapshot', user.username)
                    with store.connect(write=True) as db:
                        store.audit(db, user.username, 'after-backup', 'deletion.record', {'event_id':'after','participant_id':'after'})
                    for number in (1, 2):
                        maintenance.restore(store, root/'snapshot', root/f'restored-{number}')
                        recovered = Store(root/f'restored-{number}')
                        with recovered.connect() as db:
                            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM changes ORDER BY rowid')], before_events)
                            self.assertEqual(maintenance.references(recovered, db), refs)
                            row = recovered.case(db, fixture.case_id)
                            self.assertEqual((row['consent_confirmed'], row['deletion_requested']), (confirmed, deleted))
                            self.assertEqual(recovered.manifest(row).consents.analysis_feedback, state)
                        self.assertEqual(report_fixture.reports.download(recovered, fixture.case_id, fixture.session_id, run_id, 'pdf', user)[0], issued)
                        self.assertEqual(exports.download(recovered, export['export_id'], user)[0], output)
                finally:
                    fixture.doCleanups()

    def test_actual_ai_handler_accepts_current_and_frozen_legacy_state_matrix(self):
        original_save = Store.save
        for state, confirmed, deleted in product(("unknown", "declined", "confirmed"), (0, 1), (0, 1)):
            with self.subTest(state=state, confirmed=confirmed, deleted=deleted):
                def legacy_save(store, db, row, manifest, *args, **kwargs):
                    manifest.consents.analysis_feedback = state
                    result = original_save(store, db, row, manifest, *args, **kwargs)
                    db.execute("UPDATE cases SET consent_confirmed=?,deletion_requested=? WHERE case_id=?", (confirmed, deleted, row["case_id"]))
                    return result
                fixture = run_fixture.RunV4Tests()
                with patch.object(Store, "save", legacy_save):
                    fixture.setUp()
                try:
                    # Actual 42-group S1 handler creates 86 AI rows and a pinned basic result.
                    fixture.test_actual_handler_calculates_and_publishes_full_s1_with_fake_provider()
                    with fixture.store.connect() as db:
                        case = fixture.store.case(db, fixture.case_id)
                        self.assertEqual(fixture.store.manifest(case).consents.analysis_feedback, state)
                        self.assertEqual((case["consent_confirmed"], case["deletion_requested"]), (confirmed, deleted))
                finally:
                    fixture.doCleanups()

    def test_purge_deleted_cli_is_usage_error_without_touching_data(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.manage', 'clean', '--purge-deleted'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments: --purge-deleted', result.stderr)

    def test_legacy_flag_changed_during_reserved_work_does_not_stop_adoption(self):
        fixture = run_fixture.RunV4Tests(); fixture.setUp()
        try:
            created = fixture.enqueue()
            def handler(snapshot, stage, row):
                validate, work = fixture.handler(snapshot, stage, row)
                def change(step):
                    result = work(step)
                    with fixture.store.connect(write=True) as db:
                        db.execute('UPDATE cases SET deletion_requested=1,consent_confirmed=0 WHERE case_id=?', (fixture.case_id,))
                    return result
                return validate, change
            fixture.worker(handler).once()
            self.assertEqual(fixture.row(created['run_id'])['status'], 'succeeded')
        finally:
            fixture.doCleanups()
