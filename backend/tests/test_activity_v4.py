import json
from unittest.mock import patch

from tests import test_sheets_api_v4 as fixtures


class ActivityV4Tests(fixtures.SheetsApiV4Tests):
    test_independent_owner_submit_reopen_history_and_strict_values_over_http = None
    test_nonowners_cannot_bypass_assignment_through_history_or_mutations = None

    def events(self, action=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM changes ORDER BY happened_at,rowid").fetchall()
        return [dict(row) for row in rows if not action or row["action"] == action]

    def test_explicit_opens_repeat_without_polling_events_or_revision_changes(self):
        sheet = self.assign("reviewer")
        reader = self.client_for("reviewer")
        case_path = f"/api/cases/{self.item['case_id']}"
        sheet_path = f"/api/score-sheets-s1/{sheet['sheet_id']}"
        before = reader.get(sheet_path).json()
        for _ in range(10):
            self.assertEqual(reader.get("/api/cases").status_code, 200)
            self.assertEqual(reader.get(case_path).status_code, 200)
            self.assertEqual(reader.get(sheet_path).status_code, 200)
            self.assertEqual(reader.get(case_path + "/activity").status_code, 200)
        self.assertFalse(self.events("case.open"))
        self.assertFalse(self.events("sheet.open"))
        for _ in range(2):
            self.assertEqual(reader.get(case_path + "?purpose=open").status_code, 200)
            self.assertEqual(reader.get(sheet_path + "?purpose=open").status_code, 200)
        self.assertEqual(len(self.events("case.open")), 2)
        marks = self.events("sheet.open")
        self.assertEqual([(row['actor'], row['target']) for row in marks], [("reviewer",sheet['sheet_id'])]*2)
        self.assertEqual(json.loads(marks[0]['detail_json']), {"revision": 1})
        self.assertEqual(reader.get(sheet_path).json(), before)
        self.assertEqual(reader.get(sheet_path + "/revisions/1?purpose=open").status_code, 200)
        self.assertEqual(len(self.events("sheet.open")), 3)
        self.assertEqual(reader.get(sheet_path + "/revisions/999?purpose=open").status_code, 404)
        self.assertEqual(len(self.events("sheet.open")), 3)

    def test_video_open_is_explicit_and_ranges_do_not_add_events(self):
        video = self.item['manifest']['sessions'][0]['videos'][0]
        path = f"/api/cases/{self.item['case_id']}/videos/{video['video_id']}"
        reader = self.client_for("reviewer")
        for _ in range(10):
            self.assertEqual(reader.get(path, headers={"Range":"bytes=0-3"}).status_code, 206)
        self.assertFalse(self.events("video.open"))
        self.assertEqual(reader.post(path + "/open").status_code, 204)
        self.assertEqual(reader.post(path + "/open").status_code, 204)
        marks = self.events("video.open")
        self.assertEqual(len(marks), 2)
        self.assertEqual(marks[0]['actor'], "reviewer")
        self.assertEqual(json.loads(marks[0]['detail_json']), {"case_id":self.item['case_id']})
        self.assertEqual(reader.post(path.replace(self.item['case_id'],'missing')+'/open').status_code, 404)
        self.assertEqual(len(self.events("video.open")), 2)

    def test_failed_audit_rolls_back_save_and_failed_save_has_no_success_event(self):
        sheet = self.assign("operator")
        path = f"/api/score-sheets-s1/{sheet['sheet_id']}"
        before = self.client.get(path).json()
        events = self.events()
        self.assertEqual(self.client.put(path,json={"expected_revision":99,"observations":[]}).status_code,409)
        self.assertEqual(self.events(), events)
        with patch.object(self.store,"audit",side_effect=RuntimeError("synthetic audit failure")):
            with self.assertRaises(RuntimeError):
                self.client.put(path,json={"expected_revision":1,"observations":[]})
        self.assertEqual(self.client.get(path).json(),before)
        self.assertEqual(self.events(),events)
        self.assertEqual(self.client.put(path,json={"expected_revision":1,"observations":[]}).status_code,200)
        marks = self.events("sheet.save")
        self.assertEqual(len(marks),1)
        self.assertEqual(marks[0]['actor'],"operator")

    def test_recent_is_bounded_shared_and_omits_private_detail(self):
        path = f"/api/cases/{self.item['case_id']}/activity"
        with self.store.connect(write=True) as db:
            for revision in range(25):
                self.store.audit(db,"operator",self.item['case_id'],"survey.save",{"revision":revision+1,"password":"synthetic-secret","participant":"synthetic-private"})
        reader = self.client_for("reviewer")
        first = reader.get(path).json()
        self.assertEqual(len(first['items']),20)
        self.assertEqual(first['next_offset'],20)
        self.assertEqual(first['items'][0]['revision'],25)
        for username in ("operator","admin","developer"):
            self.assertEqual(self.client_for(username).get(path).json(),first)
        with self.store.connect(write=True) as db:
            self.store.audit(db,"reviewer",self.item['case_id'],"case.open",{"revision":26})
        second = reader.get(path+f"?offset=20&before={first['before']}").json()
        self.assertFalse({row['change_id'] for row in first['items']} & {row['change_id'] for row in second['items']})
        self.assertEqual(second['items'][0]['revision'], 5)
        self.assertNotIn('synthetic-secret',json.dumps(first))
        self.assertNotIn('synthetic-private',json.dumps(first))
        self.assertEqual(reader.get(path+'?offset=-1').status_code,422)
        self.assertEqual(self.client_for().get(path).status_code,401)

    def test_recording_open_pins_the_actual_input_revision_and_session(self):
        path = self.base + '/recording-s1?purpose=open'
        opened = self.client_for('reviewer').get(path)
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.json()['input_revision'], self.item['input_revision'])
        detail = json.loads(self.events('recording.open')[0]['detail_json'])
        self.assertEqual(detail['revision'], self.item['input_revision'])
        self.assertEqual(detail['session_id'], self.item['selected_session_id'])
