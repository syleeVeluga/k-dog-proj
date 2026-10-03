"""Explicit, offline, restartable removal of pre-S1 derived assessment data."""

import hashlib
import json
import re

from fastapi import HTTPException

from app import maintenance
from app.input_models_v4 import RawInputSourceV4, upgrade_to_s1
from app.legacy.input_models_v1 import Manifest as OriginalInput
from app.storage import encode, now
from app.usage import token_meters


RESET_ID = "s1-initial-20261002"
DERIVED = {"runs", "clips", "sheets", "results", "reviews", "exports"}
DERIVED_ACTIONS = ("preprocess.", "sheet.", "basic.", "ai.", "run.", "run_v3.",
                   "review.", "report.", "export.", "opinion.", "final.")


def _actor(db, actor):
    if not db.execute("SELECT 1 FROM users WHERE username=? AND role='admin' AND active=1", (actor,)).fetchone():
        raise HTTPException(403, "초기화에는 활성 운영 관리자 계정이 필요합니다.")


def _record(db, reset_id, action):
    row = db.execute("SELECT detail_json FROM changes WHERE target=? AND action=? ORDER BY rowid DESC LIMIT 1",
                     (reset_id, "s1.reset." + action)).fetchone()
    return json.loads(row[0]) if row else None


def boundary(db):
    row = db.execute("SELECT target FROM changes WHERE action='s1.reset.commit' ORDER BY rowid DESC LIMIT 1").fetchone()
    return row[0] if row else None


def _raw_sources(store, manifest):
    sources = []
    videos = {}
    entries = getattr(manifest, "raw_input_sources", []) if manifest.schema_version == "intake-4.0" else getattr(manifest, "prior_inputs", [])
    for entry in entries:
        if entry.schema_version != "intake-1.0":
            continue
        source = RawInputSourceV4(ref=entry.ref, hash=entry.hash)
        raw = maintenance.managed_path(store, source.ref).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source.hash:
            raise HTTPException(409, "보존할 최초 원입력의 해시가 일치하지 않습니다.")
        original = OriginalInput.model_validate_json(raw)
        if (original.case_id, original.event_id) != (manifest.case_id, manifest.event_id) or not original.participant_id:
            raise HTTPException(409, "최초 원입력의 참가자 연결이 일치하지 않습니다.")
        # A participant ID may have been corrected later; the original identity stays in the untouched bytes.
        for session in original.sessions:
            for video in session.videos:
                if maintenance.file_hash(maintenance.managed_path(store, video.storage_ref)) != video.sha256:
                    raise HTTPException(409, "최초 원입력에 연결된 영상의 해시가 일치하지 않습니다.")
                videos[video.storage_ref] = video.sha256
        sources.append(source)
    return sources, videos


def _plan(store, db):
    cases = []
    inputs = {}
    for row in db.execute("SELECT * FROM cases"):
        manifest = store.manifest(row)
        _, original_videos = _raw_sources(store, manifest)
        inputs.update(original_videos)
        for session in manifest.sessions:
            for video in session.videos:
                path = maintenance.managed_path(store, video.storage_ref)
                if maintenance.file_hash(path) != video.sha256:
                    raise HTTPException(409, "보존할 원본 영상의 해시가 일치하지 않습니다.")
                inputs[video.storage_ref] = video.sha256
        if manifest.schema_version != "intake-4.0":
            upgrade_to_s1(manifest)  # Validate the complete conversion before touching any records.
            cases.append({"case_id": row["case_id"], "revision": row["input_revision"],
                          "input_path": row["manifest_ref"], "input_digest": row["manifest_hash"]})
    runs = [r[0] for r in db.execute("SELECT run_id FROM runs WHERE kind NOT IN ('scoring_v4','report_v4')")]
    sheets = []
    for row in db.execute("SELECT s.sheet_id,s.manifest_ref,c.manifest_schema_version FROM score_sheets s JOIN cases c ON c.case_id=s.case_id"):
        try:
            data = json.loads(maintenance.managed_path(store, row["manifest_ref"]).read_bytes())
            if not isinstance(data, dict):
                raise ValueError("sheet document is not an object")
        except (OSError, ValueError):
            if row["manifest_schema_version"] == "intake-4.0":
                raise HTTPException(409, "S1 시트가 손상되어 초기화 대상을 판별할 수 없습니다.") from None
            data = {}  # Damaged old results may be discarded; raw inputs were checked above.
        if data.get("schema_version") == "3.0" or (data.get("schema_version") != "4.0" and row["manifest_schema_version"] != "intake-4.0"):
            sheets.append(row["sheet_id"])
    changes = []
    old_cases = {item["case_id"] for item in cases}
    old_exports = set()
    export_ids = set()
    for row in db.execute("SELECT target,detail_json FROM changes WHERE action='export.snapshot'"):
        detail = json.loads(row["detail_json"])
        try:
            raw = maintenance.managed_path(store, detail["ref"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != detail["hash"]:
                raise ValueError("export snapshot hash")
            snapshot = json.loads(raw)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("catalog", {}), dict):
                raise ValueError("export snapshot document")
        except (OSError, ValueError, KeyError):
            raise HTTPException(409, "내보내기 원본의 판본을 확인할 수 없습니다. 초기화 전에 참조를 복구하세요.") from None
        export_ids.add(row["target"])
        if snapshot.get("schema_version") == "4.0" or snapshot.get("catalog", {}).get("version") == "catalog-20261002-s1.1":
            continue
        members = snapshot.get("members", [])
        if not members or not all(member.get("case_id") in old_cases or member.get("run_id") in runs for member in members):
            raise HTTPException(409, "내보내기 판본과 초기화 대상 연결이 불명확합니다.")
        old_exports.add(row["target"])
    for row in db.execute("SELECT change_id,target,action,detail_json FROM changes"):
        if row["action"].startswith(("remote.", "s1.reset.")) or "remote_cleanup" in row["action"]:
            continue
        detail = json.loads(row["detail_json"])
        old_derived = row["action"].startswith(DERIVED_ACTIONS) and (
            row["target"] in old_cases or detail.get("sheet_id") in sheets or detail.get("run_id") in runs)
        if row["action"].startswith("export."):
            if row["target"] not in export_ids:
                raise HTTPException(409, "내보내기 파일의 고정 원본이 없습니다. 초기화 전에 참조를 복구하세요.")
            old_derived = row["target"] in old_exports
        if row["target"] in runs or old_derived:
            changes.append(row["change_id"])
    files = []
    for name in sorted(DERIVED | {"inputs"}):
        directory = store.path(name)
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    key = path.relative_to(store.root).as_posix()
                    safe = maintenance.managed_path(store, key)
                    files.append({"path": key, "digest": maintenance.file_hash(safe)})
    return {"data_root": str(store.root), "created_at": now(), "cases": cases, "runs": runs,
            "sheets": sheets, "changes": changes, "files": files, "preserved_videos": inputs}


def _summary(plan, reset_id, status):
    return {"reset_id": reset_id, "status": status, "data_root": plan["data_root"],
            "cases": len(plan["cases"]), "runs": len(plan["runs"]), "sheets": len(plan["sheets"]),
            "candidate_files": len(plan["files"]), "preserved_videos": len(plan["preserved_videos"])}


def preview(store, reset_id=RESET_ID):
    with store.connect() as db:
        plan = _record(db, reset_id, "plan") or _plan(store, db)
        status = "complete" if _record(db, reset_id, "complete") else "cleanup_pending" if _record(db, reset_id, "commit") else "ready"
    return _summary(plan, reset_id, status)


def execute(store, actor, reset_id=RESET_ID):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", reset_id):
        raise HTTPException(422, "초기화 작업 ID 형식이 올바르지 않습니다.")
    with maintenance.offline(store):
        with store.connect(write=True) as db:
            _actor(db, actor)
            plan = _record(db, reset_id, "plan")
            if plan is None:
                plan = _plan(store, db)
                store.audit(db, actor, reset_id, "s1.reset.plan", plan)
            if _record(db, reset_id, "complete"):
                return _summary(plan, reset_id, "complete")
        try:
            with store.connect(write=True) as db:
                if not _record(db, reset_id, "commit"):
                    _commit(store, db, plan, actor, reset_id)
            # The fixed file list never expands on a retry, so new S1 attempts cannot be swept up.
            with store.connect() as db:
                retained = maintenance.references(store, db)
            removed = 0
            for item in plan["files"]:
                if item["path"] in retained:
                    continue
                path = maintenance.managed_path(store, item["path"])
                if path.exists():
                    if maintenance.file_hash(path) != item["digest"]:
                        raise HTTPException(409, "초기화 계획 후 파일 내용이 바뀌었습니다. 보존 후 확인하세요.")
                    path.unlink()
                    removed += 1
            with store.connect(write=True) as db:
                store.audit(db, actor, reset_id, "s1.reset.complete", {"removed_files": removed, "completed_at": now()})
            return _summary(plan, reset_id, "complete")
        except (HTTPException, OSError, ValueError):
            with store.connect(write=True) as db:
                store.audit(db, actor, reset_id, "s1.reset.failed", {"status": "retry_required", "failed_at": now()})
            raise


def _commit(store, db, plan, actor, reset_id):
    for path, digest in plan["preserved_videos"].items():
        if maintenance.file_hash(maintenance.managed_path(store, path)) != digest:
            raise HTTPException(409, "초기화 점검 후 보존할 영상이 변경되었습니다.")
    for item in plan["cases"]:
        row = store.case(db, item["case_id"], expected=item["revision"], accessible=False)
        if (row["manifest_ref"], row["manifest_hash"]) != (item["input_path"], item["input_digest"]):
            raise HTTPException(409, "초기화 점검 후 원입력 참조가 변경되었습니다.")
        manifest = store.manifest(row)
        upgraded = upgrade_to_s1(manifest)
        upgraded.raw_input_sources, _ = _raw_sources(store, manifest)
        ref, digest = store.write_manifest(upgraded)
        db.execute("UPDATE cases SET input_revision=?,manifest_ref=?,manifest_hash=?,manifest_schema_version=?,"
                   "display_run_id=NULL,consents_v3_json=?,updated_at=? WHERE case_id=?",
                   (upgraded.input_revision, ref, digest, upgraded.schema_version,
                    upgraded.consents.model_dump_json(), now(), row["case_id"]))
    for run_id in plan["runs"]:
        run = db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        config = json.loads(run[0]) if run else {}
        for step in db.execute("SELECT * FROM steps WHERE run_id=?", (run_id,)).fetchall():
            usage = json.loads(step["usage_json"])
            selected = next((group for group in config.get("stages", [])
                             if (group.get("stage"), group.get("key")) == (step["stage"], step["branch_key"])), config)
            if step["call_reserved"] or usage.get("billing_uncertain") or token_meters(usage) or (
                    step["status"] in ("running", "abandoned") and step["stage"] in
                    ("ledger", "observe", "review_video", "evaluate", "report", "score_v3", "judge_v3")):
                store.audit(db, actor, reset_id, "s1.reset.usage", {
                    "run_id": run_id, "step_id": step["step_id"], "stage": step["stage"], "attempt": step["attempt"],
                    "call_reserved": bool(step["call_reserved"]), "status": step["status"],
                    "provider": usage.get("provider", selected.get("provider")), "model": usage.get("model", selected.get("model")),
                    "credential_reference": usage.get("credential_reference", selected.get("credential_reference")),
                    "meters": token_meters(usage.get("provider_usage", usage)),
                    "billing_uncertain": bool(usage.get("billing_uncertain") or step["status"] != "succeeded"
                                              or not token_meters(usage)),
                    "meter_cost_estimate": None})
        db.execute("UPDATE runs SET claim_token=NULL,lease_expires_at=NULL,status='stopped' WHERE run_id=?", (run_id,))
        db.execute("UPDATE cases SET display_run_id=NULL WHERE display_run_id=?", (run_id,))
        db.execute("DELETE FROM steps WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    for sheet_id in plan["sheets"]:
        db.execute("DELETE FROM score_grants WHERE viewer_sheet_id=? OR target_sheet_id=?", (sheet_id, sheet_id))
        db.execute("DELETE FROM basic_results WHERE sheet_id=?", (sheet_id,))
        db.execute("DELETE FROM score_sheets WHERE sheet_id=?", (sheet_id,))
    for change_id in plan["changes"]:
        db.execute("DELETE FROM changes WHERE change_id=?", (change_id,))
    store.audit(db, actor, reset_id, "s1.reset.commit", {"committed_at": now(), "catalog_version": "catalog-20261002-s1.1"})


def pending_remote_cleanup(store):
    """Return durable cleanup obligations, including uploads whose final response was lost."""
    with store.connect() as db:
        rows = db.execute("SELECT target,action,detail_json FROM changes WHERE action LIKE 'remote.%' "
                          "OR action LIKE '%remote_cleanup_failed' ORDER BY rowid").fetchall()
    registered = {(row["target"], json.loads(row["detail_json"]).get("remote_file_name"))
                  for row in rows if row["action"] == "remote.uploaded"}
    pending = {}
    for row in rows:
        data = json.loads(row["detail_json"])
        if row["action"] == "remote.upload_started":
            pending[data["upload_id"]] = {**data, "run_id": row["target"], "remote_file_name": None,
                                           "status": "upload_response_unconfirmed"}
        elif row["action"] == "remote.uploaded":
            pending[data["upload_id"]] = {**data, "run_id": row["target"], "status": "delete_pending"}
        elif row["action"] == "remote.deleted":
            pending.pop(data["upload_id"], None)
        elif row["action"].endswith("remote_cleanup_failed"):
            for name in data.get("remote_file_names", []):
                if (row["target"], name) in registered:
                    continue
                key = "legacy:" + row["target"] + ":" + name
                pending[key] = {"upload_id": key, "run_id": row["target"], "remote_file_name": name,
                                "credential_reference": data.get("credential_reference"), "status": "delete_pending"}
    return list(pending.values())


def retry_remote_cleanup(store, actor, *, delete=None):
    from app.gemini import BASE, ProviderError, request
    from app.secrets import credential

    with store.connect() as db:
        _actor(db, actor)
    for item in pending_remote_cleanup(store):
        name = item["remote_file_name"]
        if not name or not re.fullmatch(r"files/[A-Za-z0-9_-]+", name):
            continue
        try:
            if delete is None:
                key, reference = credential(store, "gemini")
                if reference != item["credential_reference"]:
                    continue  # A replacement key does not prove ownership of the former remote file.
                request("DELETE", BASE + "/v1beta/" + name, key)
            else:
                delete(name, item["credential_reference"])
        except ProviderError as exc:
            if exc.code != "provider_http_404":
                continue
        with store.connect(write=True) as db:
            store.audit(db, actor, item["run_id"], "remote.deleted", {"upload_id": item["upload_id"]})
    return {"pending": pending_remote_cleanup(store)}
