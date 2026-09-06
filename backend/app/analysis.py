"""Durable M2 run/step references, fenced artifact adoption and explicit reuse."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os

from fastapi import HTTPException

from app.domain.validation import validate_evidence
from app.domain.contracts import BehaviorCatalog, SurveyCatalog
from app.evaluation import active_configuration, validated_evaluation
from app.scoring import RULES, behavior_scores, survey_scores
from app.gemini import configuration
from app.input_models import Manifest
from app.intake import selected_session
from app.observation_models import (
    AnalysisView, ObservationArtifact, PreparedInput, RunView, StepView,
)
from app.storage import REPO_ROOT, Store, encode, now, uid


LEASE_SECONDS = 180
ACTIVE = ("queued", "running", "retry_wait")


def later(seconds) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def session_snapshot(row):
    manifest = Manifest.model_validate_json(row["input_snapshot_json"])
    return manifest, selected_session(manifest, row["session_id"])


def related_input(row):
    manifest, session = session_snapshot(row)
    return {"case_id": manifest.case_id, "session_id": session.session_id,
            "videos": [video.model_dump() for video in session.videos],
            "capture_mode": session.capture_mode, "route_note": session.route_note,
            "config": {key: value for key, value in json.loads(row["config_snapshot_json"]).items()
                       if key not in ("evaluation", "report", "behavior_catalog", "survey_catalog", "scoring_rules",
                                      "settings_version", "evaluation_concurrency", "max_ai_calls", "max_attempts")}}


def evaluation_related(row, branch):
    config = json.loads(row["config_snapshot_json"])
    return {"observation": related_input(row), "evaluation": config.get("evaluation", {}).get(branch),
            "catalog": config.get("behavior_catalog"), "rules": config.get("scoring_rules")}


def read_artifact(store, ref, expected_hash=None):
    try:
        raw = store.path(ref).read_bytes()
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("hash")
        return json.loads(raw)
    except (OSError, ValueError):
        raise HTTPException(409, "관찰 산출물 파일 또는 해시가 올바르지 않습니다.") from None


def step_payload(store, row, step, *, recover=False):
    ref = step["output_ref"] or f"runs/{row['run_id']}/{step['step_id']}/output.json"
    result = read_artifact(store, ref, None if recover else step["output_hash"])
    if (result["run_id"], result["step_id"], result["claim_token"], result["input_hash"], result["config_hash"]) != (
        row["run_id"], step["step_id"], step["claim_token"],
        digest(json.loads(row["input_snapshot_json"])), digest(json.loads(row["config_snapshot_json"]))
    ):
        raise HTTPException(409, "산출물 실행 연결이 일치하지 않습니다.")
    return result["payload"]


def validated_observation(payload, run_input, video_id, source_run_id=None):
    artifact = ObservationArtifact.model_validate_json(encode(payload))
    origin = source_run_id or run_input.run_id
    if artifact.run_id != origin or artifact.video_id != video_id:
        raise ValueError("observation provenance mismatch")
    for item in artifact.evidence:
        if item.run_id != origin or item.video_id != video_id:
            raise ValueError("evidence provenance mismatch")
    # Only an already checked, explicit manifest entry may use another source run.
    rebound = tuple(item.model_copy(update={"run_id": run_input.run_id}) for item in artifact.evidence)
    validate_evidence(run_input, rebound)
    return artifact


def validated_prepared(row, payload):
    prepared = PreparedInput.model_validate_json(encode(payload))
    manifest, session = session_snapshot(row)
    run = prepared.run_input
    config = json.loads(row["config_snapshot_json"])
    if (run.catalog_version, run.scoring_rule_version) != (config["catalog_version"], config.get("scoring_rules", {}).get("version", "pending-v1")):
        raise ValueError("prepared calculation version mismatch")
    if (run.run_id, run.case_id, run.session_id, run.input_revision, run.survey) != (
        row["run_id"], row["case_id"], row["session_id"], row["input_revision"], session.survey
    ):
        raise ValueError("prepared input provenance mismatch")
    original = {v.video_id: v for v in session.videos}
    valid = {v.video_id: v for v in run.videos}
    if set(valid) & set(prepared.errors) or set(valid) | set(prepared.errors) != set(original):
        raise ValueError("prepared video membership mismatch")
    if len(prepared.media) != len(valid) or {m.video_id for m in prepared.media} != set(valid):
        raise ValueError("prepared media membership mismatch")
    for video in valid.values():
        source = original[video.video_id]
        if (video.camera_id, video.storage_ref, video.sha256) != (source.camera_id, source.storage_ref, source.sha256):
            raise ValueError("prepared source mismatch")
    for media in prepared.media:
        video = valid[media.video_id]
        if (video.duration_sec, video.audio_status) != (media.duration_sec, media.audio_status):
            raise ValueError("prepared media properties mismatch")
    return prepared


def enqueue(store: Store, case_id, value, actor):
    config = configuration()
    catalog = json.loads((REPO_ROOT / "resources/catalogs/behavior-v1.json").read_text(encoding="utf-8"))
    config["catalog_version"] = catalog["version"]
    config["catalog_hash"] = digest(catalog)
    config["catalog_items"] = [{"item_id": item["item_id"], "text": item["text"], "segment": item["segment"]}
                               for item in catalog["items"]]
    config["behavior_catalog"] = catalog
    config["survey_catalog"] = json.loads((REPO_ROOT / "resources/catalogs/survey-v1.json").read_text(encoding="utf-8"))
    config["scoring_rules"] = RULES
    with store.connect(write=True) as db:
        _, config["evaluation"] = active_configuration(db, config["model"])
        from app.reporting import active_report_configuration
        _, config["report"] = active_report_configuration(db, config["model"])
        from app.settings import apply_snapshot
        apply_snapshot(store, db, config)
        case = store.case(db, case_id, expected=value.expected_revision)
        manifest = store.manifest(case)
        session = selected_session(manifest, manifest.selected_session_id)
        if not session.videos:
            raise HTTPException(422, "선택 촬영 세션에 영상이 없습니다.")
        if not value.reanalyze:
            existing = db.execute("SELECT run_id FROM runs WHERE case_id=? AND input_revision=? "
                                  "AND status IN ('queued','running','retry_wait') ORDER BY created_at DESC LIMIT 1",
                                  (case_id, case["input_revision"])).fetchone()
            if existing:
                return existing["run_id"]
        reuse = []
        snapshot = {"input_snapshot_json": manifest.model_dump_json(), "session_id": session.session_id,
                    "config_snapshot_json": encode(config)}
        if value.reuse_run_id:
            source = db.execute("SELECT * FROM runs WHERE run_id=? AND case_id=?",
                                (value.reuse_run_id, case_id)).fetchone()
            if not source or related_input(source) != related_input(snapshot):
                raise HTTPException(409, "재사용할 참가자·세션·영상·관찰 설정이 일치하지 않습니다.")
            prepared_step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='prepare' AND status='succeeded'",
                                       (source["run_id"],)).fetchone()
            if not prepared_step:
                raise HTTPException(409, "재사용할 미디어 검사 결과가 없습니다.")
            prepared = validated_prepared(source, step_payload(store, source, prepared_step))
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='observe' AND status='succeeded'", (source["run_id"],)):
                validated_observation(step_payload(store, source, step), prepared.run_input, step["branch_key"])
                reuse.append({"source_run_id": source["run_id"], "step_id": step["step_id"],
                              "video_id": step["branch_key"], "output_ref": step["output_ref"],
                              "output_hash": step["output_hash"], "related_hash": digest(related_input(source))})
            if not reuse:
                raise HTTPException(409, "재사용할 성공 관찰이 없습니다.")
            # Reuse evaluation only when every camera observation is directly reusable.
            if {entry["video_id"] for entry in reuse} == {m.video_id for m in prepared.media}:
                source_evidence = tuple(e for artifact in observations(store, db, source, prepared) for e in artifact.evidence)
                source_config = json.loads(source["config_snapshot_json"])
                for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='evaluate' AND status='succeeded'", (source["run_id"],)):
                    branch = step["branch_key"]
                    if evaluation_related(source, branch) != evaluation_related(snapshot, branch):
                        continue
                    artifact = validated_evaluation(step_payload(store, source, step), prepared.run_input, branch,
                        BehaviorCatalog.model_validate_json(encode(source_config["behavior_catalog"])), source_evidence)
                    if artifact.usage.get("reused"):
                        continue
                    reuse.append({"stage": "evaluate", "branch": branch, "source_run_id": source["run_id"],
                                  "step_id": step["step_id"], "output_ref": step["output_ref"], "output_hash": step["output_hash"],
                                  "related_hash": digest(evaluation_related(snapshot, branch))})
        run_id = uid()
        db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,"
                   "reuse_manifest_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (run_id, case_id, session.session_id, case["input_revision"], manifest.model_dump_json(),
                    encode(config), encode(reuse), "queued", now(), now()))
        db.execute("UPDATE cases SET display_run_id=? WHERE case_id=?", (run_id, case_id))
        store.audit(db, actor, run_id, "analysis.start", {"revision": case["input_revision"], "reuse": value.reuse_run_id})
        return run_id


def check_access(store, db, row):
    store.case(db, row["case_id"])


def guard(store, run_id, token, *, renew=True):
    with store.connect(write=renew) as db:
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row or row["status"] != "running" or row["claim_token"] != token or row["lease_expires_at"] <= now():
            raise HTTPException(409, "실행 점유가 만료되었거나 중지되었습니다.")
        check_access(store, db, row)
        if renew:
            db.execute("UPDATE runs SET lease_expires_at=?,heartbeat_at=? WHERE run_id=? AND claim_token=?",
                       (later(LEASE_SECONDS), now(), run_id, token))
        return row


def claim(store):
    with store.connect(write=True) as db:
        rows = db.execute("SELECT * FROM runs WHERE status IN ('queued','retry_wait') "
                          "OR (status='running' AND lease_expires_at<=?) ORDER BY created_at", (now(),)).fetchall()
        for row in rows:
            try:
                check_access(store, db, row)
            except HTTPException:
                db.execute("UPDATE runs SET status='stopped',claim_token=NULL,updated_at=? WHERE run_id=?", (now(), row["run_id"]))
                continue
            pending = db.execute("SELECT MAX(retry_at) FROM steps WHERE run_id=? AND status='retry_wait'", (row["run_id"],)).fetchone()[0]
            if pending and pending > now():
                continue
            token = uid()
            db.execute("UPDATE runs SET status='running',claim_token=?,lease_expires_at=?,heartbeat_at=?,updated_at=? WHERE run_id=?",
                       (token, later(LEASE_SECONDS), now(), now(), row["run_id"]))
            claimed = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone())
            claimed["retry_failed"] = row["status"] == "queued"
            return claimed
    return None


def write_output(store, row, step, payload):
    ref = f"runs/{row['run_id']}/{step['step_id']}/output.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"run_id": row["run_id"], "step_id": step["step_id"], "claim_token": step["claim_token"],
             "input_hash": digest(json.loads(row["input_snapshot_json"])),
             "config_hash": digest(json.loads(row["config_snapshot_json"])), "payload": payload}
    raw = encode(value).encode("utf-8")
    temp = path.with_name(uid() + ".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic publication, no existing attempt artifact can be overwritten.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return ref, hashlib.sha256(raw).hexdigest()


def adopt(store, row, step, ref, output_hash, usage):
    with store.connect(write=True) as db:
        current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
        if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "오래된 실행 결과를 채택할 수 없습니다.")
        check_access(store, db, current)
        changed = db.execute("UPDATE steps SET status='succeeded',output_ref=?,output_hash=?,usage_json=?,updated_at=? "
                             "WHERE step_id=? AND status='running' AND claim_token=?",
                             (ref, output_hash, encode(usage), now(), step["step_id"], step["claim_token"])).rowcount
        if not changed:
            raise HTTPException(409, "오래된 단계 결과를 채택할 수 없습니다.")


def observations(store, db, row, prepared):
    output = []
    for entry in json.loads(row["reuse_manifest_json"]):
        if entry.get("stage", "observe") != "observe":
            continue
        if entry["related_hash"] != digest(related_input(row)):
            raise HTTPException(409, "재사용 입력 해시가 일치하지 않습니다.")
        source = db.execute("SELECT * FROM runs WHERE run_id=? AND case_id=? AND session_id=?",
                            (entry["source_run_id"], row["case_id"], row["session_id"])).fetchone()
        step = db.execute("SELECT * FROM steps WHERE step_id=? AND run_id=? AND status='succeeded'",
                          (entry["step_id"], entry["source_run_id"])).fetchone()
        if not source or not step or (step["output_ref"], step["output_hash"]) != (entry["output_ref"], entry["output_hash"]):
            raise HTTPException(409, "재사용 산출물 연결이 일치하지 않습니다.")
        output.append(validated_observation(step_payload(store, source, step), prepared.run_input,
                                            entry["video_id"], entry["source_run_id"]))
    for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='observe' AND status='succeeded' ORDER BY branch_key", (row["run_id"],)):
        output.append(validated_observation(step_payload(store, row, step), prepared.run_input, step["branch_key"]))
    ids = [item.evidence_id for artifact in output for item in artifact.evidence]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence")
    return output


def evaluation_reuse(store, row, branch, run, catalog, evidence):
    entry = next((entry for entry in json.loads(row["reuse_manifest_json"])
                  if entry.get("stage") == "evaluate" and entry["branch"] == branch), None)
    if not entry:
        return None
    if entry["related_hash"] != digest(evaluation_related(row, branch)):
        raise ValueError("evaluation reuse configuration mismatch")
    with store.connect() as db:
        source = db.execute("SELECT * FROM runs WHERE run_id=? AND case_id=? AND session_id=?",
                            (entry["source_run_id"], row["case_id"], row["session_id"])).fetchone()
        step = db.execute("SELECT * FROM steps WHERE step_id=? AND run_id=? AND stage='evaluate' AND branch_key=? AND status='succeeded'",
                          (entry["step_id"], entry["source_run_id"], branch)).fetchone()
        if not source or not step or (step["output_ref"], step["output_hash"]) != (entry["output_ref"], entry["output_hash"]):
            raise ValueError("evaluation reuse provenance mismatch")
        source_run = run.model_copy(update={"run_id": source["run_id"]})
        artifact = validated_evaluation(step_payload(store, source, step), source_run, branch, catalog, evidence)
    evaluation = artifact.evaluation.model_copy(update={"run_id": run.run_id})
    rebound = tuple(e.model_copy(update={"run_id": run.run_id}) for e in evidence)
    return artifact.model_copy(update={"evaluation": evaluation, "scores": behavior_scores(run, [evaluation], catalog, rebound),
        "usage": {"reused": True, "source_run_id": source["run_id"]}})


def view_analysis(store, case_id):
    result = []
    with store.connect() as db:
        case = store.case(db, case_id)
        for row in db.execute("SELECT * FROM runs WHERE case_id=? ORDER BY created_at DESC", (case_id,)):
            steps = db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY created_at", (row["run_id"],)).fetchall()
            ready = next((step for step in steps if step["stage"] == "prepare" and step["status"] == "succeeded"), None)
            prepared, artifacts, evaluations, scores, survey = None, [], [], None, None
            config = json.loads(row["config_snapshot_json"])
            if "evaluation" in config:
                if config["scoring_rules"] != RULES:
                    raise HTTPException(409, "이 실행의 계산 규칙 버전을 현재 코드에서 지원하지 않습니다.")
                survey_step = next((s for s in steps if s["stage"] == "survey" and s["status"] == "succeeded"), None)
                if survey_step:
                    _, session = session_snapshot(row)
                    survey = survey_scores(row["run_id"], session.survey, SurveyCatalog.model_validate_json(encode(config["survey_catalog"])))
                    if step_payload(store, row, survey_step) != survey.model_dump(mode="json"):
                        raise HTTPException(409, "설문 계산 산출물이 일치하지 않습니다.")
            if ready:
                prepared = validated_prepared(row, step_payload(store, row, ready))
                artifacts = observations(store, db, row, prepared)
                evidence = tuple(e for artifact in artifacts for e in artifact.evidence)
                if "evaluation" in config:
                    catalog = BehaviorCatalog.model_validate_json(encode(config["behavior_catalog"]))
                    for step in steps:
                        if step["stage"] == "evaluate" and step["status"] == "succeeded":
                            evaluations.append(validated_evaluation(step_payload(store, row, step), prepared.run_input,
                                                                   step["branch_key"], catalog, evidence))
                    if evaluations:
                        evaluations.sort(key=lambda artifact: artifact.evaluation.branch)
                        rebound = tuple(e.model_copy(update={"run_id": row["run_id"]}) for e in evidence)
                        scores = behavior_scores(prepared.run_input, [a.evaluation for a in evaluations], catalog, rebound)
            result.append(RunView(run_id=row["run_id"], session_id=row["session_id"], input_revision=row["input_revision"],
                status=row["status"], created_at=row["created_at"], is_current=case["display_run_id"] == row["run_id"],
                steps=[StepView(stage=s["stage"], branch_key=s["branch_key"], attempt=s["attempt"], status=s["status"],
                                retry_at=s["retry_at"], usage=json.loads(s["usage_json"])) for s in steps],
                evidence=[item for artifact in artifacts for item in artifact.evidence],
                media=prepared.media if prepared else [], media_errors=prepared.errors if prepared else {},
                unconfirmed_conditions=[flag for artifact in artifacts for flag in artifact.unconfirmed_conditions],
                evaluations=evaluations, scores=scores, survey_scores=survey,
                behavior_items=list(catalog.items) if evaluations else [],
                reused_from=sorted({entry["source_run_id"] for entry in json.loads(row["reuse_manifest_json"])})))
    from app.settings import current
    from app.secrets import available
    try:
        with store.connect() as db:
            _, selected = current(store, db)
        ready = bool(selected.observe.model and available(store, "gemini"))
    except (HTTPException, OSError, ValueError):
        # Broken current settings must not hide already validated historical results.
        ready = False
    return AnalysisView(configured=ready, message="관찰 설정 준비됨 · 평가 공급자 연결은 각 분기 실행 시 확인합니다." if ready
                        else "개발자 설정 필요 · Gemini 모델과 키를 설정한 worker가 필요합니다.", runs=result)


def control(store, case_id, run_id, actor, action):
    with store.connect(write=True) as db:
        store.case(db, case_id)
        row = db.execute("SELECT * FROM runs WHERE run_id=? AND case_id=?", (run_id, case_id)).fetchone()
        if not row:
            raise HTTPException(404, "이 참가자의 실행이 아닙니다.")
        if action == "retry":
            check_access(store, db, row)
            if row["status"] not in ("partial_failed", "settings_required", "failed"):
                raise HTTPException(409, "실패한 실행만 재시도할 수 있습니다.")
            steps = db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY attempt", (run_id,)).fetchall()
            latest, repairs = {}, {}
            for step in steps:
                key = (step["stage"], step["branch_key"])
                latest[key] = step
                if json.loads(step["usage_json"]).get("code") in ("observation_schema_invalid", "evaluation_schema_invalid"):
                    repairs[key] = repairs.get(key, 0) + 1
            maximum = json.loads(row["config_snapshot_json"]).get("max_attempts", 3)
            if not any(step["status"] != "succeeded" and step["attempt"] < maximum and repairs.get(key, 0) < 2
                       for key, step in latest.items()):
                raise HTTPException(409, "재시도 가능한 실패 단계가 없습니다. 시도·구조 수정 한도와 입력·설정을 확인하세요.")
            state = "queued"
        else:
            if row["status"] not in ACTIVE:
                raise HTTPException(409, "진행 중인 실행만 중지할 수 있습니다.")
            state = "stopped"
        db.execute("UPDATE runs SET status=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?", (state, now(), run_id))
        store.audit(db, actor, run_id, "analysis." + action, {})
