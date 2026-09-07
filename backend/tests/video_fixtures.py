"""Synthetic direct-video output; never installed in production packages."""

from app.observation_models import LedgerResponse, VideoResponse


def ledger_response(context, events=None):
    """Facts only. Voiced events appear only when the synthetic media has audio."""
    if events is None:
        # Short synthetic clips must still fit; 2.5s of events scale into the actual duration.
        scale = min(1.0, float(context.get("duration_sec") or 4.0) / 4.0)
        def at(start, end):
            return {"start_sec": round(start * scale, 3), "end_sec": round(end * scale, 3)}
        events = [{"step": "entry", "kind": "other", **at(0.0, 1.0), "subject": "dog",
                   "modality": "video", "command": "none", "observation": "가상 사건: 입장", "quality_flags": []}]
        if context.get("audio_status") == "present":
            events += [
                {"step": "command_1", "kind": "command_utterance", **at(1.0, 2.0),
                 "subject": "owner", "modality": "audio_video", "command": "c1",
                 "observation": "가상 사건: 보호자가 앉아를 1회 말함", "quality_flags": []},
                {"step": "command_1", "kind": "dog_performance", **at(2.0, 2.5),
                 "subject": "dog", "modality": "video", "command": "none",
                 "observation": "가상 사건: 개가 앉음", "quality_flags": []}]
    return LedgerResponse.model_validate({"events": events, "unconfirmed_conditions": ["synthetic_test_only"]})


def video_response(context, choices=None):
    choices = choices if choices is not None else {"BS-01": "BS-01:S1"}
    observations, items = [], []
    for item in context["items"]:
        option = choices.get(item["item_id"])
        indices = []
        if option:
            observations.append({"segment_id": "entry", "start_sec": 1.0, "end_sec": 2.0,
                "subject": "owner" if item["item_id"].startswith("OWN-") else "dog", "modality": "video",
                "observation": "가상 관찰: 입장 시 이동", "candidate_item_ids": [item["item_id"]], "quality_flags": []})
            indices = [len(observations)]
        items.append({"item_id": item["item_id"], "status": "scored" if option else "not_visible",
            "selected_option_id": option, "observation_indices": indices, "reason": "합성 시험 판단" if option else "이 시야에서 확인 불가",
            "coverage": "sufficient" if option else "none", "coverage_reason": "합성 시험의 해당 구간 관찰 범위",
            "measurements": []})
    return VideoResponse.model_validate({"observations": observations, "unconfirmed_conditions": ["synthetic_test_only"], "items": items})
