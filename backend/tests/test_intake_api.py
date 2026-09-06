"""M1 integration checks use synthetic bytes, never claim media/AI validation."""

from io import BytesIO
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from openpyxl import Workbook

from app.api import create_app
from app.auth import create_user
from app.input_models import UserCreate
from app.intake import headers
from app.storage import REPO_ROOT, Store


PASSWORD = "Synthetic-password-only-42"
ORIGIN = "http://127.0.0.1:8000"


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-test-")
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.store = self.app.state.store
        with self.store.connect(write=True) as db:
            for role in ("admin", "operator", "reviewer", "developer"):
                create_user(db, UserCreate(username=role, password=PASSWORD, role=role))
        self.client = self.client_for("operator")
        self.version = self.client.get("/api/catalog/survey").json()["version"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def client_for(self, role=None):
        client = TestClient(self.app, base_url=ORIGIN, headers={"X-KDOG-Request": "1"})
        self.addCleanup(client.close)
        if role:
            result = client.post("/api/auth/login", json={"username": role, "password": PASSWORD})
            self.assertEqual(result.status_code, 200, result.text)
        return client

    def make_case(self, participant_id="0001", event_id="TEST", dog_name="가상견"):
        response = self.client.post("/api/cases", json={"participant_id": participant_id,
                                    "event_id": event_id, "dog_name": dog_name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def get_case(self, item):
        return self.client.get(f"/api/cases/{item['case_id']}").json()

    def delete_case(self, item):
        response = self.client.post(f"/api/cases/{item['case_id']}/deletion", json={
            "expected_revision": item["input_revision"],
        })
        self.assertEqual(response.status_code, 200, response.text)

    def upload(self, item, data=b"synthetic-video-one", camera="CAM-1", name="source.mp4"):
        return self.client.post(f"/api/cases/{item['case_id']}/videos", content=data, params={
            "session_id": item["selected_session_id"], "camera_id": camera,
            "filename": name, "expected_revision": item["input_revision"],
        })

    def answers(self, item, value=3):
        return {"expected_revision": item["input_revision"], "session_id": item["selected_session_id"],
                "survey_version": self.version, "answers": {f"q{i:02}": value for i in range(1, 31)}}

    def test_m1_restart_preserves_one_case_two_files_and_survey(self):
        item = self.make_case()
        with tempfile.TemporaryDirectory(prefix="kdog-source-") as source_dir:
            for i in range(1, 3):
                source = Path(source_dir) / f"camera{i}.mp4"
                source.write_bytes(f"synthetic camera {i}".encode())
                response = self.upload(item, source.read_bytes(), f"CAM-{i}", source.name)
                self.assertEqual(response.status_code, 201, response.text)
                item = response.json()
        payload = self.answers(item)
        payload["answers"]["q23"] = 5
        payload["answers"]["q02"] = None
        response = self.client.put(f"/api/cases/{item['case_id']}/survey", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.client.close()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        restored = self.get_case(item)
        self.assertEqual(restored, saved)
        self.assertEqual(restored["participant_id"], "0001")
        session = restored["manifest"]["sessions"][0]
        self.assertEqual((session["survey"]["q23"], session["survey"]["q02"]), (5, None))
        self.assertEqual(len(session["videos"]), 2)
        for video in session["videos"]:
            response = self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), video["sha256"])
            self.assertEqual(video["media_status"], "pending_probe")

    def test_ids_duplicate_names_and_cross_case_video_access(self):
        first = self.make_case()
        second = self.make_case("0002")
        self.make_case("0001", "OTHER")
        self.assertEqual(self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": "0001", "dog_name": "다른견"}).status_code, 409)
        self.assertEqual(self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": 1, "dog_name": "다른견"}).status_code, 422)
        uploaded = self.upload(first).json()
        video = uploaded["manifest"]["sessions"][0]["videos"][0]
        self.assertEqual(self.client.get(f"/api/cases/{second['case_id']}/videos/{video['video_id']}").status_code, 404)

    def test_retake_and_old_revision_are_isolated(self):
        first = self.make_case()
        first = self.upload(first).json()
        with self.store.connect() as db:
            row = self.store.case(db, first["case_id"])
            old_path = self.store.path(row["manifest_ref"])
            old_bytes = old_path.read_bytes()
        second = self.client.post(f"/api/cases/{first['case_id']}/sessions", json={
            "expected_revision": first["input_revision"], "capture_mode": "sequential", "route_note": "가상 재촬영",
        }).json()
        self.assertNotEqual(first["selected_session_id"], second["selected_session_id"])
        self.assertEqual(len(second["manifest"]["sessions"][0]["videos"]), 1)
        self.assertEqual(second["manifest"]["sessions"][1]["videos"], [])
        self.assertEqual(self.upload(first).status_code, 409)
        stale_session = self.answers(second)
        stale_session["session_id"] = first["selected_session_id"]
        self.assertEqual(self.client.put(f"/api/cases/{first['case_id']}/survey", json=stale_session).status_code, 409)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertIsNone(second["manifest"]["display_run_id"])

    def test_survey_strict_validation_and_idempotent_save(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}/survey"
        for invalid in (0, 6, True, "3", 3.5):
            payload = self.answers(item)
            payload["answers"]["q23"] = invalid
            self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.answers(item)
        payload["answers"].pop("q30")
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.answers(item)
        payload["answers"]["q31"] = 4
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.answers(item)
        payload["survey_version"] = "invented"
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        saved = self.client.put(path, json=self.answers(item)).json()
        again = self.client.put(path, json=self.answers(saved)).json()
        self.assertEqual(saved, again)

    def test_auth_roles_csrf_host_and_revocation(self):
        anonymous = self.client_for()
        self.assertEqual(anonymous.get("/api/cases").status_code, 401)
        self.assertEqual(anonymous.post("/api/auth/login", headers={"X-KDOG-Request": ""}, json={"username": "operator", "password": PASSWORD}).status_code, 403)
        self.assertEqual(self.client.get("/api/cases", headers={"Host": "evil.test"}).status_code, 400)
        self.assertEqual(self.client.post("/api/cases", headers={"Origin": "https://evil.test"}, json={}).status_code, 403)
        admin = self.client_for("admin")
        reviewer = self.client_for("reviewer")
        developer = self.client_for("developer")
        for client in (self.client, reviewer, admin):
            self.assertEqual(client.get("/api/developer/status").status_code, 403)
        self.assertEqual(developer.get("/api/developer/status").status_code, 200)
        self.assertEqual(developer.get("/api/cases").status_code, 403)
        self.assertEqual(reviewer.post("/api/cases", json={}).status_code, 403)
        self.assertEqual(admin.post("/api/admin/users", json={"username": "escalation", "password": PASSWORD, "role": "developer"}).status_code, 403)
        self.assertEqual(admin.patch("/api/admin/users/admin", json={"role": "developer", "active": True}).status_code, 403)
        self.assertEqual(admin.patch("/api/admin/users/operator", json={"role": "reviewer", "active": True}).status_code, 200)
        self.assertEqual(self.client.get("/api/cases").status_code, 401)
        self.assertEqual(admin.patch("/api/admin/users/reviewer", json={"role": "reviewer", "active": False}).status_code, 200)
        self.assertEqual(reviewer.get("/api/cases").status_code, 401)

    def test_cookie_password_audit_and_login_lock(self):
        self.make_case()
        client = self.client_for()
        response = client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertNotIn(PASSWORD, response.text)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username='operator'").fetchone()
            self.assertNotIn(PASSWORD, row["password_hash"])
            self.assertNotEqual(row["session_hash"], client.cookies["kdog_session"])
            self.assertNotIn(PASSWORD, json.dumps([dict(r) for r in db.execute("SELECT * FROM changes")]))
        for _ in range(5):
            self.assertEqual(client.post("/api/auth/login", json={"username": "operator", "password": "wrong"}).status_code, 401)
        self.assertEqual(client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD}).status_code, 401)
        invalid = client.post("/api/auth/login", json={"username": "operator", "password": {"secret": PASSWORD}})
        self.assertNotIn(PASSWORD, invalid.text)

    def test_registration_without_consent_and_deletion_block_files_after_restart(self):
        item = self.make_case()
        self.assertNotIn("consent", item)
        item = self.upload(item).json()
        video = item["manifest"]["sessions"][0]["videos"][0]
        path = f"/api/cases/{item['case_id']}/videos/{video['video_id']}"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.delete_case(item)
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.upload(item).status_code, 403)
        self.assertEqual(self.client.get("/api/cases").json(), [])
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 403)

    def test_upload_rechecks_deletion_at_commit(self):
        item = self.make_case()
        def body():
            yield b"synthetic prefix"
            self.delete_case(item)
            yield b"synthetic suffix"
        self.assertEqual(self.upload(item, body()).status_code, 403)
        self.assertEqual(list((self.root / "videos").iterdir()), [])

    def test_deletion_requires_writer_current_revision_and_has_no_consent_contract(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}/deletion"
        for role in ("reviewer", "developer"):
            self.assertEqual(self.client_for(role).post(path, json={"expected_revision": 1}).status_code, 403)
        self.assertEqual(self.client.post(path, json={"expected_revision": 2}).status_code, 409)
        self.assertEqual(self.client.post(path, json={"expected_revision": 1, "consent": {}}).status_code, 422)
        schema = self.app.openapi()
        self.assertNotIn("Consent", schema["components"]["schemas"])
        self.assertNotIn("/api/cases/{case_id}/access", schema["paths"])
        self.assertNotIn("consent", schema["components"]["schemas"]["CaseView"]["properties"])
        self.delete_case(item)
        self.assertEqual(self.client.post(path, json={"expected_revision": 1}).status_code, 403)

    def test_legacy_migration_removes_consent_preserves_inputs_and_rolls_back_on_failure(self):
        items = [self.make_case(participant_id=f"{i:04}") for i in range(3)]
        with self.store.connect(write=True) as db:
            before = [dict(row) for row in db.execute("SELECT * FROM cases ORDER BY participant_id")]
            db.execute("ALTER TABLE cases ADD COLUMN consent_json TEXT")
            for index, (item, value) in enumerate(zip(items, (None, {"video_analysis": False}, {"video_analysis": True}))):
                db.execute("UPDATE cases SET consent_json=? WHERE case_id=?", (json.dumps(value) if value else None, item["case_id"]))
                self.store.audit(db, "operator", item["case_id"], "access.state", {"consent": value, "deletion_requested": index == 2})
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (items[2]["case_id"],))
            db.execute("PRAGMA user_version=2")
            db.execute("CREATE TRIGGER fail_migration BEFORE UPDATE ON changes BEGIN SELECT RAISE(ABORT,'synthetic migration failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            Store(self.root)
        with self.store.connect(write=True) as db:
            self.assertIn("consent_json", {r[1] for r in db.execute("PRAGMA table_info(cases)")})
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            db.execute("DROP TRIGGER fail_migration")
        for _ in range(2):
            migrated = Store(self.root)
            with migrated.connect() as db:
                self.assertNotIn("consent_json", {r[1] for r in db.execute("PRAGMA table_info(cases)")})
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                after = [dict(row) for row in db.execute("SELECT * FROM cases ORDER BY participant_id")]
                before[2]["deletion_requested"] = 1
                self.assertEqual(after, before)
                details = [json.loads(r[0]) for r in db.execute("SELECT detail_json FROM changes WHERE action='access.state'")]
                self.assertEqual(details, [{"deletion_requested": i == 2} for i in range(3)])
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            for item in items[:2]:
                self.assertNotIn("consent", self.get_case(item))
            self.assertEqual(self.client.get(f"/api/cases/{items[2]['case_id']}").status_code, 403)
        for item in items[:2]:
            self.assertEqual(self.upload(item).status_code, 201)

    def test_empty_duplicate_and_failed_upload_never_register(self):
        item = self.make_case()
        self.assertEqual(self.upload(item, b"").status_code, 422)
        self.assertEqual(self.upload(item, name="bad.html").status_code, 422)
        item = self.upload(item, name="../../source.mp4").json()
        self.assertEqual(self.upload(item).status_code, 409)
        self.assertEqual(len(list((self.root / "videos").iterdir())), 1)
        with patch.object(self.store, "save", side_effect=OSError("synthetic full disk")):
            response = self.upload(item, data=b"new file")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(list((self.root / "videos").iterdir())), 1)
        self.assertEqual(self.get_case(item), item)

    def test_import_preview_errors_normal_rows_and_stale_commit(self):
        data = b"event_id,participant_id,dog_name,reservation_at\nTEST,0001,Synthetic,\nTEST,0001,Duplicate,\nTEST,0002,Other,\n"
        result = self.client.post("/api/imports/preview?kind=participants&format=csv", content=data).json()
        self.assertEqual(len(result["rows"]), 2)
        self.assertIn("3행", result["errors"][0])
        response = self.client.post("/api/imports/commit", json={"rows": result["rows"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.client.get("/api/cases").json()), 2)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 409)
        columns = headers("survey")
        data = (",".join(reversed(columns)) + "\n" + ",".join(reversed(["TEST", "0001", self.version, *(["5"] * 30)])) + "\n").encode()
        result = self.client.post("/api/imports/preview?kind=survey&format=csv", content=data).json()
        self.assertEqual(result["errors"], [])
        row = result["rows"][0]
        item = self.client.get(f"/api/cases/{row['case_id']}").json()
        self.client.put(f"/api/cases/{row['case_id']}/survey", json=self.answers(item))
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 409)

    def test_xlsx_numeric_ids_formulas_and_bad_headers(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers("participants"))
        sheet.append(["TEST", 1, "숫자 ID", None])
        sheet.append(["TEST", "0002", "텍스트 ID", None])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        result = self.client.post("/api/imports/preview?kind=participants&format=xlsx", content=output.getvalue()).json()
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["participant"]["participant_id"], "0002")
        self.assertIn("participant_id", result["errors"][0])
        self.make_case()
        for raw in ("=1+1", "6", "True"):
            data = (",".join(headers("survey")) + "\n" + ",".join(["TEST", "0001", self.version, raw, *([""] * 29)])).encode()
            result = self.client.post("/api/imports/preview?kind=survey&format=csv", content=data).json()
            self.assertIn("q01", result["errors"][0])
        self.assertEqual(self.client.post("/api/imports/preview?kind=survey&format=csv", content=b"q31\n1").status_code, 422)
        for format in ("csv", "xlsx"):
            self.assertEqual(self.client.get(f"/api/templates/survey?format={format}").status_code, 200)

    def test_five_tables_foreign_keys_immutable_runs_and_storage_integrity(self):
        item = self.make_case()
        with self.store.connect(write=True) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {"users", "cases", "runs", "steps", "changes"})
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,"
                       "config_snapshot_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       ("run-1", item["case_id"], item["selected_session_id"], 1, "{}", "{}", "queued", "now", "now"))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE runs SET input_snapshot_json='changed' WHERE run_id='run-1'")
            row = self.store.case(db, item["case_id"])
            path = self.store.path(row["manifest_ref"])
        path.write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}").status_code, 409)
        with self.assertRaises(ValueError):
            Store(REPO_ROOT / "runtime")
        with self.assertRaises(ValueError):
            create_app(self.root, public_origin="http://192.168.0.1:8000")

    def test_standard_import_more_than_twenty_and_atomic_conflict(self):
        text = ",".join(headers("participants")) + "\n"
        text += "\n".join(f"TEST,{i:04},Synthetic-{i}," for i in range(1, 22))
        result = self.client.post("/api/imports/preview?kind=participants&format=csv", content=text.encode()).json()
        self.assertEqual(len(result["rows"]), 21)
        self.make_case("0021")
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 409)
        self.assertEqual(len(self.client.get("/api/cases").json()), 1)
        result = self.client.post("/api/imports/preview?kind=participants&format=csv", content=text.encode()).json()
        self.assertEqual(len(result["rows"]), 20)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 200)
        self.assertEqual(len(self.client.get("/api/cases").json()), 21)

    def test_video_same_size_corruption_and_session_metadata(self):
        item = self.make_case()
        response = self.client.put(f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}", json={
            "expected_revision": item["input_revision"], "capture_mode": "simultaneous", "route_note": "가상 동선 기록",
        })
        self.assertEqual(response.status_code, 200)
        item = self.upload(response.json()).json()
        session = item["manifest"]["sessions"][0]
        self.assertEqual(session["capture_mode"], "simultaneous")
        video = session["videos"][0]
        self.store.path(video["storage_ref"]).write_bytes(b"X" * video["size_bytes"])
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}").status_code, 409)

    def test_server_process_restart_restores_registered_inputs(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]

        @contextmanager
        def server():
            process = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(self.root),
                 "serve", "--port", str(port)], cwd=REPO_ROOT / "backend",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"X-KDOG-Request": "1"})
            try:
                for _ in range(100):
                    try:
                        client.get("/api/auth/me")
                        break
                    except httpx.ConnectError:
                        if process.poll() is not None:
                            self.fail("server exited before accepting connections")
                        time.sleep(0.05)
                else:
                    self.fail("server startup timed out")
                response = client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
                self.assertEqual(response.status_code, 200, response.text)
                yield client
            finally:
                client.close()
                process.terminate()
                process.wait(timeout=10)

        old_client = self.client
        try:
            with server() as client:
                self.client = client
                item = self.make_case()
                for camera in (1, 2):
                    response = self.upload(item, f"process synthetic {camera}".encode(), f"CAM-{camera}")
                    self.assertEqual(response.status_code, 201, response.text)
                    item = response.json()
                response = self.client.put(f"/api/cases/{item['case_id']}/survey", json=self.answers(item, 4))
                self.assertEqual(response.status_code, 200, response.text)
                saved = response.json()
            with server() as client:
                self.client = client
                self.assertEqual(self.get_case(saved), saved)
                for video in saved["manifest"]["sessions"][0]["videos"]:
                    response = client.get(f"/api/cases/{saved['case_id']}/videos/{video['video_id']}")
                    self.assertEqual(hashlib.sha256(response.content).hexdigest(), video["sha256"])
        finally:
            self.client = old_client


if __name__ == "__main__":
    unittest.main()
