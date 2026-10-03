"""API transport/restart and shared-store S1 receipt integration."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import create_app
from app import uploads
from app.maintenance import clean, references
from app.storage import Store
from tests.support import AppCase, ORIGIN


class UploadApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")

    def receive(self, number, content, **extra):
        response = self.client.post("/api/uploads", json={"request_id": f"request-{number}",
            "filename": f"synthetic-{number}.mp4", "expected_size": len(content), **extra})
        self.assertEqual(response.status_code, 201, response.text)
        receipt = response.json()
        response = self.client.put(f"/api/uploads/{receipt['upload_id']}/content", params={"request_id": receipt["request_id"]}, content=content)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def link(self, receipt, item, camera="CAM1"):
        return self.client.post(f"/api/uploads/{receipt['upload_id']}/link", json={"case_id": item["case_id"],
            "session_id": item["selected_session_id"], "expected_revision": item["input_revision"], "camera_id": camera})

    def test_three_parallel_uploads_link_after_conflict_without_retransmission(self):
        item = self.make_case()
        with ThreadPoolExecutor(max_workers=3) as pool:
            receipts = list(pool.map(lambda n: self.receive(n, f"synthetic camera {n}".encode()), range(3)))
            linked = list(pool.map(lambda pair: self.link(pair[1], item, f"CAM{pair[0] + 1}"), enumerate(receipts)))
        self.assertEqual(sorted(response.status_code for response in linked), [200, 409, 409])
        for index, (receipt, response) in enumerate(zip(receipts, linked)):
            if response.status_code == 409:
                status = self.client.get(f"/api/uploads/{receipt['upload_id']}").json()
                self.assertEqual(status["state"], "complete")
                response = self.link(receipt, self.get_case(item), f"CAM{index + 1}")
                self.assertEqual(response.status_code, 200, response.text)
            repeated = self.link(receipt, self.get_case(item), f"CAM{index + 1}")
            self.assertEqual(repeated.status_code, 200, repeated.text)
        videos = self.get_case(item)["manifest"]["sessions"][0]["videos"]
        self.assertEqual(len(videos), 3)
        self.assertEqual({v["camera_id"]: v["source_original_number"] for v in videos}, {"CAM1": "1", "CAM2": "3", "CAM3": "2"})
        self.assertTrue(all(v["upload_id"] for v in videos))
        for i, receipt in enumerate(receipts):
            response = self.client.get(f"/api/uploads/{receipt['upload_id']}/content")
            self.assertEqual(response.content, f"synthetic camera {i}".encode())

    def test_receipt_roles_and_complete_insv_remain_storage_only(self):
        receipt = self.receive(1, b"synthetic INSV", filename="source.insv")
        self.assertFalse(receipt["analysis_ready"])
        self.assertEqual(receipt["media_status"], "storage_only")
        for role, status in ((None, 401), ("reviewer", 403), ("developer", 403)):
            client = self.client_for(role)
            for path in ("/api/uploads", f"/api/uploads/{receipt['upload_id']}/content"):
                self.assertEqual(client.get(path).status_code, status)
        self.assertEqual(self.client.get(f"/api/uploads/{receipt['upload_id']}/content").headers["Cache-Control"], "no-store")

    def test_only_api_startup_recovers_interrupted_writer_and_reuses_receipt(self):
        payload = {"request_id": "restart-request", "filename": "source.mp4", "expected_size": 8}
        response = self.client.post("/api/uploads", json=payload)
        receipt = response.json()
        writer = uploads.begin_receive(self.store, receipt["upload_id"], receipt["request_id"], "operator")
        uploads.write_chunk(writer, b"partial")
        writer.handle.close(); writer.handle = None
        Store(self.root)
        self.assertEqual(self.client.get(f"/api/uploads/{receipt['upload_id']}").json()["state"], "receiving")
        with TestClient(self.app, base_url=ORIGIN, headers={"X-KDOG-Request": "1"}, cookies=self.client.cookies) as restarted:
            self.assertEqual(restarted.get(f"/api/uploads/{receipt['upload_id']}").json()["failure_code"], "server_interrupted")
            response = restarted.put(f"/api/uploads/{receipt['upload_id']}/content", params={"request_id": receipt["request_id"]}, content=b"complete")
            self.assertEqual(response.status_code, 200, response.text)
        clean(self.store)
        self.assertFalse(self.store.path(writer.temp_ref).exists())

    def test_preserved_video_rechecks_consent_and_login_after_hashing(self):
        item = self.make_case()
        item = self.upload(item, b"preserved synthetic source").json()
        video = item["manifest"]["sessions"][0]["videos"][0]
        path = f"/api/cases/{item['case_id']}/videos/{video['video_id']}"
        real_digest = hashlib.file_digest

        def decline(handle, algorithm):
            result = real_digest(handle, algorithm)
            with self.store.connect(write=True) as db:
                row = self.store.case(db, item["case_id"])
                manifest = self.store.manifest(row)
                manifest.consents.analysis_feedback = "declined"
                self.store.save(db, row, manifest, "admin", "case.consent")
            return result

        with patch("app.api.hashlib.file_digest", side_effect=decline):
            self.assertEqual(self.client.get(path).status_code, 403)
        with self.store.connect(write=True) as db:
            row = self.store.case(db, item["case_id"])
            manifest = self.store.manifest(row)
            manifest.consents.analysis_feedback = "confirmed"
            self.store.save(db, row, manifest, "admin", "case.consent")

        def revoke(handle, algorithm):
            result = real_digest(handle, algorithm)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
            return result

        with patch("app.api.hashlib.file_digest", side_effect=revoke):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_conversion_raw_settings_are_not_backup_links_and_deletion_purges_descendants(self):
        item = self.make_case()
        parent = self.receive(1, b"parent source", filename="parent.insv")
        self.assertEqual(self.link(parent, item).status_code, 200)
        parent = self.client.get(f"/api/uploads/{parent['upload_id']}").json()
        child = self.receive(2, b"converted mp4", source_kind="received_conversion",
            parents=[{"upload_id": parent["upload_id"], "sha256": parent["sha256"], "video_id": parent["video_id"]}],
            conversion={"tool": "synthetic", "tool_version": "1", "settings": {"ref": "raw-not-a-path", "options_json": "raw-not-json"}})
        response = self.link(child, self.get_case(item))
        self.assertEqual(response.status_code, 200, response.text)
        linked = response.json()
        reviewer = self.client_for("reviewer")
        video_path = f"/api/cases/{item['case_id']}/videos/{linked['video_id']}"
        self.assertEqual(reviewer.get(video_path).content, b"converted mp4")
        with self.store.connect() as db:
            refs = references(self.store, db)
        self.assertTrue(any(digest == hashlib.sha256(b"converted mp4").hexdigest() for digest in refs.values()))
        self.delete_case(self.get_case(item))
        self.assertEqual(self.client.get(f"/api/uploads/{child['upload_id']}/content").status_code, 403)
        self.assertEqual(reviewer.get(video_path).status_code, 403)
        clean(self.store, purge_deleted=True)
        self.assertEqual(self.client.get("/api/uploads").json(), [])
        self.assertTrue(all(not self.store.path(ref).exists() for ref in refs))
