import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.domain.media_v4 import StoredMediaV4, UploadCreateV4
from app.removed_media_check import check


class RemovedMediaCheckTests(unittest.TestCase):
    def test_raw_inventory_reports_each_location_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "input.json"
            manifest.write_text(json.dumps({"sessions": [{"session_id": "s1", "videos": [
                {"video_id": "v1", "original_name": "source.INSV"}]}]}))
            batch = root / "clips/c1/s1/b1/t1/batch.json"
            batch.parent.mkdir(parents=True)
            batch.write_text(json.dumps({"case_id": "c1", "session_id": "s1", "batch_id": "b1",
                                         "source_metadata": [{"source_kind": "external_360_mp4"}]}))
            with closing(sqlite3.connect(root / "kdog.sqlite3")) as db, db:
                db.execute("CREATE TABLE cases(case_id TEXT,manifest_ref TEXT)")
                db.execute("INSERT INTO cases VALUES ('c1','input.json')")
                db.execute("CREATE TABLE upload_receipts(upload_id TEXT,request_json TEXT)")
                db.execute("INSERT INTO upload_receipts VALUES (?,?)", ("u1", '{"filename":"source.insv"}'))
                db.execute("INSERT INTO upload_receipts VALUES (?,?)", ("u2", '{"filename":"new.insv","source_kind":"received_file"}'))
            before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            result = check(root)
            self.assertEqual(result["counts"], {"cases": 1, "receipts": 1, "batches": 1})
            self.assertEqual(result["total"], 3)
            self.assertEqual(before, {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()})
            manifest.write_text('{"sessions":[]}')
            batch.unlink()
            with closing(sqlite3.connect(root / "kdog.sqlite3")) as db, db:
                db.execute("DELETE FROM upload_receipts")
            self.assertEqual(check(root)["total"], 0)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                check(Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_wal_snapshot_reads_committed_rows_and_never_creates_source_sidecars(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def snapshot():
                return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}

            with closing(sqlite3.connect(root / "kdog.sqlite3")) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE cases(case_id TEXT,manifest_ref TEXT)")
                db.execute("CREATE TABLE upload_receipts(upload_id TEXT,request_json TEXT)")
                db.execute("INSERT INTO upload_receipts VALUES ('u1','{\"filename\":\"source.insv\"}')")
                db.commit()
                before = snapshot()
                self.assertEqual(check(root)["counts"]["receipts"], 1)
                self.assertEqual(snapshot(), before)
            before = snapshot()
            self.assertEqual(list(before), ["kdog.sqlite3"])
            self.assertEqual(check(root)["total"], 1)
            self.assertEqual(snapshot(), before)

    def test_pending_probe_json_keeps_canonical_contract(self):
        request = UploadCreateV4(request_id="r1", filename="source.mp4", expected_size=1)
        self.assertEqual(UploadCreateV4.model_validate_json(request.model_dump_json()), request)
        video = StoredMediaV4(video_id="v1", upload_id="u1", original_name="source.mp4", storage_ref="source.mp4",
                              sha256="a" * 64, size_bytes=1, camera_id="CAM1", source_kind="original", media_status="pending_probe")
        self.assertEqual(StoredMediaV4.model_validate_json(video.model_dump_json()), video)
