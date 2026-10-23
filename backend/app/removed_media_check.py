"""Read-only pre-deployment inventory of discontinued media inputs."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import tempfile


def check(root: Path) -> dict:
    root = root.resolve()
    database = root / "kdog.sqlite3"
    if not database.is_file():
        raise ValueError("현재 데이터 DB가 필요합니다.")
    findings = {"cases": [], "receipts": [], "batches": []}

    def removed(value):
        return value.get("source_kind") == "external_360_mp4" or value.get("source_kind") != "received_file" and Path(
            value.get("original_name", value.get("filename", ""))).suffix.lower() == ".insv"

    def read(ref):
        path = (root / ref).resolve()
        if not path.is_relative_to(root):
            raise ValueError("데이터 루트 밖의 참조입니다.")
        return json.loads(path.read_bytes())

    sources = (database, database.with_name(database.name + "-wal"))

    def stamps():
        return {path: (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None for path in sources}

    with tempfile.TemporaryDirectory(prefix="kdog-media-check-") as folder:
        before = stamps()
        for path, stamp in before.items():
            if stamp is not None:
                shutil.copyfile(path, Path(folder) / path.name)
        if stamps() != before:
            raise ValueError("점검 중 DB가 변경되었습니다. API·worker 종료 후 다시 점검하세요.")
        snapshot = Path(folder) / database.name
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            for case_id, ref in db.execute("SELECT case_id,manifest_ref FROM cases"):
                for session in read(ref).get("sessions", []):
                    for video in session.get("videos", []):
                        if removed(video):
                            findings["cases"].append({"case_id": case_id, "session_id": session["session_id"],
                                                      "video_id": video["video_id"]})
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='upload_receipts'").fetchone():
                for upload_id, request in db.execute("SELECT upload_id,request_json FROM upload_receipts"):
                    if removed(json.loads(request)):
                        findings["receipts"].append({"upload_id": upload_id})
            for path in sorted((root / "clips").rglob("batch.json")):
                batch = read(path.relative_to(root))
                if any(removed(value) for value in batch.get("source_metadata", [])):
                    findings["batches"].append({"case_id": batch["case_id"], "session_id": batch["session_id"],
                                               "batch_id": batch["batch_id"]})
        if stamps() != before:
            raise ValueError("점검 중 DB가 변경되었습니다. API·worker 종료 후 다시 점검하세요.")
    return {"counts": {name: len(values) for name, values in findings.items()},
            "total": sum(map(len, findings.values())), "findings": findings}
