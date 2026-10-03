"""Read-only S1 benchmark preparation and evidence summary; never calls a provider.

Run with the backend's locked Python environment. All input manifests, clock traces,
pairing confirmations and output summaries belong in protected runtime storage.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sqlite3
import sys
from types import SimpleNamespace
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pydantic import Field, model_validator

from app import analysis, exports_v4, preprocess_v4, report_runs_v4, run_v4
from app.domain.catalog_v4 import ContractV4, Hash, Text
from app.domain.exports_v4 import ExportSnapshotV4
from app.domain.preprocess_v4 import FileV4
from app.domain.runs_v4 import RunConfigV4
from app.input_models_v4 import ManifestV4
from app.storage import Store

VERSION = "benchmark-20261002-s1.1-1"
CONDITIONS = ("original_1gb_x1", "original_1gb_x3", "compressed_200_300mb_x3")
STAGES = ("pc_upload", "queue", "conversion", "probe_preprocess", "provider_upload", "provider_wait",
    "ai", "schema_repair", "calculation", "content", "html_pdf_publish")
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ReadOnlyStore(Store):
    """Use existing Store readers without running its startup migrations."""
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not (self.root/"kdog.sqlite3").is_file():
            raise ValueError("an existing S1 store is required")

    @contextmanager
    def connect(self, *, write=False):
        if write:
            raise ValueError("benchmark summarization cannot write to the app store")
        db = sqlite3.connect((self.root/"kdog.sqlite3").as_uri()+"?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()


class Interval(ContractV4):
    stage: Literal[*STAGES]
    start: Seconds
    end: Seconds
    attempt: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("interval ends before it starts")
        return self


class ClockTrace(ContractV4):
    """One observer clock, in elapsed seconds; cross-machine clocks cannot be mixed."""
    version: Literal["benchmark-clock-1"] = "benchmark-clock-1"
    ai_run_id: Text
    report_run_id: Text | None = None
    clock_id: Text
    observer: Text
    started_at_utc: Text
    server_receive_start: Seconds
    pdf_published: Seconds | None = None
    stages: tuple[Interval, ...]

    @model_validator(mode="after")
    def ordered(self):
        from datetime import datetime
        stamp = datetime.fromisoformat(self.started_at_utc)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError("clock origin must be UTC with an explicit offset")
        if self.pdf_published is not None and self.pdf_published < self.server_receive_start:
            raise ValueError("publication precedes server reception")
        if any(row.stage != "pc_upload" and row.start < self.server_receive_start or self.pdf_published is not None and row.end > self.pdf_published for row in self.stages):
            raise ValueError("stage is outside the measured pipeline interval")
        return self


class RunPin(ContractV4):
    run_id: Text
    input_hash: Hash
    config_hash: Hash


class MediaAlignment(ContractV4):
    video_sha256: Hash
    camera_id: Text
    common_start: Seconds
    common_end: Seconds
    source_offset_seconds: Annotated[float, Field(allow_inf_nan=False)]
    duration_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    fps: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    video_codec: Text
    has_audio: bool
    parent_hashes: tuple[Hash, ...] = ()
    conversion_tool: Text | None = None
    conversion_settings_hash: Hash | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.common_end <= self.common_start:
            raise ValueError("actual common interval must be positive")
        if self.common_start+self.source_offset_seconds < 0 or self.common_end+self.source_offset_seconds > self.duration_seconds:
            raise ValueError("aligned observation is outside the actual source duration")
        if self.parent_hashes and (not self.conversion_tool or not self.conversion_settings_hash):
            raise ValueError("derived media requires conversion tool and settings provenance")
        return self


class Pairing(ContractV4):
    case_id: Text
    session_id: Text
    same_content_id: Text
    confirmed_by: Text
    confirmed_at: Text
    basis: Text
    media: tuple[MediaAlignment, ...]


class Condition(ContractV4):
    key: Literal[*CONDITIONS]
    # The operator states what 'about 1 GB' means before measuring. No invented tolerance.
    size_range_bytes: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]] | None = None
    missing_reason: Text = "실제 영상·동의·실행 로그 미수령"

    @model_validator(mode="after")
    def bounds(self):
        if self.size_range_bytes and self.size_range_bytes[0] > self.size_range_bytes[1]:
            raise ValueError("size range is reversed")
        if self.key == CONDITIONS[2] and self.size_range_bytes not in (None, (200_000_000, 300_000_000)):
            raise ValueError("200–300 MB uses decimal bytes; do not silently replace this condition")
        return self


class Trial(ContractV4):
    condition: Literal[*CONDITIONS]
    pair_id: Text
    repeat: Annotated[int, Field(ge=1)]
    case_id: Text
    session_id: Text
    ai: RunPin
    report: RunPin | None = None
    pairing: FileV4
    clock: FileV4 | None = None
    export: FileV4 | None = None
    cache: Literal["cold", "explicit_reuse"]
    fps_condition: Literal["source", "compression_fps_kept", "fps_reduced"]
    pc_upload_mode: Literal["one_pc", "three_pc_concurrent", "unmeasured"]
    provider_execution: Literal["serial", "parallel", "unmeasured"] = "serial"


class BenchmarkManifest(ContractV4):
    version: Literal["benchmark-20261002-s1.1-1"] = VERSION
    sample_kind: Literal["synthetic", "field"]
    app_commit: Text
    environment: dict[str, Text]
    planned_repetitions: Annotated[int, Field(ge=1)] | None = None
    planned_provider_call_budget: Annotated[int, Field(ge=0)] | None = None
    conditions: tuple[Condition, ...]
    trials: tuple[Trial, ...] = ()

    @model_validator(mode="after")
    def complete(self):
        if sorted(row.key for row in self.conditions) != sorted(CONDITIONS):
            raise ValueError("all three required conditions must appear exactly once")
        keys = [(row.condition, row.pair_id, row.repeat, row.cache, row.fps_condition) for row in self.trials]
        if len(keys) != len(set(keys)) or len({row.ai.run_id for row in self.trials}) != len(self.trials):
            raise ValueError("a run cannot be counted as multiple trials")
        if self.trials and (self.planned_repetitions is None or self.planned_provider_call_budget is None):
            raise ValueError("declare repetitions and call budget before interpreting measurements")
        if self.trials and self.sample_kind == "field" and (not re.fullmatch(r"[0-9a-f]{40}", self.app_commit) or
                not {"server", "cpu", "memory", "network", "os"} <= self.environment.keys() or
                any(self.environment[key] == "실측 전 기록" for key in ("server", "cpu", "memory", "network", "os") if key in self.environment)):
            raise ValueError("field measurements require the exact app commit and recorded server/network environment")
        if any(row.repeat > self.planned_repetitions for row in self.trials):
            raise ValueError("trial exceeds the declared repetition plan")
        return self


def template():
    return {"version": VERSION, "sample_kind": "field", "app_commit": "측정할 앱 commit 입력",
        "environment": {key: "실측 전 기록" for key in ("server", "cpu", "memory", "network", "os")},
        "planned_repetitions": None, "planned_provider_call_budget": None,
        "conditions": [{"key": key, "size_range_bytes": [200_000_000, 300_000_000] if key == CONDITIONS[2] else None,
            "missing_reason": "실제 영상·동의·실행 로그 미수령"} for key in CONDITIONS], "trials": []}


def union_seconds(intervals):
    total = 0.0
    end = None
    for left, right in sorted(intervals):
        total += right - left if end is None else max(0.0, right - max(left, end))
        end = right if end is None else max(end, right)
    return total


def timing(trace):
    grouped = {stage: [(row.start, row.end) for row in trace.stages if row.stage == stage] for stage in STAGES}
    ai = [entry for stage in ("provider_upload", "provider_wait", "ai", "schema_repair") for entry in grouped[stage]]
    all_intervals = [(row.start, row.end) for row in trace.stages]
    return {"server_receive_to_pdf_seconds": None if trace.pdf_published is None else trace.pdf_published-trace.server_receive_start,
        "pc_upload_to_pdf_seconds": trace.pdf_published-min(left for left, _ in grouped["pc_upload"]) if trace.pdf_published is not None and grouped["pc_upload"] else None,
        "ai_span_seconds": max(right for _, right in ai)-min(left for left, _ in ai) if ai else None,
        "ai_active_union_seconds": union_seconds(ai) if ai else None,
        "stage_sum_seconds": sum(right-left for left, right in all_intervals),
        "stage_union_seconds": union_seconds(all_intervals),
        "by_stage": {stage: {"measured": bool(values), "sum_seconds": sum(right-left for left, right in values) if values else None,
            "union_seconds": union_seconds(values) if values else None, "interval_count": len(values)} for stage, values in grouped.items()},
        "scope": "server reception start to PDF publication; includes reception; stage sums are not wall-clock totals"}


def _read(store, pointer, model, stamps):
    return model.model_validate_json(report_runs_v4._read_file(store, pointer, stamps))


def _run(store, pin, kind, trial):
    with store.connect() as db:
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (pin.run_id,)).fetchone()
        if not row or (row["kind"], row["case_id"], row["session_id"], row["input_hash"], analysis.digest(json.loads(row["config_snapshot_json"]))) != (
                kind, trial.case_id, trial.session_id, pin.input_hash, pin.config_hash):
            raise ValueError("run identity, input or configuration differs from the explicit manifest")
        return dict(row)


def _access(store, trial, user):
    with store.connect() as db:
        account = db.execute("SELECT active,role FROM users WHERE username=?", (user.username,)).fetchone()
        if not account or not account["active"] or account["role"] not in ("operator", "admin"):
            raise ValueError("active operator permission required")
        case = store.case(db, trial.case_id)
        source = store.manifest(case)
        if not isinstance(source, ManifestV4) or source.consents.analysis_feedback != "confirmed":
            raise ValueError("current analysis consent must be confirmed")
        if not any(row.session_id == trial.session_id for row in source.sessions):
            raise ValueError("session no longer belongs to this case")


def quality(snapshot, ai_run_id):
    """S14 owns denominator rules; only this run's immutable first AI sheet participates."""
    indices = [index for index, member in enumerate(snapshot.members) if member.sheet.sheet.rater_kind != "ai" or
        member.sheet.ai_run_id == ai_run_id and member.sheet.origin == "ai_service" and member.sheet.revision == 1 and not member.sheet.previous]
    selected = {"members": tuple(snapshot.members[index] for index in indices)}
    selected["surveys"] = tuple(snapshot.surveys[index] for index in indices)
    rows = exports_v4.tables(snapshot.model_copy(update=selected))
    items = []
    for entry in rows["item_denominators"]:
        code = entry["code"]
        pairs = [row for row in rows["independent_pairs"] if row["code"] == code and row["included"]]
        items.append({**entry, "category_equal_rate": entry["equal_n"]/entry["valid_pair_n"] if entry["valid_pair_n"] and entry["value_type"] != "count" else None,
            "count_absolute_difference_sum": sum(abs(row["difference"]) for row in pairs) if pairs and entry["value_type"] == "count" else None})
    excluded = Counter(reason for row in rows["independent_pairs"] if not row["included"] for reason in json.loads(row["excluded_reasons"]))
    return {"status": "valid_pairs_available" if any(row["valid_pair_n"] for row in items) else "no_valid_human_reference",
        "items": items, "excluded_pair_reasons": dict(excluded), "reference_only_sources_in_denominator": 0,
        "event_omission_duplication": "unmeasured_requires_confirmed_event_reference",
        "final_type_sentence_quality": "unmeasured_requires_human_semantic_review", "accuracy_threshold": None}


def check_offset(recording, video_id, declared):
    actual = recording.offset(video_id)
    if actual is None or declared != actual:
        raise ValueError("pairing requires the confirmed recording synchronization offset")


def verified_export(store, pointer, user, stamps):
    snapshot = _read(store, pointer, ExportSnapshotV4, stamps)
    with store.connect() as db:
        record = exports_v4._record(db, snapshot.export_id)
        if (record["ref"], record["hash"]) != (pointer.ref, pointer.hash):
            raise ValueError("quality reference is not the adopted S14 export snapshot")
    exports_v4.guard(store, snapshot, user)
    stamps.update(exports_v4._files(store, snapshot))
    return snapshot


def inspect_trial(store, trial, user, stamps):
    _access(store, trial, user)
    row = _run(store, trial.ai, "s1", trial)
    source = run_v4.snapshot_for(row)
    preprocess_v4.verified_batch(store, trial.case_id, trial.session_id,
        FileV4(ref=source.preprocess.ref, hash=source.preprocess.hash), user.username,
        expected_input=FileV4(ref=source.input.manifest_ref, hash=source.input.manifest_hash), expected_revision=source.input_revision)
    stamps.update(run_v4.verify_files(store, source))
    config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
    pairing = _read(store, trial.pairing, Pairing, stamps)
    if (pairing.case_id, pairing.session_id) != (trial.case_id, trial.session_id):
        raise ValueError("pairing belongs to a different case or session")
    files = {(file.ref, file.hash) for file in source.batch.source_files}
    videos = [video for video in source.session.videos if (video.storage_ref, video.sha256) in files]
    if not videos or len({video.camera_id for video in videos}) != len(videos):
        raise ValueError("camera source mapping is incomplete or duplicated")
    aligned = {(entry.video_sha256, entry.camera_id): (entry.common_start, entry.common_end) for entry in pairing.media}
    if len(aligned) != len(pairing.media) or set(aligned) != {(video.sha256, video.camera_id) for video in videos}:
        raise ValueError("pairing must name every actual input hash and camera exactly once")
    for video in videos:
        entry = next(item for item in pairing.media if item.video_sha256 == video.sha256)
        if set(entry.parent_hashes) != {parent.sha256 for parent in getattr(video, "parents", ())}:
            raise ValueError("pairing changes the pinned media parent lineage")
        check_offset(source.session.recording_s1, video.video_id, entry.source_offset_seconds)
    with store.connect() as db:
        steps = [dict(step) for step in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY created_at,attempt", (row["run_id"],))]
    reserved = sum(bool(step["call_reserved"]) for step in steps)
    if trial.provider_execution == "parallel":
        raise ValueError("current S1 worker executes provider requests serially; parallel support is unmeasured")
    if (trial.cache == "cold") != (not json.loads(row["reuse_manifest_json"]) and source.batch.reuse_manifest is None):
        raise ValueError("cold and explicit reuse executions cannot be mislabeled")
    if trial.report:
        report = _run(store, trial.report, "report_v4", trial)
        report_source = report_runs_v4.snapshot_for(report)
        if report_source.final_document.basic_document.input_document.ai_run_id != trial.ai.run_id:
            raise ValueError("report does not use the selected AI run")
        if report["status"] == "succeeded":
            report_runs_v4.download(store, trial.case_id, trial.session_id, trial.report.run_id, "manifest", user)
    trace = _read(store, trial.clock, ClockTrace, stamps) if trial.clock else None
    if trace and (trace.ai_run_id, trace.report_run_id) != (trial.ai.run_id, trial.report.run_id if trial.report else None):
        raise ValueError("clock trace belongs to different executions")
    if trace and trace.pdf_published is not None and (not trial.report or report["status"] != "succeeded"):
        raise ValueError("unissued output cannot supply a PDF publication time")
    result_quality = {"status": "no_valid_human_reference", "items": [], "reference_only_sources_in_denominator": 0}
    if trial.export:
        exported = verified_export(store, trial.export, user, stamps)
        if any((member.selection.case_id, member.selection.session_id) != (trial.case_id, trial.session_id) for member in exported.members):
            raise ValueError("quality export mixes benchmark cases or sessions")
        result_quality = quality(exported, trial.ai.run_id)
    usage = [json.loads(step["usage_json"]) for step in steps]
    result = {"run_state": row["status"], "camera_count": len(videos), "file_sizes_bytes": [video.size_bytes for video in videos],
        "source_metadata": source.batch.source_metadata, "catalog_and_rule_hashes": source.batch.asset_hashes,
        "configuration_hash": trial.ai.config_hash, "models": sorted({(stage.provider, stage.model) for stage in config.stages if stage.provider_call}),
        "prompt_hashes": sorted({hashlib.sha256(stage.prompt.encode()).hexdigest() for stage in config.stages if stage.provider_call}),
        "request_fps": sorted({stage.request_fps for stage in config.stages if stage.provider_call and stage.request_fps is not None}),
        "production_fps_policy": sorted({stage.production_fps for stage in config.stages if stage.provider_call}),
        "encoder_version": source.batch.encoder_version, "reserved_calls": reserved,
        "attempts": len(steps), "retried_attempts": sum(step["attempt"] > 1 for step in steps),
        "billing_uncertain_attempts": sum(bool(entry.get("billing_uncertain")) for entry in usage),
        "known_cost_usd": sum(entry["cost_usd"] for entry in usage if type(entry.get("cost_usd")) in (int, float) and math.isfinite(entry["cost_usd"])),
        "unknown_cost_attempts": sum(bool(step["call_reserved"]) and (type(entry.get("cost_usd")) not in (int, float) or not math.isfinite(entry["cost_usd"])) for step, entry in zip(steps, usage)),
        "provider_meter_attempts": [{key: item[key] for key in ("attempt", "input_tokens", "output_tokens", "total_tokens", "token_meters", "billing_uncertain")}
            for item in run_v4.view(store, trial.ai.run_id, user)["steps"] if item["call_reserved"]],
        "timing": timing(trace) if trace else None, "quality": result_quality,
        "cache": trial.cache, "fps_condition": trial.fps_condition, "pc_upload_mode": trial.pc_upload_mode,
        "provider_execution": trial.provider_execution, "multiview_input_count": len(videos),
        "insv": {"storage": "implemented_not_field_measured", "conversion": "unmeasured", "direct_read": "unsupported_storage_only", "accuracy": "unmeasured"}}
    # Paths/names/IDs embedded in probe metadata are private; emit only technical fields.
    safe_fields = {"duration_seconds", "fps", "width", "height", "video_codec", "has_audio", "conversion_tool", "conversion_settings_hash"}
    result["source_metadata"] = [{key: value for key, value in entry.model_dump(mode="json").items() if key in safe_fields} for entry in pairing.media]
    return result, pairing


def summarize(manifest, store=None, user=None):
    manifest = BenchmarkManifest.model_validate_json(manifest.model_dump_json())
    stamps, results, pairs, intervals, frame_rates = {}, [], {}, {}, {}
    for index, trial in enumerate(manifest.trials):
        result, pairing = inspect_trial(store, trial, user, stamps)
        pair = (trial.case_id, trial.session_id, pairing.same_content_id)
        if trial.pair_id in pairs and pairs[trial.pair_id] != pair:
            raise ValueError("a comparison pair must describe the same case, session and confirmed content")
        pairs[trial.pair_id] = pair
        for entry in pairing.media:
            key = (trial.pair_id, entry.camera_id)
            extent = (entry.common_start, entry.common_end)
            if key in intervals and intervals[key] != extent:
                raise ValueError("paired recordings do not cover the same actual common interval")
            intervals[key] = extent
            frame_rates.setdefault(key, []).append((trial.fps_condition, entry.fps))
        result.update(trial=f"T{index+1:03}", pair=f"P{list(pairs).index(trial.pair_id)+1:03}", repeat=trial.repeat, condition=trial.condition)
        result["actual_common_intervals"] = {entry.camera_id: [entry.common_start, entry.common_end] for entry in pairing.media}
        results.append(result)
    for values in frame_rates.values():
        source_rates = {fps for kind, fps in values if kind == "source"}
        if len(source_rates) > 1 or any(kind == "compression_fps_kept" and source_rates and fps not in source_rates or
                kind == "fps_reduced" and source_rates and fps >= min(source_rates) for kind, fps in values):
            raise ValueError("declared retained/reduced FPS does not match the original recording")
    if sum(row["reserved_calls"] for row in results) > (manifest.planned_provider_call_budget or 0):
        raise ValueError("measured calls exceed the declared benchmark budget")
    rows = []
    for condition in manifest.conditions:
        trials = [row for row in results if row["condition"] == condition.key]
        required_count = 1 if condition.key == CONDITIONS[0] else 3
        accepted = [row for row in trials if row["camera_count"] == required_count and condition.size_range_bytes and
            all(condition.size_range_bytes[0] <= size <= condition.size_range_bytes[1] for size in row["file_sizes_bytes"])]
        timed = [row for row in accepted if row["timing"] and row["timing"]["server_receive_to_pdf_seconds"] is not None]
        # Do not merge cold/cache, FPS, PC-upload or provider concurrency conditions.
        groups = defaultdict(list)
        for row in timed:
            groups[(row["pair"], row["cache"], row["fps_condition"], row["pc_upload_mode"], row["provider_execution"], row["configuration_hash"])].append(row)
        variations = []
        for key, values in groups.items():
            wall = [row["timing"]["server_receive_to_pdf_seconds"] for row in values]
            variations.append({"pair": key[0], "cache": key[1], "fps_condition": key[2], "pc_upload_mode": key[3],
                "provider_execution": key[4], "configuration_hash": key[5], "n": len(wall), "min_seconds": min(wall),
                "max_seconds": max(wall), "mean_seconds": statistics.mean(wall),
                "sample_stdev_seconds": statistics.stdev(wall) if len(wall) > 1 else None})
        rows.append({"condition": condition.key, "status": "measured" if timed and manifest.sample_kind == "field" else "synthetic_only" if timed else "unmeasured",
            "reason": None if timed else "file_count_or_size_condition_not_confirmed" if trials and not accepted else "complete_clock_trace_missing" if trials else condition.missing_reason,
            "size_range_bytes": condition.size_range_bytes, "trials": [row["trial"] for row in trials], "repeat_groups": variations})
    for trial in manifest.trials:
        _access(store, trial, user)
        if trial.export:
            verified_export(store, trial.export, user, stamps)
    if store:
        report_runs_v4.check_stamps(store, stamps)
    return {"version": VERSION, "sample_kind": manifest.sample_kind, "app_commit": manifest.app_commit,
        "environment": manifest.environment, "conditions": rows, "trials": results, "real_measurement_complete": False,
        "insv_followup": {"storage": "field_unmeasured", "conversion": "field_unmeasured", "direct_read": "unsupported_storage_only", "accuracy": "field_unmeasured"},
        "accuracy_threshold": None, "note": "Recorded measurements are not accuracy approval or S16 field acceptance. Missing rows are never extrapolated."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--template", type=Path)
    inputs.add_argument("--schema", type=Path)
    inputs.add_argument("--manifest", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.template:
        target, result = args.template, template()
    elif args.schema:
        target, result = args.schema, {"manifest": BenchmarkManifest.model_json_schema(),
            "pairing_file": Pairing.model_json_schema(), "clock_file": ClockTrace.model_json_schema()}
    else:
        if not args.manifest or not args.output:
            parser.error("--manifest and --output are required")
        manifest_bytes = args.manifest.read_bytes()
        manifest = BenchmarkManifest.model_validate_json(manifest_bytes)
        if manifest.trials and (not args.data_dir or not args.actor):
            parser.error("measured trials require --data-dir and --actor")
        if args.data_dir and not (args.data_dir/"kdog.sqlite3").is_file():
            parser.error("--data-dir must be an existing S1 store")
        result = summarize(manifest, ReadOnlyStore(args.data_dir) if args.data_dir else None, SimpleNamespace(username=args.actor))
        target = args.output
        result["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(f"Saved {VERSION}; no provider or media processing was executed.")


if __name__ == "__main__":
    main()
