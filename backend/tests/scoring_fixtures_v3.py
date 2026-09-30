"""Synthetic source-time records for source-defined calculation tests, not real ratings."""

import hashlib

from app.domain.recording_v3 import WALK_PHASES
from app.domain.sheets_v3 import SheetDocumentV3
from app.input_models_v3 import SessionV3
from app.preprocess_v3 import ASSET_HASHES, CATALOG, window_plan
from app.storage import encode


def fixture(values, *, events=(), alone_end=110, rater_kind="human"):
    spans = [("entry", 0, 30), ("baseline", 30, 50), ("alone", 50, alone_end), ("reunion", alone_end, alone_end + 30),
             ("ignore", 140, 160), ("walk", 162, 192), ("stranger", 198, 228), ("exit", 230, 260)]
    session = SessionV3.model_validate_json(encode({"session_id": "session1", "note": "독립 합성 fixture", "survey_version": "survey-20260929-v3",
        "protocol_version": "protocol-20260929-v3", "protocol_source": "new_session", "survey": {f"s{i:02}": None for i in range(1, 29)},
        "videos": [{"video_id": "video1", "original_name": "synthetic.mp4", "storage_ref": "videos/video1.mp4", "sha256": "a" * 64, "size_bytes": 1}],
        "recording": {"video_id": "video1", "confirmed": True, "segments": [{"segment": key, "video_id": "video1", "start_sec": start, "end_sec": end,
            **({"state": "shortened", "reason": "실제 단축"} if key == "alone" and alone_end != 110 else {})} for key, start, end in spans],
            "walk_phases": [{"phase": phase, "video_id": "video1", "start_sec": 162 + i * 5, "end_sec": 167 + i * 5} for i, phase in enumerate(WALK_PHASES)],
            "events": [{"event_id": "entry-stop", "kind": "object_stop", "video_id": "video1", "segment": "entry", "status": "observed", "seconds": 15, "end_seconds": 20, "note": "실제 정지"},
                       {"event_id": "exit-stop", "kind": "object_stop", "video_id": "video1", "segment": "exit", "status": "observed", "seconds": 245, "end_seconds": 250, "note": "실제 정지"}, *events]}}))
    plan = window_plan(session)
    windows = {item["window_id"]: item for item in plan["windows"]}
    observations = []
    for code, raw in values.items():
        changes = raw if isinstance(raw, dict) else {"value": raw}
        item = next(item for item in CATALOG.items if item.code == code)
        window = next((windows[key] for key in item.windows if windows[key]["status"] in ("available", "partial")), None)
        if window and window["start_sec"] is None:
            window_range = next(part for part in plan["windows"] if part["window_id"] == window["window_id"] + "_before")
        else:
            window_range = window
        evidence = []
        if window_range and window_range["start_sec"] is not None:
            start, end = window_range["start_sec"], min(window_range["start_sec"] + 1, window_range["end_sec"])
            evidence = [{"video_id": "video1", "video_sha256": "a" * 64, "window_id": window["window_id"],
                         "start_seconds": start, "end_seconds": end, "observed_seconds": end - start, "note": "합성 실제 시각 근거"}]
        value = changes.get("value")
        observations.append({"code": code, "status": "observed" if value is not None else "unobserved", "reason": None if value is not None else "원값 미관찰",
            "opportunity": "present", "validity": "valid", "evidence": evidence,
            **({"latency_not_occurred": value == 99, "actual_latency_seconds": None if value == 99 else value} if code == "개32" and value is not None else {}), **changes})
    source = {"input_revision": 1, "input": {"manifest_ref": "inputs/fixture.json", "manifest_hash": "b" * 64},
              "catalog_hash": ASSET_HASHES["catalog_hash"], "protocol_hash": ASSET_HASHES["protocol_hash"], "window_rules_hash": ASSET_HASHES["rules_hash"],
              "session": session.model_dump(mode="json"), "windows": plan["windows"]}
    return SheetDocumentV3.model_validate_json(encode({"revision": 1, "state": "submitted", "assigned_username": "reviewer", "rater_name": "합성 전문가",
        "purpose": "independent", "active": True, "actor": "reviewer", "recorded_at": "2026-10-01T00:00:00+09:00", "change_reason": "합성 원자료 확정",
        "source": source, "source_hash": hashlib.sha256(encode(source).encode()).hexdigest(),
        "sheet": {"sheet_id": "sheet1", "case_id": "case1", "session_id": "session1", "rater_id": "rater1", "rater_kind": rater_kind, "observations": observations}}))


def event(kind, seconds, segment, **changes):
    return {"event_id": kind, "kind": kind, "video_id": "video1", "segment": segment, "status": "observed", "seconds": seconds, "note": "합성 실제 사건", **changes}
