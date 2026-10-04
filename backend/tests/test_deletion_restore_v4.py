"""Synthetic stable case identity survives deletion and repeated old-backup restores."""
import json
from pathlib import Path
import unittest

from app import maintenance
from app.storage import Store
from tests import test_sheets_v4 as support


class DeletionRestoreV4Tests(unittest.TestCase):
    def test_changed_participant_id_cannot_resurrect_same_case_from_older_backup(self):
        for cleaned_before_restore in (False, True):
            with self.subTest(cleaned_before_restore=cleaned_before_restore):
                fixture = support.SheetsV4Tests()
                fixture.setUp()
                try:
                    store, case_id = fixture.store, fixture.case_id
                    root = Path(fixture.temp.name)
                    with store.connect() as db:
                        before = store.case(db, case_id)
                        old_participant_id = before["participant_id"]
                        original_ref = before["manifest_ref"]
                    maintenance.backup(store, root / "before-id-edit", "operator")
                    with store.connect(write=True) as db:
                        case = store.case(db, case_id)
                        manifest = store.manifest(case)
                        manifest.participant_id = "RENAMED-SYNTHETIC-ID"
                        store.save(db, case, manifest, "operator", "case.update")
                        db.execute("UPDATE cases SET participant_id=?,deletion_requested=1 WHERE case_id=?",
                                   (manifest.participant_id, case_id))
                        store.audit(db, "operator", case_id, "case.identity", {
                            "before": {"participant_id": old_participant_id},
                            "after": {"participant_id": manifest.participant_id},
                        })
                    if cleaned_before_restore:
                        maintenance.clean(store, purge_deleted=True)
                    # The second restore uses only the ledger left by the first.
                    # Neither ledger may lose the stable ID when the case is absent.
                    for number in (1, 2):
                        destination = root / f"restored-{number}"
                        maintenance.restore(store, root / "before-id-edit", destination)
                        store = Store(destination)
                        with store.connect() as db:
                            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE case_id=?", (case_id,)).fetchone()[0], 0)
                            records = list(db.execute("SELECT target,detail_json FROM changes WHERE action='deletion.record'"))
                            self.assertTrue(any(row["target"] == case_id for row in records))
                            self.assertTrue(any(json.loads(row["detail_json"])["participant_id"] == "RENAMED-SYNTHETIC-ID" for row in records))
                        self.assertFalse(store.path(original_ref).exists())
                finally:
                    fixture.doCleanups()
