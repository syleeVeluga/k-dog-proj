"""Synthetic choices only. Never available as a production provider."""

import json

from app.evaluation_models import EvaluationResponse


class FakeEvaluator:
    def __init__(self):
        self.calls = []
        self.callback = None

    def evaluate(self, config, context, guard):
        guard()
        self.calls.append((config, context))
        if self.callback:
            return self.callback(config, context, guard)
        return evaluation_response(context), {"provider": "synthetic-test-only", "model": "synthetic-test-only", "input_tokens": 10}


def evaluation_response(context):
    items = []
    for item in context["items"]:
        evidence = [e["evidence_id"] for e in context["evidence"] if item["item_id"] in e["candidate_item_ids"]]
        scored = item["item_id"] == "BS-01" and evidence
        items.append({"item_id": item["item_id"], "status": "scored" if scored else "insufficient_evidence",
            "selected_option_id": item["options"][0]["option_id"] if scored else None,
            "evidence_ids": evidence, "reason": "가상 시험 선택지" if scored else "가상 자료에 해당 항목 관찰이 없습니다."})
    return EvaluationResponse.model_validate_json(json.dumps({"branch": context["branch"], "items": items}, ensure_ascii=False))
