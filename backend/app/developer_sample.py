"""One explicit provider call on generated, participant-free input; no production run."""

import hashlib
import json
from pathlib import Path
import tempfile

from app.domain.contracts import BehaviorCatalog, RunInput, SurveyCatalog
from app.evaluation import Evaluator, evaluation_context, make_evaluation
from app.gemini import GeminiObserver, ProviderError
from app.media import command, MediaError
from app.observation_models import MediaInfo
from app.reporting import Reporter, make_report
from app.scoring import RULES, survey_scores
from app.storage import REPO_ROOT


def run_sample(store, pipeline, stage):
    config = getattr(pipeline, stage).model_dump()
    catalog = BehaviorCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/behavior-v1.json").read_bytes())
    run = RunInput.model_validate_json(json.dumps({
        "run_id": "synthetic-run", "case_id": "synthetic-case", "event_id": "SYNTHETIC", "participant_id": "0000",
        "session_id": "synthetic-session", "input_revision": 1, "catalog_version": catalog.version,
        "pipeline_version": "synthetic-v1", "scoring_rule_version": RULES["version"], "report_mapping_version": "pending-v1",
        "prompt_version": "synthetic-v1", "config_version": "synthetic-v1",
        "survey": {f"q{i:02}": None for i in range(1, 31)}, "videos": [{"video_id": "synthetic-video", "camera_id": "CAM-1",
        "storage_ref": "synthetic/video.mp4", "sha256": "0" * 64, "duration_sec": 2.0, "audio_status": "absent"}]}))
    if stage in ("observe", "video"):
        with tempfile.TemporaryDirectory(prefix="kdog-developer-sample-") as directory:
            path = Path(directory) / "sample.mp4"
            try:
                command(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=2",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], timeout=30)
            except MediaError:
                raise ValueError("synthetic media unavailable") from None
            info = MediaInfo(video_id="synthetic-video", storage_ref="synthetic/video.mp4", sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size, duration_sec=2.0, codec="h264", width=320, height=240, audio_status="absent", mime_type="video/mp4", quality_flags=["audio_absent"])
            from app.video_evaluation import context
            from app.input_models import Session
            sample_context = context(catalog, Session(session_id="synthetic-session", capture_mode="unknown", route_note="",
                survey_version=catalog.version, survey=dict(run.survey), videos=[]), info, pipeline.fps)
            sample_context["sample"] = "synthetic gray frame; no dog, guardian or audio"
            response, usage = GeminiObserver(store).observe(path, info, {**config, "fps": pipeline.fps, "direct_video": stage == "video"},
                sample_context, lambda: None)
            if response.observations:
                raise ProviderError("observation_schema_invalid", usage=usage)
            if stage == "video":
                from app.video_evaluation import decisions, validate_items
                from app.observation_models import ObservationArtifact
                validate_items(ObservationArtifact(run_id=run.run_id, video_id=info.video_id, evidence=[],
                    unconfirmed_conditions=response.unconfirmed_conditions, usage=usage, video_items=decisions(response, [], catalog, info.duration_sec)), run, catalog)
            return response.model_dump(mode="json"), usage
    bundle = {"evidence": [], "quality_flags": [], "unconfirmed_conditions": ["synthetic empty evidence"]}
    if stage in ("dog", "owner"):
        response, usage = Evaluator(store).evaluate(config, evaluation_context(stage, catalog, bundle), lambda: None)
        try:
            return make_evaluation(response, usage, run, stage, catalog, ()).model_dump(mode="json"), usage
        except ValueError:
            raise ProviderError("evaluation_schema_invalid", usage=usage) from None
    survey_catalog = SurveyCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/survey-v1.json").read_bytes())
    response, usage = Reporter(store).write(config, {"scores": {"items": [], "domains": [], "status": "missing"},
        "survey": survey_scores(run.run_id, run.survey, survey_catalog).model_dump(mode="json"), "evidence": [],
        "mapping_status": "mapping_pending", "cross_type_status": "type_rule_pending"}, lambda: None)
    try:
        return make_report(response, {"run_id": run.run_id}, 1, set()).model_dump(mode="json"), usage
    except ValueError:
        raise ProviderError("evaluation_schema_invalid", usage=usage) from None
