"""Synthetic direct-video output; never installed in production packages."""

from app.observation_models import VideoResponse


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
