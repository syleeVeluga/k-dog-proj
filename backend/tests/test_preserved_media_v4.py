import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import uploads
from app.domain.catalog_v4 import SURVEY_VERSION
from app.domain.media_v4 import ConversionV4, MediaParentV4, PreservedMediaRegistrationV4, StoredMediaV4
from app.input_models import StoredVideo
from app.input_models_v3 import CaseCreateV3
from app.input_models_v4 import new_session_v4
from app.intake import create_case
from app.storage import Store


class PreservedMediaV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-preserved-test-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "store")
        with self.store.connect(write=True) as db:
            for user, role in (("op", "operator"), ("admin", "admin"), ("review", "reviewer")):
                db.execute("INSERT INTO users(username,password_hash,role,session_hash) VALUES(?,?,?,?)",
                           (user, "synthetic-no-login", role, "synthetic-session-" + user))
            self.case_id = create_case(self.store, db, CaseCreateV3(event_id="SYNTHETIC", participant_id="001",
                                      dog_name="합성견"), "op", SURVEY_VERSION)
            self.session_id = self.store.case(db, self.case_id)["selected_session_id"]

    def preserved(self, name="preserved.mp4", video_id="preserved", data=b"synthetic-video"):
        ref = f"synthetic/{video_id}{Path(name).suffix}"
        path = self.store.path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        video = StoredVideo(video_id=video_id, original_name=name, storage_ref=ref,
                            sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id)
            manifest = self.store.manifest(case)
            manifest.sessions[0].videos.append(video)
            self.store.save(db, case, manifest, "op", "synthetic.preserve")
        return video

    def revision(self):
        with self.store.connect() as db:
            return self.store.case(db, self.case_id)["input_revision"]

    def request(self, **changes):
        return PreservedMediaRegistrationV4(**{"request_id": "register-1", "expected_revision": self.revision(),
            "camera_id": "CAM2", "source_kind": "original", **changes})

    def register(self, video, request=None, actor="op"):
        return uploads.register_preserved_video(self.store, self.case_id, self.session_id, video.video_id,
                                               request or self.request(), actor)

    def count(self):
        with self.store.connect() as db:
            return db.execute("SELECT COUNT(*) FROM upload_receipts").fetchone()[0]

    def test_preserves_bytes_path_identifier_and_creates_linked_receipt(self):
        video = self.preserved()
        before, data = self.revision(), self.store.path(video.storage_ref).read_bytes()
        receipt = self.register(video)
        with self.store.connect() as db:
            registered = self.store.manifest(self.store.case(db, self.case_id)).sessions[0].videos[0]
            self.assertIn(video.storage_ref, uploads.references(db))
            fixed = db.execute("SELECT request_json,request_hash FROM upload_receipts WHERE upload_id=?", (receipt.upload_id,)).fetchone()
            self.assertEqual(hashlib.sha256(fixed["request_json"].encode()).hexdigest(), fixed["request_hash"])
        self.assertIsInstance(registered, StoredMediaV4)
        for field in ("video_id", "original_name", "storage_ref", "sha256", "size_bytes"):
            self.assertEqual(getattr(registered, field), getattr(video, field))
        self.assertEqual((registered.camera_id, registered.source_original_number, registered.offset_seconds), ("CAM2", "3", None))
        self.assertEqual((receipt.state, receipt.linked_revision, self.revision()), ("linked", before + 1, before + 1))
        self.assertEqual(uploads.linked_video_path(self.store, self.case_id, video.video_id, "review").read_bytes(), data)

    def test_response_loss_retry_ignores_old_revision_but_never_changes_metadata(self):
        video = self.preserved()
        request = self.request()
        first = self.register(video, request)
        self.assertEqual(self.register(video, request), first)
        self.assertEqual(self.count(), 1)
        for change in ({"camera_id": "CAM1"}, {"source_original_number": "other"}, {"request_id": "other-request"}):
            with self.assertRaises(HTTPException) as caught:
                self.register(video, self.request(**change))
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.revision(), first.linked_revision)

    def test_explicit_kind_and_conversion_requirements(self):
        base = {"request_id": "id", "expected_revision": 1, "camera_id": "CAM1"}
        for extra in ({}, {"source_kind": "app_derived"}, {"source_kind": "received_conversion"},
                      {"source_kind": "original", "conversion": {"tool": "tool", "tool_version": "1", "settings": {}}}):
            with self.assertRaises(ValidationError):
                PreservedMediaRegistrationV4.model_validate({**base, **extra})
        video = self.preserved(name="source.insv")
        receipt = self.register(video)
        self.assertEqual(receipt.media_status, "storage_only")
        self.assertFalse(receipt.analysis_ready)

    def converted(self):
        parent = self.preserved(name="source.insv", video_id="parent", data=b"synthetic-source")
        parent_receipt = self.register(parent, self.request(request_id="register-parent"))
        child = self.preserved(video_id="child", data=b"synthetic-converted")
        request = self.request(source_kind="received_conversion", parents=[MediaParentV4(upload_id=parent_receipt.upload_id,
            sha256=parent_receipt.sha256)], conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={"projection": "flat"}))
        return parent, child, request

    def test_received_conversion_preserves_parent_hash_video_and_tool_settings(self):
        parent, child, request = self.converted()
        receipt = self.register(child, request)
        with self.store.connect() as db:
            video = self.store.manifest(self.store.case(db, self.case_id)).sessions[0].videos[-1]
        self.assertEqual(video.parents[0].video_id, parent.video_id)
        self.assertEqual(video.parents[0].sha256, parent.sha256)
        self.assertEqual(video.conversion, request.conversion)
        self.assertEqual(receipt.source_kind, "received_conversion")

    def test_tampered_parent_or_preserved_bytes_prevent_registration(self):
        parent, child, request = self.converted()
        self.store.path(parent.storage_ref).write_bytes(b"x" * parent.size_bytes)
        before = self.revision()
        with self.assertRaises(HTTPException) as caught:
            self.register(child, request)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((self.count(), self.revision()), (1, before))
        self.store.path(child.storage_ref).write_bytes(b"x" * child.size_bytes)
        with self.assertRaises(HTTPException):
            self.register(child, self.request())

    def test_conversion_registration_only_accepts_preserved_mp4(self):
        parent, _, request = self.converted()
        wrong = self.preserved(name="converted.mov", video_id="wrong", data=b"synthetic-mov")
        with self.assertRaises(HTTPException) as caught:
            self.register(wrong, request.model_copy(update={"expected_revision": self.revision()}))
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.count(), 1)

    def test_original_changed_after_hash_is_not_adopted(self):
        video = self.preserved()
        verify = uploads._verify_file
        def mutate(store, row):
            path = verify(store, row)
            path.write_bytes(b"x" * video.size_bytes)
            return path
        with patch.object(uploads, "_verify_file", side_effect=mutate):
            with self.assertRaises(HTTPException) as caught:
                self.register(video)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.count(), 0)

    def test_revision_conflict_retries_same_preserved_file_without_upload(self):
        video = self.preserved()
        request = self.request()
        self.preserved(video_id="second", data=b"synthetic-second")
        with self.assertRaises(HTTPException) as caught:
            self.register(video, request)
        self.assertEqual(caught.exception.status_code, 409)
        receipt = self.register(video, self.request())
        self.assertEqual(receipt.video_id, video.video_id)
        self.assertEqual(self.count(), 1)

    def test_permission_consent_selection_deletion_and_login_rechecked_after_hash(self):
        video = self.preserved()
        with self.assertRaises(HTTPException) as caught:
            self.register(video, actor="review")
        self.assertEqual(caught.exception.status_code, 403)
        verify = uploads._verify_file
        def revoke(store, row):
            path = verify(store, row)
            with store.connect(write=True) as db:
                db.execute("UPDATE users SET session_hash='new-login' WHERE username='op'")
            return path
        with patch.object(uploads, "_verify_file", side_effect=revoke):
            with self.assertRaises(HTTPException) as caught:
                self.register(video)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.count(), 0)
        with self.store.connect(write=True) as db:
            case = self.store.case(db, self.case_id)
            manifest = self.store.manifest(case)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db, case, manifest, "op", "synthetic.consent")
        with self.assertRaises(HTTPException) as caught:
            self.register(video)
        self.assertEqual(caught.exception.status_code, 403)

    def test_selection_or_deletion_during_hash_prevents_adoption(self):
        video = self.preserved()
        verify = uploads._verify_file
        def retake(store, row):
            path = verify(store, row)
            with store.connect(write=True) as db:
                case = store.case(db, self.case_id)
                manifest = store.manifest(case)
                manifest.sessions.append(new_session_v4("retake"))
                manifest.selected_session_id = "retake"
                store.save(db, case, manifest, "op", "synthetic.retake")
            return path
        with patch.object(uploads, "_verify_file", side_effect=retake):
            with self.assertRaises(HTTPException) as caught:
                self.register(video)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.count(), 0)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        with self.assertRaises(HTTPException):
            self.register(video)

    def test_simultaneous_identical_requests_create_one_receipt_and_revision(self):
        video = self.preserved()
        request = self.request()
        barrier, verify = threading.Barrier(2), uploads._verify_file
        def wait_before_adoption(store, row):
            result = verify(store, row)
            barrier.wait(timeout=10)
            return result
        with patch.object(uploads, "_verify_file", side_effect=wait_before_adoption):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.register, video, request) for _ in range(2)]
                results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual((self.count(), self.revision()), (1, request.expected_revision + 1))


if __name__ == "__main__":
    unittest.main()
