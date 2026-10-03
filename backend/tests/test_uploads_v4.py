import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import uploads
from app.domain.catalog_v4 import SURVEY_VERSION
from app.domain.media_v4 import ConversionV4, MediaParentV4, UploadCreateV4, UploadLinkV4
from app.input_models_v3 import CaseCreateV3
from app.intake import create_case
from app.maintenance import backup, clean, references, restore
from app.storage import Store
from app.input_models_v4 import new_session_v4


async def chunks(data):
    for offset in range(0, len(data), 3):
        yield data[offset:offset + 3]
        await asyncio.sleep(0)


class UploadsV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-upload-test-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "store")
        with self.store.connect(write=True) as db:
            uploads.init_schema(db)
            for user, role in (("op", "operator"), ("other", "operator"), ("admin", "admin"), ("review", "reviewer")):
                db.execute("INSERT INTO users(username,password_hash,role,session_hash) VALUES(?,?,?,?)",
                           (user, "synthetic-no-login", role, "synthetic-session-" + user))

    def case(self, participant="001"):
        with self.store.connect(write=True) as db:
            case_id = create_case(self.store, db, CaseCreateV3(event_id="SYNTHETIC", participant_id=participant,
                                  dog_name="합성견"), "op", SURVEY_VERSION)
            return dict(self.store.case(db, case_id))

    def create(self, data=b"synthetic-media", request_id="request-1", **changes):
        return uploads.create_receipt(self.store, UploadCreateV4(request_id=request_id,
            filename=changes.pop("filename", "camera.mp4"), expected_size=len(data), **changes), "op")

    def received(self, data=b"synthetic-media", **changes):
        receipt = self.create(data, **changes)
        return asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(data), "op"))

    def link(self, receipt, case, camera="CAM1", revision=None):
        return uploads.link_receipt(self.store, receipt.upload_id, UploadLinkV4(case_id=case["case_id"],
            session_id=case["selected_session_id"], camera_id=camera,
            expected_revision=revision or case["input_revision"]), "op")

    def current(self, case):
        with self.store.connect() as db:
            return dict(self.store.case(db, case["case_id"]))

    def test_three_receives_and_revision_conflicts_recover_without_reupload(self):
        case = self.case()
        data = [b"synthetic-camera-one", b"synthetic-camera-two", b"synthetic-camera-three"]
        receipts = [self.create(content, request_id=f"pc-{i}") for i, content in enumerate(data)]

        async def receive_all():
            return await asyncio.gather(*(uploads.receive(self.store, receipt.upload_id, receipt.request_id,
                chunks(content), "op") for receipt, content in zip(receipts, data)))

        receipts = asyncio.run(receive_all())
        self.assertTrue(all(receipt.state == "complete" for receipt in receipts))

        def attempt(pair):
            i, receipt = pair
            try:
                return self.link(receipt, case, f"CAM{i + 1}")
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
                return receipt

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(attempt, enumerate(receipts)))
        self.assertEqual(sum(result.state == "linked" for result in results), 1)
        for i, result in enumerate(results):
            if result.state == "complete":
                self.assertEqual(uploads.get_receipt(self.store, result.upload_id, "op").state, "complete")
                self.link(result, self.current(case), f"CAM{i + 1}")
        with self.store.connect() as db:
            session = self.store.manifest(self.store.case(db, case["case_id"])).sessions[0]
        self.assertEqual(len(session.videos), 3)
        self.assertEqual({v.camera_id: v.source_original_number for v in session.videos}, {"CAM1": "1", "CAM2": "3", "CAM3": "2"})
        self.assertTrue(all(v.offset_seconds is None for v in session.videos))

    def test_request_binding_and_response_loss_are_idempotent(self):
        data = b"synthetic-media"
        receipt = self.received(data)
        self.assertEqual(self.create(data).upload_id, receipt.upload_id)
        same = asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(data), "op"))
        self.assertEqual(same.sha256, receipt.sha256)
        with self.assertRaises(HTTPException) as conflict:
            self.create(data, filename="different.mp4")
        self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(b"x" * len(data)), "op"))
        with self.assertRaises(HTTPException):
            asyncio.run(uploads.receive(self.store, receipt.upload_id, "other-request", chunks(data), "op"))
        case = self.case()
        linked = self.link(receipt, case)
        self.assertEqual(self.link(receipt, case).video_id, linked.video_id)
        self.assertEqual(self.current(case)["input_revision"], 2)

    def test_same_camera_distinct_files_and_local_duplicate_do_not_cross_cases(self):
        case, other_case = self.case(), self.case("002")
        one = self.received(b"same-bytes", request_id="one")
        two = self.received(b"other-bytes", request_id="two")
        duplicate = self.received(b"same-bytes", request_id="duplicate")
        foreign = self.received(b"same-bytes", request_id="foreign")
        first = self.link(one, case, "CAM2")
        self.link(two, self.current(case), "CAM2")
        self.assertEqual(self.link(duplicate, self.current(case), "CAM2").video_id, first.video_id)
        self.assertNotEqual(self.link(foreign, other_case, "CAM2").video_id, first.video_id)
        self.assertEqual(self.current(case)["input_revision"], 3)

    def test_interruption_disk_failure_and_restart_need_a_new_whole_stream(self):
        receipt = self.create()

        async def interrupted():
            yield b"syn"
            raise OSError("synthetic network interruption")

        with self.assertRaises(OSError):
            asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, interrupted(), "op"))
        self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "failed")
        writer = uploads.begin_receive(self.store, receipt.upload_id, receipt.request_id, "op")
        uploads.write_chunk(writer, b"syn")
        writer.handle.close()
        writer.handle = None  # Simulate a terminated process holding no operating-system handle.
        with self.store.connect(write=True) as db:
            self.assertEqual(uploads.recover_interrupted(db), 1)
        with self.assertRaises(HTTPException):
            uploads.finish_receive(self.store, writer)
        uploads.fail_receive(self.store, writer)
        with patch("app.uploads.os.fsync", side_effect=OSError("synthetic full disk")):
            with self.assertRaises(OSError):
                asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(b"synthetic-media"), "op"))
        complete = asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(b"synthetic-media"), "op"))
        self.assertEqual(complete.state, "complete")
        self.assertEqual(uploads.download_path(self.store, receipt.upload_id, "op").read_bytes(), b"synthetic-media")

    def test_size_and_hash_mismatch_never_become_complete(self):
        for name, data, expected_hash in (("short", b"short", None), ("hash", b"synthetic-media", "0" * 64)):
            receipt = self.create(request_id=name, expected_sha256=expected_hash)
            with self.assertRaises(HTTPException):
                asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id, chunks(data), "op"))
            self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "failed")

    def test_deletion_and_revoked_account_or_session_block_completion(self):
        case = self.case()
        receipt = self.create(case_id=case["case_id"], session_id=case["selected_session_id"])
        writer = uploads.begin_receive(self.store, receipt.upload_id, receipt.request_id, "op")
        uploads.write_chunk(writer, b"synthetic-media")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (case["case_id"],))
        with self.assertRaises(HTTPException) as deleted:
            uploads.finish_receive(self.store, writer)
        self.assertEqual(deleted.exception.status_code, 403)
        uploads.fail_receive(self.store, writer)
        for index, sql in enumerate(("UPDATE users SET active=0 WHERE username='op'",
                                    "UPDATE users SET session_hash='changed' WHERE username='op'")):
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=1 WHERE username='op'")
            receipt = self.create(request_id=f"revoke-{index}")
            writer = uploads.begin_receive(self.store, receipt.upload_id, receipt.request_id, "op")
            uploads.write_chunk(writer, b"synthetic-media")
            with self.store.connect(write=True) as db:
                db.execute(sql)
            with self.assertRaises(HTTPException) as revoked:
                uploads.finish_receive(self.store, writer)
            self.assertEqual(revoked.exception.status_code, 403)
            uploads.fail_receive(self.store, writer)

    def test_unlinked_inventory_permissions_and_manual_cleanup_are_explicit(self):
        receipt = self.received()
        self.assertEqual(uploads.list_receipts(self.store, "other")[0].upload_id, receipt.upload_id)
        with self.assertRaises(HTTPException):
            uploads.list_receipts(self.store, "review")
        with self.assertRaises(HTTPException):
            uploads.begin_receive(self.store, receipt.upload_id, receipt.request_id, "other")
        with self.assertRaises(HTTPException):
            uploads.abort_receipt(self.store, receipt.upload_id, "other")
        self.assertEqual(uploads.abort_receipt(self.store, receipt.upload_id, "admin").failure_code, "cancelled")
        with self.store.connect() as db:
            self.assertEqual(uploads.references(db), {})

    def test_insv_and_received_conversion_keep_provenance_and_parent_access(self):
        case = self.case()
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        self.assertEqual(parent.media_status, "storage_only")
        child = self.received(b"synthetic-mp4", request_id="child", filename="converted.mp4", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={"projection": "360"}))
        with self.assertRaises(HTTPException):
            self.link(child, case)
        linked_parent = self.link(parent, case)
        linked_child = self.link(child, self.current(case))
        with self.store.connect() as db:
            videos = self.store.manifest(self.store.case(db, case["case_id"])).sessions[0].videos
        converted = next(video for video in videos if video.video_id == linked_child.video_id)
        self.assertEqual(converted.parents[0].video_id, linked_parent.video_id)
        self.assertEqual(converted.conversion.tool_version, "1.0")
        self.assertFalse(child.analysis_ready)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (case["case_id"],))
        with self.assertRaises(HTTPException):
            uploads.download_path(self.store, child.upload_id, "admin")
        with self.store.connect(write=True) as db:
            self.assertEqual(uploads.purge_case(db, case["case_id"]), 2)
            self.assertEqual(uploads.references(db), {})

    def test_receipt_snapshot_and_complete_bytes_survive_database_backup(self):
        receipt = self.received()
        backup_root = Path(self.temp.name) / "snapshot"
        backup_root.mkdir()
        with self.store.connect() as db, closing(sqlite3.connect(backup_root / "kdog.sqlite3")) as copy:
            db.backup(copy)
            refs = uploads.references(db)
        for ref, digest in refs.items():
            target = backup_root / ref
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.store.path(ref), target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
        restored = Store(backup_root)
        self.assertEqual(uploads.get_receipt(restored, receipt.upload_id, "op").state, "complete")
        self.assertEqual(uploads.download_path(restored, receipt.upload_id, "op").read_bytes(), b"synthetic-media")

    def test_tampered_complete_file_and_unsafe_name_are_rejected(self):
        for filename in ("../source.mp4", "C:\\video.mp4", "source.mp4.exe"):
            with self.subTest(filename=filename), self.assertRaises(ValidationError):
                UploadCreateV4(request_id="unsafe", filename=filename, expected_size=1)
        receipt = self.received()
        path = uploads.download_path(self.store, receipt.upload_id, "op")
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaises(HTTPException):
            self.link(receipt, self.case())
        self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "complete")

    def test_previous_session_receipts_remain_readable_after_retake(self):
        case = self.case()
        receipt = self.received()
        self.link(receipt, case)
        with self.store.connect(write=True) as db:
            current = self.store.case(db, case["case_id"])
            manifest = self.store.manifest(current)
            manifest.sessions.append(new_session_v4("synthetic-retake"))
            manifest.selected_session_id = "synthetic-retake"
            self.store.save(db, current, manifest, "op", "test.retake")
        self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "linked")
        self.assertEqual(len(uploads.list_receipts(self.store, "op")), 1)
        self.assertEqual(uploads.download_path(self.store, receipt.upload_id, "op").read_bytes(), b"synthetic-media")
        another = self.received(b"another-video", request_id="after-retake")
        with self.assertRaises(HTTPException) as caught:
            self.link(another, case, revision=self.current(case)["input_revision"])
        self.assertEqual(caught.exception.status_code, 409)

    def test_tampered_parent_bytes_block_derived_link_without_losing_child(self):
        case = self.case()
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        self.link(parent, case)
        child = self.received(b"synthetic-mp4", request_id="child", filename="converted.mp4", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        path = uploads.download_path(self.store, parent.upload_id, "op")
        path.write_bytes(b"x" * path.stat().st_size)
        before = self.current(case)["input_revision"]
        with self.assertRaises(HTTPException) as caught:
            self.link(child, self.current(case))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(uploads.get_receipt(self.store, child.upload_id, "op").state, "complete")
        self.assertEqual(self.current(case)["input_revision"], before)

    def test_parent_changed_after_hash_check_is_rejected_before_adoption(self):
        case = self.case()
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        self.link(parent, case)
        child = self.received(b"synthetic-mp4", request_id="child", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        verify = uploads._verify_file
        def changed_after_check(store, row):
            path = verify(store, row)
            if row["upload_id"] == parent.upload_id:
                path.write_bytes(b"x" * path.stat().st_size)
            return path
        with patch.object(uploads, "_verify_file", side_effect=changed_after_check):
            with self.assertRaises(HTTPException) as caught:
                self.link(child, self.current(case))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(uploads.get_receipt(self.store, child.upload_id, "op").state, "complete")

    def test_failed_conversion_remains_manageable_after_parent_is_cancelled(self):
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        child = self.create(b"synthetic-mp4", request_id="child", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        writer = uploads.begin_receive(self.store, child.upload_id, child.request_id, "op")
        uploads.fail_receive(self.store, writer)
        uploads.abort_receipt(self.store, parent.upload_id, "op")
        inventory = {item.upload_id: item for item in uploads.list_receipts(self.store, "op")}
        self.assertEqual(inventory[child.upload_id].failure_code, "interrupted")
        self.assertEqual(inventory[parent.upload_id].failure_code, "cancelled")
        self.assertEqual(uploads.get_receipt(self.store, child.upload_id, "op").state, "failed")
        self.assertEqual(uploads.abort_receipt(self.store, child.upload_id, "op").failure_code, "cancelled")
        with self.assertRaises(HTTPException):
            uploads.begin_receive(self.store, child.upload_id, child.request_id, "op")

    def test_changed_parent_bytes_block_receive_completion_and_derived_download(self):
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        conversion = dict(source_kind="received_conversion", parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
                          conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        completed = self.received(b"synthetic-mp4", request_id="completed", **conversion)
        partial = self.create(b"next-mp4", request_id="partial", **conversion)
        path = uploads.download_path(self.store, parent.upload_id, "op")
        path.write_bytes(b"x" * path.stat().st_size)
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(uploads.receive(self.store, partial.upload_id, partial.request_id, chunks(b"next-mp4"), "op"))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(uploads.get_receipt(self.store, partial.upload_id, "op").state, "failed")
        with self.assertRaises(HTTPException) as caught:
            uploads.download_path(self.store, completed.upload_id, "op")
        self.assertEqual(caught.exception.status_code, 409)

    def test_deletion_after_download_hashing_is_rechecked(self):
        case = self.case()
        receipt = self.received()
        self.link(receipt, case)
        verify = uploads._verify_file
        def delete_after_check(store, row):
            path = verify(store, row)
            with store.connect(write=True) as db:
                db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (case["case_id"],))
            return path
        with patch.object(uploads, "_verify_file", side_effect=delete_after_check):
            with self.assertRaises(HTTPException) as caught:
                uploads.download_path(self.store, receipt.upload_id, "op")
        self.assertEqual(caught.exception.status_code, 403)

    def restore_before_case_link(self, *, already_cleaned):
        parent = self.received(b"synthetic-insv", request_id="delete-parent", filename="camera.insv")
        child = self.received(b"synthetic-child", request_id="delete-child", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        retained = self.received(b"retained-other", request_id="keep-other")
        snapshot = Path(self.temp.name) / "before-case-and-link"
        backup(self.store, snapshot, "op")
        case = self.case()
        self.link(parent, case)
        # Keep the child unlinked: descendants of a deleted parent are in scope too.
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (case["case_id"],))
            self.assertEqual(uploads.collect_case_upload_ids(db, case["case_id"]), {parent.upload_id, child.upload_id})
        if already_cleaned:
            clean(self.store, purge_deleted=True)
        restored_path = Path(self.temp.name) / "restored"
        restore(self.store, snapshot, restored_path)
        restored = Store(restored_path)
        for receipt in (parent, child):
            with self.assertRaises(HTTPException) as caught:
                uploads.get_receipt(restored, receipt.upload_id, "op")
            self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(uploads.download_path(restored, retained.upload_id, "op").read_bytes(), b"retained-other")
        with restored.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM upload_receipts").fetchone()[0], 1)
            tombstones = [json.loads(row[0]) for row in db.execute("SELECT detail_json FROM changes WHERE action='deletion.upload'")]
            self.assertEqual({item["upload_id"] for item in tombstones}, {parent.upload_id, child.upload_id})
            self.assertTrue(all(set(item) == {"upload_id"} for item in tombstones))
            expected_refs = references(restored, db)
        self.assertTrue(all(file.relative_to(restored.root).as_posix() in expected_refs for file in restored.path("videos").glob("*")))

    def test_restore_deletion_request_removes_receipts_from_before_case_link(self):
        self.restore_before_case_link(already_cleaned=False)

    def test_restore_deletion_after_cleanup_removes_receipts_from_before_case_link(self):
        self.restore_before_case_link(already_cleaned=True)

    def test_disk_write_and_finish_do_not_block_other_async_work(self):
        for phase in ("write_chunk", "finish_receive"):
            with self.subTest(phase=phase):
                receipt = self.create(request_id="heartbeat-" + phase)
                entered, release = threading.Event(), threading.Event()
                operation = getattr(uploads, phase)
                def blocked(*args):
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("test worker was not released")
                    return operation(*args)
                async def scenario():
                    task = asyncio.create_task(uploads.receive(self.store, receipt.upload_id, receipt.request_id,
                                                                chunks(b"synthetic-media"), "op"))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        self.assertFalse(task.done())
                        pulses = []
                        for number in range(3):
                            await asyncio.sleep(0)
                            pulses.append(number)
                        self.assertEqual(pulses, [0, 1, 2])
                    finally:
                        release.set()
                    return await task
                with patch.object(uploads, phase, side_effect=blocked):
                    result = asyncio.run(scenario())
                self.assertEqual(result.state, "complete")

    def test_cancel_waits_for_disk_write_then_cleans_partial_file(self):
        receipt = self.create()
        entered, release = threading.Event(), threading.Event()
        operation = uploads.write_chunk
        def blocked(writer, chunk):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test writer was not released")
            return operation(writer, chunk)
        async def scenario():
            task = asyncio.create_task(uploads.receive(self.store, receipt.upload_id, receipt.request_id,
                                                        chunks(b"synthetic-media"), "op"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()  # Repeated cancellation must still wait for the current writer.
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        with patch.object(uploads, "write_chunk", side_effect=blocked):
            asyncio.run(scenario())
        self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "failed")
        self.assertFalse(list(self.store.path("videos").glob("*")))

    def test_cancel_after_durable_completion_preserves_idempotent_result(self):
        receipt = self.create()
        entered, release = threading.Event(), threading.Event()
        finish = uploads.finish_receive
        def completed_before_response(*args):
            result = finish(*args)
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test response was not released")
            return result
        async def scenario():
            task = asyncio.create_task(uploads.receive(self.store, receipt.upload_id, receipt.request_id,
                                                        chunks(b"synthetic-media"), "op"))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        with patch.object(uploads, "finish_receive", side_effect=completed_before_response):
            asyncio.run(scenario())
        self.assertEqual(uploads.get_receipt(self.store, receipt.upload_id, "op").state, "complete")
        self.assertEqual(uploads.download_path(self.store, receipt.upload_id, "op").read_bytes(), b"synthetic-media")
        self.assertEqual(asyncio.run(uploads.receive(self.store, receipt.upload_id, receipt.request_id,
                                                     chunks(b"synthetic-media"), "op")).upload_id, receipt.upload_id)

    def test_linked_video_reader_checks_case_binding_without_opening_inbox(self):
        case = self.case()
        receipt = self.received()
        linked = self.link(receipt, case)
        self.assertEqual(uploads.linked_video_path(self.store, case["case_id"], linked.video_id, "review").read_bytes(),
                         b"synthetic-media")
        with self.assertRaises(HTTPException) as caught:
            uploads.download_path(self.store, receipt.upload_id, "review")
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            uploads.linked_video_path(self.store, self.case("other")["case_id"], linked.video_id, "review")
        self.assertEqual(caught.exception.status_code, 404)
        with self.store.connect(write=True) as db:
            row = self.store.case(db, case["case_id"])
            manifest = self.store.manifest(row)
            manifest.consents.analysis_feedback = "declined"
            self.store.save(db, row, manifest, "op", "test.decline")
        with self.assertRaises(HTTPException) as caught:
            uploads.linked_video_path(self.store, case["case_id"], linked.video_id, "review")
        self.assertEqual(caught.exception.status_code, 403)

    def test_linked_video_reader_cannot_bypass_parent_integrity_or_revocation(self):
        case = self.case()
        parent = self.received(b"synthetic-insv", request_id="parent", filename="camera.insv")
        self.link(parent, case)
        child = self.received(b"synthetic-mp4", request_id="child", source_kind="received_conversion",
            parents=[MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256)],
            conversion=ConversionV4(tool="synthetic-converter", tool_version="1.0", settings={}))
        linked = self.link(child, self.current(case))
        parent_path = uploads.download_path(self.store, parent.upload_id, "op")
        parent_path.write_bytes(b"x" * parent_path.stat().st_size)
        with self.assertRaises(HTTPException) as caught:
            uploads.linked_video_path(self.store, case["case_id"], linked.video_id, "review")
        self.assertEqual(caught.exception.status_code, 409)
        parent_path.write_bytes(b"synthetic-insv")
        verify = uploads._verify_file
        def revoke_after_check(store, row):
            path = verify(store, row)
            with store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='review'")
            return path
        with patch.object(uploads, "_verify_file", side_effect=revoke_after_check):
            with self.assertRaises(HTTPException) as caught:
                uploads.linked_video_path(self.store, case["case_id"], linked.video_id, "review")
        self.assertEqual(caught.exception.status_code, 403)
