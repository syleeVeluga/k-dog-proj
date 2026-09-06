"""Synthetic narration, never selected by the application or CLI."""
from app.report_models import Narration


class FakeReporter:
    def __init__(self):
        self.calls = []
        self.callback = None

    def write(self, config, context, guard):
        guard()
        self.calls.append((config, context))
        if self.callback:
            return self.callback(config, context, guard)
        ids = [e["evidence_id"] for e in context["evidence"][:1]]
        def part(text):
            return {"text": text, "evidence_ids": ids}
        return Narration.model_validate_json(__import__("json").dumps({
            "cover": part("가상 시험: 입장 시 이동을 관찰했습니다."),
            "comments": [part("영역 대응은 미정입니다. 촬영된 입장 행동만 참고하며 평소 관계를 단정할 수 없습니다.") for _ in range(4)],
            "cross": part("유형 분류는 보류합니다. 촬영 조건과 일상 상황이 다를 수 있습니다."),
            "tips": [part("편안한 환경에서 짧게 활동하고 반응을 기록해 보세요.")]})), {"model": "synthetic-test-only", "totalTokenCount": 10}
