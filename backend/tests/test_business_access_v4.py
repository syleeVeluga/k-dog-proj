"""AR01: active accounts share business access; developer settings remain protected."""

import json

from app.api import create_app
from tests.support import AppCase, PASSWORD, ROLES
from tests import test_sheets_api_v4 as sheet_fixture


class BusinessAccessV4Tests(AppCase):
    def test_all_accounts_register_edit_upload_and_reach_business_modules(self):
        for role in ROLES:
            with self.subTest(role=role):
                client = self.client_for(role)
                response = client.post("/api/cases", json={"event_id": "ACCESS", "participant_id": role, "dog_name": "합성견"})
                self.assertEqual(response.status_code, 201, response.text)
                item = response.json()
                path = f"/api/cases/{item['case_id']}"
                response = client.put(path, json={"expected_revision": item["input_revision"], "participant_id": role,
                    "dog_name": "정정 합성견", "consents": {"analysis_feedback": "confirmed"}})
                self.assertEqual(response.status_code, 200, response.text)
                item = response.json()
                response = client.post(path + "/videos", params={"session_id": item["selected_session_id"],
                    "expected_revision": item["input_revision"], "filename": "synthetic.mp4"}, content=b"synthetic video")
                self.assertEqual(response.status_code, 201, response.text)
                item = response.json()
                base = path + f"/sessions/{item['selected_session_id']}"
                for endpoint in (path, base + "/recording-s1", base + "/sheets-s1", base + "/runs-s1",
                        base + "/report-runs-s1", "/api/admin/users", "/api/admin/recovery", "/api/comparisons-s1/sources"):
                    result = client.get(endpoint)
                    self.assertEqual(result.status_code, 200, (role, endpoint, result.text))
                for endpoint in (base + "/runs-s1", base + "/report-runs-s1"):
                    self.assertEqual(client.post(endpoint, json={}).status_code, 422)
                video = item["manifest"]["sessions"][0]["videos"][0]
                self.assertEqual(client.get(path + f"/videos/{video['video_id']}").content, b"synthetic video")
                receipt = client.post("/api/uploads", json={"request_id": role, "filename": "received.mp4", "expected_size": 3})
                self.assertEqual(receipt.status_code, 201, receipt.text)
                self.assertEqual(client.put(f"/api/uploads/{receipt.json()['upload_id']}/content?request_id={role}", content=b"raw").status_code, 200)
                self.assertEqual(client.post("/api/admin/backups").status_code, 201)

    def test_every_account_can_create_normal_accounts_but_never_developers(self):
        for role in ROLES:
            with self.subTest(role=role):
                client = self.client_for(role)
                name = "created_" + role
                response = client.post("/api/admin/users", json={"username": name, "password": PASSWORD, "role": "admin"})
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["role"], "operator")
                self.assertEqual(self.client_for(name).get("/api/cases").status_code, 200)
                response = client.patch(f"/api/admin/users/{name}", json={"active": False})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["role"], "operator")
                self.assertEqual(client.post("/api/admin/users", json={"username": "escalate_" + role,
                    "password": PASSWORD, "role": "developer"}).status_code, 403)
                for username in (name, "developer"):
                    self.assertEqual(client.patch(f"/api/admin/users/{username}", json={"role": "developer", "active": True}).status_code, 403)
                self.assertEqual(client.patch(f"/api/admin/users/{role}", json={"active": False}).status_code, 403)
        with self.store.connect() as db:
            records = db.execute("SELECT actor,target,detail_json FROM changes WHERE action='user.create'").fetchall()
        self.assertEqual({row["actor"] for row in records}, set(ROLES))
        self.assertTrue(all(json.loads(row["detail_json"]) == {"role": "operator"} for row in records))
        self.assertNotIn(PASSWORD, json.dumps([dict(row) for row in records]))

    def test_legacy_roles_and_passwords_survive_active_updates_and_restart(self):
        with self.store.connect() as db:
            originals = {row["username"]: (row["role"], row["password_hash"]) for row in db.execute("SELECT * FROM users")}
        for role in ("reviewer", "admin"):
            result = self.client.patch(f"/api/admin/users/{role}", json={"role": "operator", "active": True})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["role"], role)
        self.app = create_app(self.root)
        for role in ROLES:
            self.assertEqual(self.client_for(role).get("/api/admin/users").status_code, 200)
        with self.store.connect() as db:
            self.assertEqual(originals, {row["username"]: (row["role"], row["password_hash"]) for row in db.execute("SELECT * FROM users")})

    def test_settings_and_authentication_boundaries(self):
        for role in ROLES:
            client = self.client_for(role)
            for path in ("/api/developer/settings", "/api/settings-s1"):
                self.assertEqual(client.get(path).status_code, 200 if role == "developer" else 403)
        anonymous = self.client_for()
        for path in ("/api/cases", "/api/admin/users", "/api/admin/recovery", "/api/settings-s1"):
            self.assertEqual(anonymous.get(path).status_code, 401)
        client = self.client_for("reviewer")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET session_expires=0 WHERE username='reviewer'")
        self.assertEqual(client.get("/api/cases").status_code, 401)
        client = self.client_for("admin")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='admin'")
        self.assertEqual(client.get("/api/admin/users").status_code, 401)


class ScoringBusinessAccessV4Tests(sheet_fixture.SheetsApiV4Tests):
    test_independent_owner_submit_reopen_history_and_strict_values_over_http = None
    test_nonowners_cannot_bypass_assignment_through_history_or_mutations = None

    def test_each_account_can_assign_and_edit_its_sheet(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.client = self.client_for(role)
                sheet = self.assign(role)
                path = f"/api/score-sheets-s1/{sheet['sheet_id']}"
                self.assertEqual(self.client.get(path).status_code, 200)
                result = self.client.put(path, json={"expected_revision": 1, "observations": []})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["revision"], 2)
                with self.store.connect() as db:
                    event = db.execute("SELECT actor FROM changes WHERE target=? AND action='sheet.save' ORDER BY rowid DESC LIMIT 1", (self.item["case_id"],)).fetchone()
                self.assertEqual(event["actor"], role)
