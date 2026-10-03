"""S14 HTTP contracts use synthetic workbooks and pinned S1 documents."""
import base64
from io import BytesIO
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from app.api import create_app
from app.auth import password_hash
from tests import test_exports_v4 as export_support, test_validation_data_v4 as reference_support


class ResearchApiV4Tests(unittest.TestCase):
    def setup_fixture(self, kind):
        fixture = kind()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with fixture.store.connect(write=True) as db:
            db.execute('UPDATE users SET password_hash=?', (password_hash('Synthetic-Research-2026!'),))
        client = TestClient(create_app(fixture.store.root), base_url='http://127.0.0.1:8000', headers={'X-KDOG-Request': '1'})
        self.addCleanup(client.close)
        self.assertEqual(client.post('/api/auth/login', json={'username': 'operator', 'password': 'Synthetic-Research-2026!'}).status_code, 200)
        return fixture, client

    def test_reference_preview_register_read_and_score_separation(self):
        f, client = self.setup_fixture(reference_support.ValidationDataV4Tests)
        body = {'config': f.request.model_dump(mode='json'), 'file_base64': base64.b64encode(f.data).decode()}
        inspected = client.post('/api/validation-data-s1/workbook', json={'file_base64': body['file_base64']})
        self.assertEqual(inspected.status_code, 200, inspected.text)
        self.assertIn('Synthetic', inspected.json()['sheets'])
        self.assertEqual(inspected.json()['source_sha256'], f.request.expected_sha256)
        preview = client.post('/api/validation-data-s1/preview', json=body)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(client.get('/api/validation-data-s1').json(), [])
        created = client.post('/api/validation-data-s1', json=body)
        self.assertEqual(created.status_code, 201, created.text)
        saved = created.json()
        self.assertTrue(saved['reference_only'])
        self.assertFalse(saved['score_import_enabled'])
        self.assertEqual(client.post('/api/validation-data-s1', json=body).json(), saved)
        self.assertEqual(len(client.get('/api/validation-data-s1').json()), 1)
        detail = client.get('/api/validation-data-s1/' + saved['reference']['validation_id'])
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json(), saved)
        broken = {**body, 'file_base64': '!invalid'}
        self.assertEqual(client.post('/api/validation-data-s1/preview', json=broken).status_code, 422)

    def test_research_export_download_is_immutable_and_revocation_is_live(self):
        f, client = self.setup_fixture(export_support.ExportV4Tests)
        body = f.request.model_dump(mode='json')
        created = client.post('/api/exports-s1', json=body)
        self.assertEqual(created.status_code, 201, created.text)
        saved = created.json()
        self.assertEqual(client.post('/api/exports-s1', json=body).json(), saved)
        self.assertEqual(client.get('/api/exports-s1').json(), [saved])
        path = '/api/exports-s1/' + saved['export_id']
        self.assertEqual(client.get(path).json(), saved)
        response = client.get(path + '/download')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertIn('raw_observations.csv', archive.namelist())
        with f.store.connect(write=True) as db:
            db.execute('UPDATE cases SET consent_confirmed=0 WHERE case_id=?', (f.case_id,))
        self.assertEqual(client.get(path + '/download').status_code, 403)
