"""S09 transport regressions exercise real disclosure guards and immutable pins."""
import unittest
from fastapi.testclient import TestClient

from app.api import create_app
from app.auth import password_hash
from app import judgements_v4 as basics, sheets_v4 as sheets
from tests import test_disclosures_v4 as support
from tests.test_opinions_v4 import model


class OpinionsApiV4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.DisclosureV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET password_hash=?", (password_hash("Synthetic-Password-2026!"),))
        app = create_app(self.store.root)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request":"1"})
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.post('/api/auth/login',json={"username":"operator","password":"Synthetic-Password-2026!"}).status_code,200)
        self.path = f'/api/cases/{self.fixture.case_id}/sessions/{self.fixture.session_id}'

    def test_other_interpretation_requires_exact_disclosure_and_final_history_stays_pinned(self):
        f = self.fixture
        meta = self.client.get(self.path+'/opinions-s1/metadata')
        self.assertEqual(meta.status_code,200,meta.text)
        self.assertTrue(meta.json()['requires_reveal'])
        self.assertEqual(self.client.get(self.path+'/opinions-s1').status_code,403)
        original = self.store.path(f.sheet['manifest_ref']).read_bytes()
        request = f.request().model_dump(mode='json')
        revealed = self.client.post(self.path+'/opinions-s1/reveal',json=request)
        self.assertEqual(revealed.status_code,200,revealed.text)
        self.assertEqual(revealed.json()['viewer']['purpose'],'review')
        self.assertEqual(self.store.path(f.sheet['manifest_ref']).read_bytes(),original)
        opinion = self.client.get(self.path+'/opinions-s1')
        self.assertEqual(opinion.status_code,200,opinion.text)
        final = self.client.post(self.path+'/final-results-s1',json={"basic":f.basic_ref,"opinion":f.opinion['reference'],"reason":"synthetic final"})
        self.assertEqual(final.status_code,201,final.text)
        ref = final.json()['reference']
        self.assertEqual(self.client.get(self.path+'/final-results-s1/'+ref['final_id']).json()['reference'],ref)
        bad = {**request,"target":{**request['target'],"kind":"final","revision":None}}
        self.assertEqual(self.client.post(self.path+'/final-results-s1/wrong/reveal',json=bad).status_code,422)

    def test_candidates_require_actual_raw_reveal_and_current_grant(self):
        f = self.fixture
        row = f.admin_sheet
        basic = basics.create(self.store,row['sheet_id'],model(basics.CalculateV4,input={"sheet_id":row['sheet_id'],"revision":row['revision'],"ref":row['manifest_ref'],"hash":row['manifest_hash']}),f.admin)
        result_id = basic['summary']['result_id']
        url = self.path+'/final-results-s1/candidates'
        query = {'viewer_sheet_id':f.sheet['sheet_id']}
        def ids():
            response = self.client.get(url,params=query)
            self.assertEqual(response.status_code,200,response.text)
            return {entry['result_id'] for entry in response.json()}
        self.assertNotIn(result_id,ids())
        f.helper.grant(f.sheet,row)
        self.assertNotIn(result_id,ids())
        self.assertEqual(self.client.get(url+f'/{result_id}/1',params=query).status_code,403)
        f.helper.reveal(f.sheet,row,'operator')
        self.assertIn(result_id,ids())
        view = self.client.get(url+f'/{result_id}/1',params=query)
        self.assertEqual(view.status_code,200,view.text)
        self.assertEqual(view.json()['summary'],basic['summary'])
        with self.store.connect(write=True) as db:
            db.execute('DELETE FROM score_grants WHERE viewer_sheet_id=?',(f.sheet['sheet_id'],))
        self.assertNotIn(result_id,ids())
        self.assertEqual(self.client.get(url+f'/{result_id}/1',params=query).status_code,403)
