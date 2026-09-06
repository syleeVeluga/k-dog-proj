"""Immutable developer versions; drafts and synthetic trials never enter case runs."""

import difflib
import hashlib
import json
import os
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.input_models import Model
from app.storage import encode, now, uid


Stage = Literal["observe", "dog", "owner", "report", "video"]


class StageConfig(Model):
    provider: Literal["gemini", "openai", "anthropic"]
    model: Annotated[str, Field(max_length=150, pattern=r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)?$")]
    prompt: Annotated[str, Field(min_length=1, max_length=24000)]
    max_output_tokens: Annotated[int, Field(ge=256, le=65536)]


class Pipeline(Model):
    observe: StageConfig
    dog: StageConfig
    owner: StageConfig
    report: StageConfig
    video: StageConfig | None = None
    evaluation_mode: Literal["per_video", "legacy"] = "per_video"
    fps: Annotated[float, Field(gt=0, le=10)] = 1.0
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 3
    evaluation_concurrency: Literal[1, 2] = 2
    max_ai_calls: Annotated[int, Field(ge=1, le=1000)] = 100

    @model_validator(mode="after")
    def observation_provider(self):
        if self.observe.provider != "gemini" or self.observe.model and not self.observe.model.startswith("gemini-"):
            raise ValueError("관찰은 Gemini 모델만 지원합니다.")
        if self.video is None:
            from app.video_evaluation import PROMPT
            self.video = StageConfig(provider="gemini", model=self.observe.model, prompt=PROMPT,
                                     max_output_tokens=self.observe.max_output_tokens)
        if self.video.provider != "gemini" or self.video.model and not self.video.model.startswith("gemini-"):
            raise ValueError("영상별 직접 평가는 Gemini 모델만 지원합니다.")
        return self


class DraftEdit(Model):
    expected_active: str
    config: Pipeline


class Activate(Model):
    expected_active: str


class TrialRequest(Model):
    stage: Stage
    mode: Literal["schema", "provider"] = "schema"


class Version(Model):
    version: str


class ActiveVersion(Model):
    active_version: str


class VersionHistory(Version):
    created_at: str
    actor: str


class KeyState(Model):
    provider: Literal["gemini", "openai", "anthropic"]
    reference: str
    available: bool


class KeyTest(Model):
    provider: Literal["gemini", "openai", "anthropic"]
    reference: str
    status: str


class TrialResult(Version):
    trial_id: str
    stage: Stage
    mode: Literal["schema", "provider"]
    created_at: str
    status: str
    sample: Literal["synthetic-v1"]
    usage: dict[str, int | str | bool]
    output: dict | None = None


class SettingsView(ActiveVersion):
    config: Pipeline
    versions: list[VersionHistory]
    trials: list[TrialResult]
    keys: list[KeyState]


class Difference(ActiveVersion, Version):
    config: Pipeline
    diff: str


def active(db):
    row = db.execute("SELECT detail_json FROM changes WHERE action='settings.activate' ORDER BY rowid DESC LIMIT 1").fetchone()
    return json.loads(row[0])["version"] if row else "legacy"


def load(store, db, version):
    row = db.execute("SELECT detail_json FROM changes WHERE action='settings.draft' AND target=?", (version,)).fetchone()
    if not row:
        raise HTTPException(404, "설정 버전을 찾을 수 없습니다.")
    link = json.loads(row[0])
    raw = store.path(link["ref"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != link["hash"]:
        raise HTTPException(409, "설정 파일 해시가 일치하지 않습니다.")
    return Pipeline.model_validate_json(raw)


def current(store, db):
    version = active(db)
    if version != "legacy":
        return version, load(store, db, version)
    from app.gemini import configuration
    from app.evaluation import active_configuration
    from app.reporting import active_report_configuration
    observation = configuration()
    _, evaluation = active_configuration(db, observation["model"])
    _, report = active_report_configuration(db, observation["model"])
    def stage(value):
        return {k: value[k] for k in ("provider", "model", "prompt", "max_output_tokens")}
    return version, Pipeline.model_validate({"observe": stage({"provider": "gemini", **observation}),
        "dog": stage(evaluation["dog"]), "owner": stage(evaluation["owner"]), "report": stage(report)})


def view(store):
    from app.secrets import available, state, PROVIDERS
    with store.connect() as db:
        version, config = current(store, db)
        versions = [{"version": r["target"], "created_at": r["happened_at"], "actor": r["actor"]}
                    for r in db.execute("SELECT * FROM changes WHERE action='settings.draft' ORDER BY rowid DESC")]
        trials = [json.loads(r[0]) for r in db.execute("SELECT detail_json FROM changes WHERE action='settings.trial' ORDER BY rowid DESC LIMIT 20")]
    return {"active_version": version, "config": config.model_dump(), "versions": versions, "trials": trials,
            "keys": [{"provider": p, "available": available(store, p), "reference": (state(store, p) or {}).get("reference", "environment")} for p in PROVIDERS]}


def save(store, value, actor):
    version = uid()
    with store.connect(write=True) as db:
        if active(db) != value.expected_active:
            raise HTTPException(409, "운영 버전이 변경되었습니다. 새로 조회하세요.")
        ref = f"settings/{version}.json"
        path = store.path(ref)
        path.parent.mkdir(exist_ok=True)
        raw = value.config.model_dump_json().encode()
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        store.audit(db, actor, version, "settings.draft", {"ref": ref, "hash": hashlib.sha256(raw).hexdigest()})
    return {"version": version}


def difference(store, version):
    with store.connect() as db:
        active_version, base = current(store, db)
        draft = load(store, db, version)
    return {"active_version": active_version, "version": version, "config": draft.model_dump(), "diff": "\n".join(difflib.unified_diff(
        json.dumps(base.model_dump(), ensure_ascii=False, indent=2).splitlines(),
        json.dumps(draft.model_dump(), ensure_ascii=False, indent=2).splitlines(), fromfile=active_version, tofile=version, lineterm=""))}


def activate(store, version, value, actor):
    with store.connect(write=True) as db:
        previous = active(db)
        if previous != value.expected_active:
            raise HTTPException(409, "운영 버전이 변경되었습니다. 새로 조회하세요.")
        config = load(store, db, version)
        stages = ("video", "report") if config.evaluation_mode == "per_video" else ("observe", "dog", "owner", "report")
        if any(not getattr(config, stage).model for stage in stages):
            raise HTTPException(422, "각 단계 모델을 지정하세요.")
        store.audit(db, actor, version, "settings.activate", {"version": version, "previous": previous})
    return {"active_version": version}


def apply_snapshot(store, db, snapshot):
    version, config = current(store, db)
    snapshot["evaluation_mode"] = config.evaluation_mode
    if config.evaluation_mode == "legacy" and version == "legacy":
        return
    # Hash only the relevant stage contents so unrelated edits do not invalidate reuse.
    def stage(value):
        data = value.model_dump()
        data["prompt_version"] = hashlib.sha256(encode(data).encode()).hexdigest()
        return data
    observation = stage(config.observe)
    snapshot.update(observation)
    snapshot.update(config_version=observation["prompt_version"], settings_version=version,
                    fps=config.fps, max_attempts=config.max_attempts,
                    evaluation_concurrency=config.evaluation_concurrency, max_ai_calls=config.max_ai_calls)
    snapshot["evaluation"] = {branch: stage(getattr(config, branch)) for branch in ("dog", "owner")}
    snapshot["report"] = stage(config.report)
    if config.evaluation_mode == "per_video":
        from app.video_evaluation import VERSION
        video = stage(config.video)
        snapshot.update(video)
        snapshot.update(pipeline_version=VERSION, config_version=video["prompt_version"], direct_video=True)


def trial(store, version, value, actor):
    from app.developer_sample import run_sample
    from app.gemini import ProviderError
    with store.connect() as db:
        config = load(store, db, version)
    result = {"trial_id": uid(), "version": version, "stage": value.stage, "mode": value.mode,
              "created_at": now(), "status": "schema_valid", "sample": "synthetic-v1", "usage": {}}
    if value.mode == "provider":
        with store.connect(write=True) as db:
            store.audit(db, actor, version, "settings.trial.start", {k: v for k, v in result.items() if k != "usage"})
        try:
            result["output"], result["usage"] = run_sample(store, config, value.stage)
            result["status"] = "provider_valid"
        except ProviderError as exc:
            result.update(status=exc.code, usage=exc.usage)
        except (ValueError, OSError, HTTPException):
            result["status"] = "sample_invalid"
    with store.connect(write=True) as db:
        store.audit(db, actor, version, "settings.trial", result)
    return result
