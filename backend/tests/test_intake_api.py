"""Intake API (intake-2.0): 28-item survey, several video files, session notes, migration from intake-1.0 and the frozen pipeline."""

from io import BytesIO
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from openpyxl import Workbook

from app.analysis import FROZEN, session_snapshot
from app.api import create_app
from app.domain.catalog import SURVEY_IDS
from app.intake import headers
from app.storage import REPO_ROOT, Store
from tests.support import AppCase, PASSWORD


class IntakeTests(AppCase):
    def test_restart_preserves_one_case_several_files_and_survey(self):
        item = self.make_case()
        for index in range(1, 4):
            response = self.upload(item, f"synthetic file {index}".encode(), f"file{index}.mp4")
            self.assertEqual(response.status_code, 201, response.text)
            item = response.json()
        payload = self.answers(item, not_applicable=("s07", "s09"))
        payload["answers"]["s23"] = 5
        payload["answers"]["s02"] = None
        response = self.client.put(f"/api/cases/{item['case_id']}/survey", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.client.close()
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        restored = self.get_case(item)
        self.assertEqual(restored, saved)
        session = restored["manifest"]["sessions"][0]
        self.assertEqual(restored["manifest"]["schema_version"], "intake-2.0")
        self.assertEqual((session["survey"]["s23"], session["survey"]["s02"], session["survey"]["s07"]), (5, None, None))
        self.assertEqual(session["survey_not_applicable"], ["s07", "s09"])
        self.assertEqual(session["survey_version"], "catalog-20260913-v2")
        self.assertEqual(len(session["videos"]), 3)
        for video in session["videos"]:
            response = self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), video["sha256"])

    def test_survey_strict_validation_not_applicable_and_idempotent_save(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}/survey"
        for invalid in (0, 6, True, "3", 3.5):
            payload = self.answers(item)
            payload["answers"]["s23"] = invalid
            self.assertEqual(self.client.put(path, json=payload).status_code, 422, invalid)
        payload = self.answers(item)
        payload["answers"].pop("s28")
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.answers(item)
        payload["answers"]["q01"] = 4
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        payload = self.answers(item)
        payload["survey_version"] = "catalog-20260904-v1"
        self.assertEqual(self.client.put(path, json=payload).status_code, 422)
        # 해당 없음 is a missing value: only items 7-9 offer it, and the answer must stay blank.
        self.assertEqual(self.client.put(path, json=self.answers(item, not_applicable=("s10",))).status_code, 422)
        answered = self.answers(item, not_applicable=("s08",))
        answered["answers"]["s08"] = 3
        self.assertEqual(self.client.put(path, json=answered).status_code, 422)
        duplicate = self.answers(item, not_applicable=("s08",))
        duplicate["not_applicable"] = ["s08", "s08"]
        self.assertEqual(self.client.put(path, json=duplicate).status_code, 422)
        saved = self.client.put(path, json=self.answers(item, not_applicable=("s08",))).json()
        again = self.client.put(path, json=self.answers(saved, not_applicable=("s08",))).json()
        self.assertEqual(saved, again)
        self.assertEqual(saved["manifest"]["sessions"][0]["survey_not_applicable"], ["s08"])

    def test_ids_duplicate_names_and_cross_case_video_access(self):
        first = self.make_case()
        second = self.make_case("0002")
        self.make_case("0001", "OTHER")
        self.assertEqual(self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": "0001", "dog_name": "다른견"}).status_code, 409)
        self.assertEqual(self.client.post("/api/cases", json={"event_id": "TEST", "participant_id": 1, "dog_name": "다른견"}).status_code, 422)
        uploaded = self.upload(first).json()
        video = uploaded["manifest"]["sessions"][0]["videos"][0]
        self.assertEqual(self.client.get(f"/api/cases/{second['case_id']}/videos/{video['video_id']}").status_code, 404)

    def test_retake_session_note_and_old_revision_are_isolated(self):
        first = self.make_case()
        first = self.upload(first).json()
        with self.store.connect() as db:
            row = self.store.case(db, first["case_id"])
            old_path = self.store.path(row["manifest_ref"])
            old_bytes = old_path.read_bytes()
        noted = self.client.put(f"/api/cases/{first['case_id']}/sessions/{first['selected_session_id']}",
                                json={"expected_revision": first["input_revision"], "note": "마이크 늦게 켬"})
        self.assertEqual(noted.status_code, 200, noted.text)
        self.assertEqual(noted.json()["manifest"]["sessions"][0]["note"], "마이크 늦게 켬")
        for stale in ({"capture_mode": "sequential"}, {"checklist": {"entry": "performed"}}, {"route_note": "x"}):
            self.assertEqual(self.client.put(f"/api/cases/{first['case_id']}/sessions/{first['selected_session_id']}",
                                             json={"expected_revision": noted.json()["input_revision"], "note": "", **stale}).status_code, 422)
        second = self.client.post(f"/api/cases/{first['case_id']}/sessions", json={
            "expected_revision": noted.json()["input_revision"], "note": "가상 재촬영",
        }).json()
        self.assertNotEqual(first["selected_session_id"], second["selected_session_id"])
        self.assertEqual(len(second["manifest"]["sessions"][0]["videos"]), 1)
        self.assertEqual(second["manifest"]["sessions"][1]["videos"], [])
        self.assertEqual(second["manifest"]["sessions"][1]["note"], "가상 재촬영")
        self.assertEqual(self.upload(first).status_code, 409)
        stale_session = self.answers(second)
        stale_session["session_id"] = first["selected_session_id"]
        self.assertEqual(self.client.put(f"/api/cases/{first['case_id']}/survey", json=stale_session).status_code, 409)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertIsNone(second["manifest"]["display_run_id"])

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

    def test_deletion_blocks_files_after_restart_and_upload_rechecks_at_commit(self):
        item = self.make_case()
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
        other = self.make_case("0002")

        def body():
            yield b"synthetic prefix"
            self.delete_case(other)
            yield b"synthetic suffix"
        self.assertEqual(self.upload(other, body()).status_code, 403)
        self.assertEqual(len(list((self.root / "videos").iterdir())), 1)

    def test_deletion_requires_writer_and_current_revision(self):
        item = self.make_case()
        path = f"/api/cases/{item['case_id']}/deletion"
        for role in ("reviewer", "developer"):
            self.assertEqual(self.client_for(role).post(path, json={"expected_revision": 1}).status_code, 403)
        self.assertEqual(self.client.post(path, json={"expected_revision": 2}).status_code, 409)
        self.delete_case(item)
        self.assertEqual(self.client.post(path, json={"expected_revision": 1}).status_code, 403)

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

    def test_video_same_size_corruption_detected(self):
        item = self.upload(self.make_case()).json()
        video = item["manifest"]["sessions"][0]["videos"][0]
        self.store.path(video["storage_ref"]).write_bytes(b"X" * video["size_bytes"])
        self.assertEqual(self.client.get(f"/api/cases/{item['case_id']}/videos/{video['video_id']}").status_code, 409)

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
        self.assertEqual(columns[3:], list(SURVEY_IDS))
        values = ["TEST", "0001", self.version, *(["5"] * 6), "NA", "", "해당 없음", *(["4"] * 19)]
        data = (",".join(reversed(columns)) + "\n" + ",".join(reversed(values)) + "\n").encode()
        result = self.client.post("/api/imports/preview?kind=survey&format=csv", content=data).json()
        self.assertEqual(result["errors"], [])
        row = result["rows"][0]
        self.assertEqual(row["survey"]["not_applicable"], ["s07", "s09"])
        self.assertEqual((row["survey"]["answers"]["s07"], row["survey"]["answers"]["s08"], row["survey"]["answers"]["s28"]), (None, None, 4))
        self.assertEqual(len(row["changed_questions"]), 27)
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 200)
        saved = self.client.get(f"/api/cases/{row['case_id']}").json()["manifest"]["sessions"][0]
        self.assertEqual((saved["survey"]["s01"], saved["survey_not_applicable"]), (5, ["s07", "s09"]))
        item = self.client.get(f"/api/cases/{row['case_id']}").json()
        self.client.put(f"/api/cases/{row['case_id']}/survey", json=self.answers(item))
        self.assertEqual(self.client.post("/api/imports/commit", json={"rows": result["rows"]}).status_code, 409)

    def test_xlsx_numeric_ids_formulas_bad_headers_and_misplaced_na(self):
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
        for raw in ("=1+1", "6", "True", "NA"):
            data = (",".join(headers("survey")) + "\n" + ",".join(["TEST", "0001", self.version, raw, *([""] * 27)])).encode()
            result = self.client.post("/api/imports/preview?kind=survey&format=csv", content=data).json()
            self.assertIn("s01", result["errors"][0], raw)
        self.assertEqual(self.client.post("/api/imports/preview?kind=survey&format=csv", content=b"q01\n1").status_code, 422)
        mapped = json.dumps({"columns": {"event_id": "행사", "participant_id": "번호", "dog_name": "이름"}})
        response = self.client.post("/api/imports/preview", params={"kind": "participants", "format": "csv", "mapping": mapped},
                                    content="행사,번호,이름\nMAPPING,0007,가상견\n".encode("utf-8"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rows"][0]["participant_id"], "0007")
        self.assertEqual(self.client.post("/api/imports/preview", params={"kind": "survey", "format": "csv", "mapping": json.dumps({"horizontal": {"F": "x"}})},
                                          content=b"a").status_code, 422)
        for format in ("csv", "xlsx"):
            self.assertEqual(self.client.get(f"/api/templates/survey?format={format}").status_code, 200)

    def test_five_tables_foreign_keys_immutable_runs_and_storage_integrity(self):
        item = self.make_case()
        with self.store.connect(write=True) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {"users", "cases", "runs", "steps", "changes"})
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
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

    def legacy_manifest(self, item, answers):
        return {"schema_version": "intake-1.0", "case_id": item["case_id"], "event_id": item["event_id"],
                "participant_id": item["participant_id"], "input_revision": item["input_revision"],
                "selected_session_id": item["selected_session_id"], "display_run_id": None,
                "sessions": [{"session_id": item["selected_session_id"], "capture_mode": "sequential", "route_note": "옛 동선 메모",
                              "survey_version": "catalog-20260904-v1", "survey": answers,
                              "videos": [{**v, "camera_id": "CAM-1"} for v in item["manifest"]["sessions"][0]["videos"]],
                              "checklist": {"entry": "performed", "training": "skipped"}}]}

    def test_intake_1_0_manifests_migrate_once_and_old_run_snapshots_stay_readable(self):
        item = self.upload(self.make_case()).json()
        answers = {f"q{i:02}": None for i in range(1, 31)}
        answers.update(q01=5, q07=2, q09=4, q13=1, q14=3, q22=2, q25=5, q26=1, q30=4)
        legacy = self.legacy_manifest(item, answers)
        raw = json.dumps(legacy, ensure_ascii=False).encode("utf-8")
        with self.store.connect(write=True) as db:
            row = self.store.case(db, item["case_id"])
            key = f"inputs/{item['case_id']}-legacy.json"
            self.store.path(key).write_bytes(raw)
            db.execute("UPDATE cases SET manifest_ref=?, manifest_hash=? WHERE case_id=?", (key, hashlib.sha256(raw).hexdigest(), item["case_id"]))
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", ("legacy-run", item["case_id"], item["selected_session_id"], row["input_revision"],
                                                    raw.decode("utf-8"), "{}", "scored", "now", "now"))
            db.execute("PRAGMA user_version=4")
        for _ in range(2):
            migrated = Store(self.root)
            with migrated.connect() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
                row = migrated.case(db, item["case_id"])
                manifest = migrated.manifest(row)
                run = db.execute("SELECT * FROM runs WHERE run_id='legacy-run'").fetchone()
            self.assertEqual(row["input_revision"], item["input_revision"] + 1)
            session = manifest.sessions[0]
            self.assertEqual((session.survey["s01"], session.survey["s10"], session.survey["s14"], session.survey["s22"], session.survey["s26"]), (5, 4, 1, 2, 1))
            self.assertIsNone(session.survey["s07"])  # new item without an old counterpart stays blank
            self.assertEqual(session.survey_not_applicable, [])
            self.assertEqual(session.survey_version, "catalog-20260913-v2")
            self.assertEqual(session.note, "옛 동선 메모 · 순차 촬영")
            self.assertEqual(len(session.videos), 1)
            self.assertEqual(session.videos[0].original_name, "source.mp4")
            self.assertIn("q07", manifest.migration_note)
            self.assertIn("q25", manifest.migration_note)
            self.assertIn("q30", manifest.migration_note)
            self.assertNotIn("q13", manifest.migration_note)
            self.assertEqual(json.loads(run["input_snapshot_json"]), legacy)
            _, old_session = session_snapshot(run)
            self.assertEqual(old_session.survey["q25"], 5)
            self.assertEqual(old_session.checklist["entry"], "performed")
        self.assertTrue(self.store.path(key).exists())
        self.app = create_app(self.root)
        self.client = self.client_for("operator")
        view = self.get_case(item)
        self.assertEqual(view["manifest"]["schema_version"], "intake-2.0")
        self.assertEqual(self.client.put(f"/api/cases/{item['case_id']}/survey", json=self.answers(view)).status_code, 200)

    def test_frozen_pipeline_refuses_new_runs_exports_and_reports_but_keeps_reads(self):
        item = self.upload(self.make_case()).json()
        base = f"/api/cases/{item['case_id']}"
        response = self.client.post(f"{base}/analysis", json={"expected_revision": item["input_revision"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], FROZEN)
        self.assertEqual(self.client.post("/api/exports", json={"format": "xlsx", "case_id": item["case_id"]}).status_code, 409)
        self.assertEqual(self.client.post("/api/exports/preview", json={"format": "xlsx", "case_id": item["case_id"]}).status_code, 409)
        self.assertEqual(self.client.get(f"{base}/analysis").json()["runs"], [])
        self.assertEqual(self.client.get("/api/exports").json(), [])
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", ("old-run", item["case_id"], item["selected_session_id"], 1, "{}", "{}", "failed", "now", "now"))
        self.assertEqual(self.client.post(f"{base}/analysis/old-run/retry").status_code, 409)
        self.assertEqual(self.client.post(f"{base}/reports/old-run/generate").status_code, 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

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
                for index in (1, 2):
                    response = self.upload(item, f"process synthetic {index}".encode(), f"process{index}.mp4")
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
    import unittest
    unittest.main()
