"""S1 startup and reset must recognize the actual admitted run kind."""
from pathlib import Path
import subprocess
import sys
import unittest

from app import reset_s1
from tests import test_run_v4 as support


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
