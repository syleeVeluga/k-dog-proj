"""Synthetic API and backup checks for the same-edition comparison boundary."""
import unittest

from fastapi.testclient import TestClient
from app.api import create_app
from app.auth import password_hash
from app import maintenance
from app.storage import Store
from tests import test_comparisons_v4 as support


class ComparisonApiV4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.ExternalComparisonGateV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        with self.store.connect(write=True) as db:
            db.execute('UPDATE users SET password_hash=?', (password_hash('Synthetic-Comparison-2026!'),))
        self.client = TestClient(create_app(self.store.root), base_url='http://127.0.0.1:8000', headers={'X-KDOG-Request': '1'})
        self.addCleanup(self.client.close)
        self.login('operator')

    def login(self, name):
        self.assertEqual(self.client.post('/api/auth/login', json={'username': name, 'password': 'Synthetic-Comparison-2026!'}).status_code, 200)

    def test_explicit_cohort_api_preserves_valid_n_and_current_authority(self):
        f = self.fixture
        candidates = self.client.get('/api/comparisons-s1/candidates').json()
        self.assertEqual({row['case_id'] for row in candidates}, set(f.ids))
        self.assertTrue(all(row['input']['manifest_hash'] and row['sessions'] for row in candidates))
        body = {'request_id': 'api-cohort', 'title': '합성 자체 집단', 'reason': '명시 선택 시험',
                'members': [f.selection(key).model_dump(mode='json') for key in f.ids]}
        self.assertEqual(self.client.get('/api/comparisons-s1/cohorts').json(), [])
        result = self.client.post('/api/comparisons-s1/cohorts', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        saved = result.json()
        self.assertEqual(self.client.post('/api/comparisons-s1/cohorts', json=body).json(), saved)
        self.assertEqual(len(self.client.get('/api/comparisons-s1/cohorts').json()), 1)
        self.assertTrue(any(row['n'] < 3 for row in saved['document']['domains']))
        sources = self.client.get('/api/comparisons-s1/sources')
        self.assertEqual(sources.status_code, 200)
        self.assertNotIn('reference_values', sources.text)
        self.assertNotIn('42926', sources.text)
        self.assertEqual(self.client.get('/api/comparisons-s1/research').status_code, 403)
        self.login('admin')
        self.assertEqual(self.client.get('/api/comparisons-s1/research').status_code, 200)
        self.login('reviewer')
        self.assertEqual(self.client.get('/api/comparisons-s1/cohorts').status_code, 403)
        self.login('operator')
        with self.store.connect(write=True) as db:
            db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?', (f.ids[0],))
        self.assertEqual(self.client.get('/api/comparisons-s1/cohorts/' + saved['reference']['snapshot_id']).status_code, 403)

    def test_typed_research_and_cohort_backup_reapply_deleted_member(self):
        f = self.fixture
        cohort = f.create()
        research = f.confirmation(requirements={'ref': 'raw condition, not a file', 'condition_json': 'ordinary text'})
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
        self.assertIn(cohort.reference.ref, refs)
        self.assertIn(research.ref, refs)
        self.assertIn('comparison-evidence/synthetic.txt', refs)
        backup = self.store.root.parent / (self.store.root.name + '-backup')
        restored = self.store.root.parent / (self.store.root.name + '-restored')
        self.addCleanup(self._remove, backup)
        self.addCleanup(self._remove, restored)
        maintenance.backup(self.store, backup, f.admin.username)
        with self.store.connect(write=True) as db:
            db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?', (f.ids[0],))
        maintenance.clean(self.store, purge_deleted=True)
        self.assertFalse(self.store.path(cohort.reference.ref).exists())
        maintenance.restore(self.store, backup, restored)
        target = Store(restored)
        self.assertFalse(target.path(cohort.reference.ref).exists())
        self.assertTrue(target.path(research.ref).exists())
        with target.connect() as db:
            self.assertFalse(db.execute("SELECT 1 FROM changes WHERE action='comparison.s1.snapshot'").fetchone())

    @staticmethod
    def _remove(path):
        import shutil
        shutil.rmtree(path, ignore_errors=True)
