"""S12 API exercises actual renderer/worker, browser policy and guarded downloads."""
import unittest
from fastapi.testclient import TestClient

from app.api import create_app
from app.auth import password_hash
from app.report_render_v4 import render_html
from app.report_pdf_v4 import render_pdf
from tests import test_report_runs_v4 as support


class ReportApiV4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=support.ReportRunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store
        self.fixture.render.side_effect=lambda profile,header,images:(render_html(profile,header,images),render_pdf(profile,header,images))
        with self.store.connect(write=True) as db:
            db.execute('UPDATE users SET password_hash=?',(password_hash('Synthetic-Password-2026!'),))
        self.app=create_app(self.store.root)
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8000',headers={'X-KDOG-Request':'1'})
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'operator','password':'Synthetic-Password-2026!'}).status_code,200)
        f=self.fixture
        self.path=f'/api/cases/{f.case_id}/sessions/{f.session_id}/report-runs-s1'

    def test_explicit_run_and_safe_inline_html_pdf_and_immutable_manifest(self):
        self.assertEqual(self.client.get(self.path).json(),[])
        request=self.fixture.request.model_dump(mode='json')
        first=self.client.post(self.path,json=request)
        self.assertEqual(first.status_code,201,first.text)
        run_id=first.json()['run_id']
        self.assertFalse(first.json()['normal_publish_available'])
        self.assertEqual(self.client.post(self.path,json=request).json()['run_id'],run_id)
        url='/api/report-runs-s1/'+run_id
        stopped=self.client.post(url+'/stop',json={'expected_updated_at':first.json()['updated_at'],'reason':'synthetic stop'})
        self.assertEqual(stopped.status_code,200,stopped.text)
        retry=self.client.post(url+'/retry',json={'expected_updated_at':stopped.json()['updated_at'],'reason':'synthetic retry'})
        self.assertEqual(retry.status_code,200,retry.text)
        self.fixture.work()
        shown=self.client.get(url)
        self.assertEqual(shown.status_code,200,shown.text)
        self.assertTrue(shown.json()['normal_publish_available'])
        self.assertEqual(shown.json()['publication_state'],'issued')
        file_url=self.path+f'/{run_id}/files/'
        html=self.client.get(file_url+'html',params={'inline':True})
        self.assertEqual(html.status_code,200,html.text)
        self.assertIn('inline;',html.headers['content-disposition'])
        self.assertIn("script-src 'none'",html.headers['content-security-policy'])
        self.assertIn('font-src data:',html.headers['content-security-policy'])
        self.assertNotIn('검토용 미리보기',html.text)
        pdf=self.client.get(file_url+'pdf')
        self.assertEqual(pdf.status_code,200)
        self.assertTrue(pdf.content.startswith(b'%PDF-'))
        self.assertIn('attachment;',pdf.headers['content-disposition'])
        manifest=self.client.get(file_url+'manifest')
        self.assertEqual(manifest.status_code,200,manifest.text)
        self.assertEqual(manifest.json()['final'],request['final'])
        self.assertEqual(manifest.json()['profile']['sentence_bank_status'],'pending_G02')
        with self.store.connect(write=True) as db:
            case=self.store.case(db,self.fixture.case_id)
            saved=self.store.manifest(case)
            saved.consents.analysis_feedback='declined'
            self.store.save(db,case,saved,'operator','synthetic revoke')
        self.assertIn(self.client.get(file_url+'pdf').status_code,(403,409))
