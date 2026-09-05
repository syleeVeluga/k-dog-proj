"""Single DB-backed worker; requests only enqueue, browser lifetime is irrelevant."""

from contextlib import contextmanager
import hashlib
import json
import threading
import time

from fastapi import HTTPException

from app.analysis import (
    adopt, check_access, claim, guard, later, observations, session_snapshot,
    step_payload, validated_observation, validated_prepared, write_output,
)
from app.domain.contracts import Evidence, RunInput, VideoReference
from app.gemini import GeminiObserver, ProviderError
from app.media import MediaError, inspect_media
from app.observation_models import ObservationArtifact, PreparedInput
from app.storage import encode, now, uid


@contextmanager
def heartbeat(store, row):
    stop = threading.Event()

    def renew():
        while not stop.wait(30):
            try:
                guard(store, row["run_id"], row["claim_token"])
            except (HTTPException, OSError):
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


class Worker:
    def __init__(self, store, *, observer=None, probe=inspect_media):
        self.store = store
        # Injection is only a Python test seam; CLI/API never offer a fake provider.
        self.observer = observer if observer is not None else GeminiObserver()
        self.probe = probe

    def check(self, row):
        return guard(self.store, row["run_id"], row["claim_token"])

    def stage(self, row, stage, branch, validate, work):
        self.check(row)
        with self.store.connect() as db:
            previous = db.execute("SELECT * FROM steps WHERE run_id=? AND stage=? AND branch_key=? ORDER BY attempt DESC LIMIT 1",
                                  (row["run_id"], stage, branch)).fetchone()
        if previous and previous["status"] == "succeeded":
            return validate(step_payload(self.store, row, previous))
        if previous and previous["status"] == "failed" and not row.get("retry_failed", False):
            return None
        if previous and previous["status"] == "running":
            # The latest uncommitted attempt is eligible only before a new attempt exists.
            ref = f"runs/{row['run_id']}/{previous['step_id']}/output.json"
            try:
                payload = step_payload(self.store, row, previous, recover=True)
                parsed = validate(payload)
                output_hash = hashlib.sha256(self.store.path(ref).read_bytes()).hexdigest()
                adopt(self.store, row, previous, ref, output_hash, payload.get("usage", {}))
                return parsed
            except (HTTPException, ValueError, KeyError, OSError):
                self.check(row)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE steps SET status='abandoned',usage_json=?,updated_at=? WHERE step_id=? AND status='running'",
                               (encode({"code": "worker_interrupted", "billing_uncertain": stage == "observe"}), now(), previous["step_id"]))
        attempt = previous["attempt"] + 1 if previous else 1
        if attempt > 3:
            return None
        if previous and previous["status"] == "retry_wait" and previous["retry_at"] > now():
            return None
        # Schema repair has its own one-repair cap inside the shared three-attempt budget.
        if stage == "observe":
            with self.store.connect() as db:
                history = [json.loads(s[0]) for s in db.execute(
                    "SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=?", (row["run_id"], stage, branch))]
            if sum(s.get("code") == "observation_schema_invalid" for s in history) >= 2:
                return None
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
            step = {"step_id": uid(), "claim_token": row["claim_token"], "attempt": attempt}
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,lease_expires_at,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,'running',?,?,?,?)",
                       (step["step_id"], row["run_id"], stage, branch, attempt, row["claim_token"], later(180), now(), now()))
        try:
            payload = work(step)
            parsed = validate(payload)
            self.check(row)
            ref, output_hash = write_output(self.store, row, step, payload)
            adopt(self.store, row, step, ref, output_hash, payload.get("usage", {}))
            return parsed
        except ProviderError as exc:
            usage = {**exc.usage, "code": exc.code, "billing_uncertain": exc.uncertain}
            with self.store.connect() as db:
                schema_failures = sum(json.loads(s[0]).get("code") == "observation_schema_invalid" for s in db.execute(
                    "SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=?", (row["run_id"], stage, branch)))
            retry = exc.retryable and attempt < 3 and not (exc.code == "observation_schema_invalid" and schema_failures >= 1)
            self.fail(row, step, "retry_wait" if retry else "failed", usage,
                      later(max(exc.delay, 10 * 2 ** (attempt - 1))) if retry else None)
        except MediaError as exc:
            self.fail(row, step, "failed", {"code": str(exc)}, None)
        except (ValueError, KeyError):
            self.fail(row, step, "failed", {"code": "artifact_invalid"}, None)
        return None

    def fail(self, row, step, status, usage, retry_at):
        self.check(row)
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running":
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
            db.execute("UPDATE steps SET status=?,usage_json=?,retry_at=?,updated_at=? WHERE step_id=? AND claim_token=? AND status='running'",
                       (status, encode(usage), retry_at, now(), step["step_id"], row["claim_token"]))

    def prepare(self, row, step):
        manifest, session = session_snapshot(row)
        config = json.loads(row["config_snapshot_json"])
        media, videos, errors = [], [], {}
        for video in session.videos:
            self.check(row)
            ref = f"runs/{row['run_id']}/{step['step_id']}/{video.video_id}.mp4"
            try:
                info = self.probe(self.store.path(video.storage_ref), video, self.store.path(ref), ref)
            except MediaError as exc:
                errors[video.video_id] = str(exc)
                continue
            media.append(info)
            videos.append(VideoReference(video_id=video.video_id, camera_id=video.camera_id,
                          sha256=video.sha256, storage_ref=video.storage_ref,
                          duration_sec=info.duration_sec, audio_status=info.audio_status))
        if not videos:
            raise MediaError("사용 가능한 영상이 없습니다. 미디어 파일과 FFmpeg 설치를 확인하세요.")
        run = RunInput(run_id=row["run_id"], case_id=row["case_id"], event_id=manifest.event_id,
                       participant_id=manifest.participant_id, session_id=row["session_id"],
                       input_revision=row["input_revision"], catalog_version=config["catalog_version"],
                       pipeline_version=config["pipeline_version"], prompt_version=config["prompt_version"],
                       config_version=config["config_version"], scoring_rule_version="pending-v1",
                       report_mapping_version="pending-v1", survey=session.survey, videos=tuple(videos))
        return PreparedInput(run_input=run, media=media, errors=errors).model_dump(mode="json")

    def observe(self, row, step, prepared, info):
        _, session = session_snapshot(row)
        config = json.loads(row["config_snapshot_json"])
        video = next(v for v in prepared.run_input.videos if v.video_id == info.video_id)
        path = self.store.path(info.storage_ref)
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != info.sha256:
                raise MediaError("분석용 영상 해시가 변경되었습니다.")
        context = {"items": config["catalog_items"], "route_note": session.route_note,
                   "capture_mode": session.capture_mode, "duration_sec": info.duration_sec,
                   "audio_status": info.audio_status, "sampling_fps": config["fps"]}
        response, usage = self.observer.observe(path, info, config, context, lambda: self.check(row))
        try:
            evidence = [Evidence(evidence_id=f"ev-{step['step_id']}-{index:04}", run_id=row["run_id"],
                        case_id=row["case_id"], session_id=row["session_id"], video_id=video.video_id,
                        camera_id=video.camera_id, segment_id=item.segment_id,
                        source_start_sec=item.start_sec + video.clip_offset_sec,
                        source_end_sec=item.end_sec + video.clip_offset_sec, subject=item.subject,
                        modality=item.modality, observation=item.observation,
                        candidate_item_ids=tuple(item.candidate_item_ids),
                        quality_flags=tuple(dict.fromkeys(item.quality_flags + info.quality_flags + ["sampling_1fps"])) )
                        for index, item in enumerate(response.observations, 1)]
            artifact = ObservationArtifact(run_id=row["run_id"], video_id=video.video_id, evidence=evidence,
                        unconfirmed_conditions=response.unconfirmed_conditions, usage=usage)
            validated_observation(artifact.model_dump(mode="json"), prepared.run_input, video.video_id)
        except ValueError:
            raise ProviderError("observation_schema_invalid", retryable=True, usage=usage) from None
        return artifact.model_dump(mode="json")

    def process(self, row):
        prepared = self.stage(row, "prepare", "session", lambda p: validated_prepared(row, p),
                              lambda step: self.prepare(row, step))
        if prepared:
            reused = {entry["video_id"] for entry in json.loads(row["reuse_manifest_json"])}
            with self.store.connect() as db:
                observations(self.store, db, row, prepared)
            for info in prepared.media:
                if info.video_id in reused:
                    continue
                observed = self.stage(row, "observe", info.video_id,
                           lambda p, video_id=info.video_id: validated_observation(p, prepared.run_input, video_id),
                           lambda step, info=info: self.observe(row, step, prepared, info))
                if observed is None:
                    with self.store.connect() as db:
                        failed = db.execute("SELECT usage_json FROM steps WHERE run_id=? AND stage='observe' AND branch_key=? ORDER BY attempt DESC LIMIT 1",
                                            (row["run_id"], info.video_id)).fetchone()
                    if failed and json.loads(failed[0]).get("code") == "developer_settings_required":
                        break
            with self.store.connect() as db:
                artifacts = observations(self.store, db, row, prepared)
            if {a.video_id for a in artifacts} == {m.video_id for m in prepared.media}:
                evidence = [e.model_dump(mode="json") for a in artifacts for e in a.evidence]
                config = json.loads(row["config_snapshot_json"])
                related = {item["item_id"]: [e["evidence_id"] for e in evidence if item["item_id"] in e["candidate_item_ids"]]
                           for item in config["catalog_items"]}
                bundle = {"run_id": row["run_id"], "evidence": evidence, "item_evidence_ids": related,
                          "unobserved_item_ids": [item for item, ids in related.items() if not ids],
                          "quality_flags": ["cameras_not_synchronized", "no_cross_camera_count_aggregation"],
                          "unconfirmed_conditions": [flag for a in artifacts for flag in a.unconfirmed_conditions]}

                def validate_bundle(payload):
                    if payload != bundle:
                        raise ValueError("evidence bundle does not match adopted observations")
                    return payload

                self.stage(row, "integrate", "session", validate_bundle, lambda step: bundle)
        self.check(row)
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
            steps = db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY attempt", (row["run_id"],)).fetchall()
            latest = {(s["stage"], s["branch_key"]): s for s in steps}
            codes = [json.loads(s["usage_json"]).get("code", "") for s in latest.values()]
            if any(s["status"] == "retry_wait" for s in latest.values()):
                status = "retry_wait"
            elif "developer_settings_required" in codes:
                status = "settings_required"
            elif not prepared:
                status = "failed"
            elif prepared.errors or any(s["status"] != "succeeded" for s in latest.values()):
                status = "partial_failed"
            else:
                status = "observed"
            # Never change cases.display_run_id at completion (F-04).
            integrated = latest.get(("integrate", "session"))
            db.execute("UPDATE runs SET status=?,result_ref=?,result_hash=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=? AND claim_token=?",
                       (status, integrated["output_ref"] if integrated else None, integrated["output_hash"] if integrated else None,
                        now(), row["run_id"], row["claim_token"]))

    def once(self):
        row = claim(self.store)
        if row is None:
            return False
        try:
            with heartbeat(self.store, row):
                self.process(row)
        except (HTTPException, OSError, ValueError, KeyError):
            with self.store.connect(write=True) as db:
                current = db.execute("SELECT * FROM cases WHERE case_id=?", (row["case_id"],)).fetchone()
                consent = json.loads(current["consent_json"] or "{}")
                stopped = current["deletion_requested"] or not consent.get("video_analysis") or not consent.get("external_ai")
                db.execute("UPDATE runs SET status=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? "
                           "WHERE run_id=? AND claim_token=? AND status='running'",
                           ("stopped" if stopped else "failed", now(), row["run_id"], row["claim_token"]))
        return True

    def run(self):
        while True:
            if not self.once():
                time.sleep(2)
