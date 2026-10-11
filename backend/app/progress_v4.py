"""읽기 전용 분석 단계 요약. 목록 화면이 참가자별로 「촬영 확정 → 전처리 → 채점 → 최종 결과 → 리포트」 중 어디까지 왔는지 보이게 한다.

저장 형식은 바꾸지 않고 기존 기록(변경 이력·평가 시트·리포트 실행)에서만 계산한다. 계산 규칙은 이 한 곳에 둔다.
교수/검토자에게는 다른 평가자의 배정·제출 수와 최종 결과 진행을 보이지 않는다(독립 채점 원칙).
"""

from functools import lru_cache
import json
from pathlib import Path
from typing import Literal

from .input_models import Model

Stage = Literal["recording", "preprocess", "scoring", "final", "report", "complete"]
PREPROCESS_ACTIONS = ("preprocess_v4.started", "preprocess_v4.completed", "preprocess_v4.failed", "preprocess_v4.superseded")


class ProgressV4(Model):
    session_id: str                       # 이 요약이 계산된 회차(화면이 다른 회차를 보고 있으면 쓰지 않는다)
    stage: Stage
    recording: bool
    preprocess: Literal["none", "running", "done", "outdated", "failed"]
    scoring: Literal["none", "partial", "done"]
    sheets_total: int | None = None
    sheets_submitted: int | None = None
    my_sheet: Literal["none", "draft", "submitted"] = "none"
    assigned: list[str] = []
    final: bool | None = None
    report: bool | None = None
    videos_total: int = 0
    videos_usable: int = 0


@lru_cache(maxsize=512)
def _read_clips(root: str, ref: str) -> frozenset[str]:
    batch = json.loads((Path(root) / ref).read_bytes())
    return frozenset(clip["video_id"] for clip in batch.get("clips", []) if clip.get("status") in ("complete", "partial"))


def _usable_videos(root: str, ref: str) -> frozenset[str]:
    """전처리 결과에서 실제 클립(완성·일부)이 만들어진 영상. 결과 파일은 바뀌지 않으므로 성공한 읽기만 캐시한다(일시적 읽기 실패는 다음 요청에서 다시 읽는다)."""
    try:
        return _read_clips(root, ref)
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def build(store, db, views, user) -> dict[str, ProgressV4]:
    """views: 현재 선택 회차를 가진 사례 보기 목록. 한 번의 요청에서 필요한 표를 한꺼번에 읽는다."""
    latest: dict[tuple[str, str], tuple[str, dict]] = {}
    completed: dict[tuple[str, str], dict] = {}
    for row in db.execute("SELECT target,action,detail_json FROM changes WHERE action IN (?,?,?,?) ORDER BY rowid", PREPROCESS_ACTIONS):
        detail = json.loads(row["detail_json"])
        latest[(row["target"], detail.get("session_id", ""))] = (row["action"], detail)
        if row["action"] == "preprocess_v4.completed":
            completed[(row["target"], detail.get("session_id", ""))] = detail
    finals = {(row["target"], json.loads(row["detail_json"]).get("session_id", ""))
              for row in db.execute("SELECT target,detail_json FROM changes WHERE action='final.s1.publish'")}
    reports = {(row["case_id"], row["session_id"]) for row in db.execute(
        "SELECT case_id,session_id FROM runs WHERE kind='report_v4' AND status='succeeded' AND result_ref IS NOT NULL")}
    sheets: dict[tuple[str, str], list] = {}
    from .domain.sheets_v4 import AI_ACCOUNT  # input_models_v4가 이 모듈을 가져오므로 늦게 불러온다
    # 공개 뒤에는 시트의 목적이 independent → review로 바뀌므로 둘 다 평가자 시트다. AI 서비스 계정 시트는 사람 평가자가 아니다.
    for row in db.execute("SELECT case_id,session_id,assigned_username,state FROM score_sheets WHERE active=1 AND purpose IN ('independent','review') AND assigned_username<>?", (AI_ACCOUNT,)):
        sheets.setdefault((row["case_id"], row["session_id"]), []).append(row)
    result = {}
    for view in views:
        session_id = view.manifest.selected_session_id
        key = (view.case_id, session_id)
        session = next(item for item in view.manifest.sessions if item.session_id == session_id)
        recording = bool(session.recording_s1 and session.recording_s1.confirmed)
        action, detail = latest.get(key, ("", {}))
        preprocess = ("done" if detail.get("input_revision") == view.input_revision else "outdated") if action == "preprocess_v4.completed" \
            else "running" if action == "preprocess_v4.started" else "failed" if action in ("preprocess_v4.failed", "preprocess_v4.superseded") else "none"
        videos = [video for video in session.videos if video.media_status != "storage_only"]
        # 다시 실행 중이거나 실패했어도 마지막으로 완성된 결과의 영상은 읽을 수 있다.
        last = completed.get(key)
        usable = _usable_videos(str(store.root), last["ref"]) if last else frozenset()
        rows = sheets.get(key, [])
        mine = next((row for row in rows if row["assigned_username"] == user.username), None)
        my_sheet = "none" if mine is None else "submitted" if mine["state"] == "submitted" else "draft"
        submitted = sum(row["state"] == "submitted" for row in rows)
        scoring = "none" if not rows else "done" if submitted == len(rows) else "partial"
        final = key in finals
        report = key in reports
        steps = [("recording", recording), ("preprocess", preprocess in ("done", "outdated")), ("scoring", scoring == "done"),
                 ("final", final), ("report", report)]
        stage = next((name for name, done in steps if not done), "complete")
        result[view.case_id] = ProgressV4(
            session_id=session_id, stage=stage, recording=recording, preprocess=preprocess, scoring=scoring,
            sheets_total=len(rows), sheets_submitted=submitted,
            my_sheet=my_sheet, assigned=sorted({row["assigned_username"] for row in rows}),
            final=final, report=report,
            videos_total=len(videos), videos_usable=sum(video.video_id in usable for video in videos))
    return result
