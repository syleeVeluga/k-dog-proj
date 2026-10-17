"""S1 startup and reset must recognize the actual admitted run kind."""
from pathlib import Path
import subprocess
import sys
import unittest

from app import reset_s1
from tests import test_run_v4 as support
from tests import test_attachment_ai_v4 as attachment_support


class S1DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.run = self.fixture.enqueue()
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO users(username,role,password_hash) VALUES('admin','admin','synthetic-only')")
            db.execute("UPDATE runs SET status='stopped' WHERE run_id=?", (self.run['run_id'],))

    def test_existing_s1_run_allows_real_worker_start_without_provider_call(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.manage', '--data-dir', str(self.store.root), 'worker', '--once'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf8', errors='replace'))
        self.assertEqual(self.fixture.row(self.run['run_id'])['status'], 'stopped')

    def test_first_and_repeated_reset_preserve_new_s1_run_and_all_its_parents(self):
        original = self.fixture.row(self.run['run_id'])
        self.assertEqual(reset_s1.preview(self.store)['runs'], 0)
        reset_s1.execute(self.store, 'admin')
        reset_s1.execute(self.store, 'admin')
        self.assertEqual(self.fixture.row(self.run['run_id']), original)
        self.assertTrue(self.store.path(self.fixture.batch_ref).exists())
        self.assertTrue(self.store.path('videos/v1.mp4').exists())


class AttachmentDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = attachment_support.AttachmentOpinionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        self.run, _ = self.fixture.complete()
        self.assertEqual(self.run['status'], 'succeeded')

    def test_completed_attachment_run_allows_real_worker_restart(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.manage', '--data-dir', str(self.store.root), 'worker', '--once'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf8', errors='replace'))

    def test_first_and_repeated_reset_preserve_attachment_run_steps_files_and_audit(self):
        self.assert_preserved_after_reset()

    def test_saved_pre_fix_reset_plan_cannot_delete_attachment_run_or_audit(self):
        with self.store.connect(write=True) as db:
            plan = reset_s1._plan(self.store, db)
            plan['runs'] = [self.run['run_id']]
            plan['changes'] = [row[0] for row in db.execute('SELECT change_id FROM changes WHERE target=?', (self.run['run_id'],))]
            self.store.audit(db, self.fixture.user.username, reset_s1.RESET_ID, 's1.reset.plan', plan)
        self.assert_preserved_after_reset()
        with self.store.connect() as db:
            self.assertEqual(reset_s1._record(db, reset_s1.RESET_ID, 'plan'), plan)

    def assert_preserved_after_reset(self):
        with self.store.connect() as db:
            before_run = dict(db.execute('SELECT * FROM runs WHERE run_id=?', (self.run['run_id'],)).fetchone())
            before_steps = [dict(row) for row in db.execute('SELECT * FROM steps WHERE run_id=? ORDER BY step_id', (self.run['run_id'],))]
            before_audit = [dict(row) for row in db.execute('SELECT * FROM changes WHERE target=? ORDER BY rowid', (self.run['run_id'],))]
        before_files = {row['output_ref']: self.store.path(row['output_ref']).read_bytes() for row in before_steps if row['output_ref']}
        self.assertEqual(reset_s1.preview(self.store)['runs'], 0)
        reset_s1.execute(self.store, self.fixture.user.username)
        reset_s1.execute(self.store, self.fixture.user.username)
        with self.store.connect() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM runs WHERE run_id=?', (self.run['run_id'],)).fetchone()), before_run)
            self.assertEqual([dict(row) for row in db.execute('SELECT * FROM steps WHERE run_id=? ORDER BY step_id', (self.run['run_id'],))], before_steps)
            self.assertEqual([dict(row) for row in db.execute('SELECT * FROM changes WHERE target=? ORDER BY rowid', (self.run['run_id'],))], before_audit)
        for ref, data in before_files.items():
            self.assertEqual(self.store.path(ref).read_bytes(), data)
