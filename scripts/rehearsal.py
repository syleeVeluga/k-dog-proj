"""촬영 당일 리허설: 합성 영상 72쌍을 접수 → 설문 가져오기 → 영상 파일 등록 → 8구간 확정 → 전처리까지 끝까지 돌린다.

운영 자료 폴더는 절대 열지 않는다. 자료는 임시 폴더(또는 --data-dir로 지정한 새 빈 폴더)에만 쓰고, 참가자·보호자·반려견
이름은 모두 합성 문자열이며 공급자 키나 AI 호출은 없다. 처리량 보장이 아니라 흐름 검증이다 — 합성 영상은 320×240 45초이므로
현장의 5.7K 원본 시간·용량을 대표하지 않는다.

    # backend/에서 실행 (httpx는 개발 의존성이므로 uv sync --locked가 필요하다)
    uv run --locked python -X utf8 ../scripts/rehearsal.py --pairs 72 --report "D:/tmp/rehearsal.json"
"""

import argparse
import csv
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import preprocess  # noqa: E402
from app.api import create_app  # noqa: E402
from app.auth import create_user  # noqa: E402
from app.input_models import Manifest, UserCreate  # noqa: E402
from app.intake import headers  # noqa: E402
from app.maintenance import runtime_lock, status  # noqa: E402

ORDER = ("entry", "baseline", "alone", "stranger", "reunion", "ignore", "walk", "exit")
# Segment boundaries as fractions of the reference length, roughly the 01 §3 procedure proportions.
BOUNDARIES = (0.0, 0.07, 0.18, 0.33, 0.49, 0.67, 0.78, 0.93, 1.0)
PASSWORD = "Rehearsal-synthetic-only-42"
HEADERS = {"X-KDOG-Request": "1"}


class RehearsalError(RuntimeError):
    pass


def synthetic_video(path: Path, seconds: float, pattern: str):
    """A small H.264/AAC file from FFmpeg generators; different patterns give different hashes."""
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", f"{pattern}=size=320x240:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=300)


def windows(duration: float):
    # Floor to 0.1 s so the last edge never rounds past the probed length (validate_segments is strict).
    edges = [math.floor(duration * fraction * 10) / 10 for fraction in BOUNDARIES]
    return [{"segment": name, "start_sec": edges[i], "end_sec": edges[i + 1]} for i, name in enumerate(ORDER)]


def csv_bytes(columns, rows):
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def participants_csv(event: str, pairs: int):
    sexes, sizes, routes = ("암", "수", "중성화", "미기재"), ("소형", "중형", "대형"), ("분양", "입양", "기타")
    rows = [[event, f"{i:04}", f"합성견{i:02}", f"2026-10-31T{9 + i // 12:02}:{(i % 12) * 5:02}", i, "예", f"합성보호자{i:02}",
             "합성 견종", sexes[i % 4], 1 + i % 12, sizes[i % 3], f"{1 + i % 8}년", routes[i % 3]] for i in range(1, pairs + 1)]
    return csv_bytes(headers("participants"), rows)


def survey_csv(event: str, pairs: int, version: str):
    rows = []
    for i in range(1, pairs + 1):
        answers = [((i + number) % 5) + 1 for number in range(1, 29)]
        if i % 3 == 0:  # every third guardian marks 7~9 as 「해당 없음」, the only items that allow it
            answers[6:9] = ["해당 없음"] * 3
        rows.append([event, f"{i:04}", version, *answers])
    return csv_bytes(headers("survey"), rows)


def timed(stages, name):
    class Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, *exc):
            stages[name] = round(time.perf_counter() - self.start, 2)
    return Timer()


def rehearse(data_dir: Path, pairs: int, seconds: float, event: str):
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RehearsalError(f"{tool}이 PATH에 없습니다.")
    app = create_app(data_dir)
    store = app.state.store
    with store.connect(write=True) as db:
        for role in ("operator", "admin"):
            create_user(db, UserCreate(username=f"rehearsal-{role}", password=PASSWORD, role=role))
    client = TestClient(app, base_url="http://127.0.0.1:8000", headers=HEADERS)
    stages, report = {}, {"pairs": pairs, "event_id": event, "reference_seconds": seconds}

    def call(method, path, **kwargs):
        response = getattr(client, method)(path, **kwargs)
        if response.status_code >= 400:
            raise RehearsalError(f"{method.upper()} {path} → {response.status_code} {response.text[:300]}")
        return response.json()

    def import_file(kind, data):
        preview = call("post", f"/api/imports/preview?kind={kind}&format=csv", content=data)
        if preview["errors"] or len(preview["rows"]) != pairs:
            raise RehearsalError(f"{kind} 미리보기 오류: {preview['errors'][:5]} ({len(preview['rows'])}행)")
        call("post", "/api/imports/commit", json={"rows": preview["rows"]})

    with client, tempfile.TemporaryDirectory(prefix="kdog-rehearsal-media-") as media:
        call("post", "/api/auth/login", json={"username": "rehearsal-operator", "password": PASSWORD})
        version = call("get", "/api/catalog/survey")["version"]
        reference, secondary = Path(media) / "reference.mp4", Path(media) / "secondary.mp4"
        with timed(stages, "synthetic_media"):
            synthetic_video(reference, seconds, "testsrc")
            synthetic_video(secondary, max(seconds - 5, 5), "smptebars")
        duration = preprocess.probe(reference)["duration_sec"]
        files = {name: path.read_bytes() for name, path in (("reference.mp4", reference), ("secondary.mp4", secondary))}

        def listed():
            return {item["participant_id"]: item for item in call("get", "/api/cases") if item["event_id"] == event}

        with timed(stages, "intake_import"):
            import_file("participants", participants_csv(event, pairs))
        cases = listed()
        if len(cases) != pairs:
            raise RehearsalError(f"접수 {len(cases)}건 ≠ {pairs}쌍")

        with timed(stages, "survey_import"):
            import_file("survey", survey_csv(event, pairs, version))
        separations, statuses = {}, {}
        for item in cases.values():
            result = call("get", f"/api/cases/{item['case_id']}/survey/result")
            # 「해당 없음」 rows are complete answers but leave 7~9 unanswered, so their status is partial by design.
            expected = "partial" if int(item["participant_id"]) % 3 == 0 else "calculated"
            if result["status"] != expected:
                raise RehearsalError(f"{item['participant_id']} 설문 결과 상태 {result['status']} (예상 {expected})")
            statuses[result["status"]] = statuses.get(result["status"], 0) + 1
            label = result["separation"]["label"] or result["separation"]["status"]
            separations[label] = separations.get(label, 0) + 1
        report["survey_status"] = statuses
        report["survey_separation_types"] = separations
        cases = listed()  # the survey import bumped every input_revision

        uploaded = 0
        with timed(stages, "video_register"):
            for item in cases.values():
                for name, data in files.items():
                    item = call("post", f"/api/cases/{item['case_id']}/videos", content=data,
                                params={"session_id": item["selected_session_id"], "filename": name, "expected_revision": item["input_revision"]})
                    uploaded += len(data)
                cases[item["participant_id"]] = item
        report["uploaded_bytes"] = uploaded

        with timed(stages, "segments_confirm"):
            for item in cases.values():
                session = next(s for s in item["manifest"]["sessions"] if s["session_id"] == item["selected_session_id"])
                reference_id = next(v["video_id"] for v in session["videos"] if v["original_name"] == "reference.mp4")
                cases[item["participant_id"]] = call("put", f"/api/cases/{item['case_id']}/sessions/{session['session_id']}/segments", json={
                    "expected_revision": item["input_revision"], "video_id": reference_id, "confirm": True, "windows": windows(duration)})

        clips, clip_bytes = 0, 0
        with timed(stages, "preprocess"), runtime_lock(store, "worker"):
            for item in cases.values():
                result = preprocess.run(store, item["case_id"], item["selected_session_id"], "rehearsal-operator")
                clips += len(result["clips"])
                clip_bytes += sum(clip["size_bytes"] for clip in result["clips"])
                for clip in result["clips"]:
                    with store.path(clip["ref"]).open("rb") as handle:
                        if hashlib.file_digest(handle, "sha256").hexdigest() != clip["hash"]:
                            raise RehearsalError(f"클립 해시 불일치: {clip['ref']}")
        confirmed = Manifest.model_validate(item["manifest"])
        expected = pairs * len(preprocess.plan(next(s for s in confirmed.sessions if s.session_id == item["selected_session_id"])))
        if clips != expected:
            raise RehearsalError(f"클립 {clips}개 ≠ 예상 {expected}개")
        report.update({"clips": clips, "clip_bytes": clip_bytes, "clips_per_pair": clips // pairs})

    report["data_dir_bytes"] = sum(path.stat().st_size for path in data_dir.rglob("*") if path.is_file())
    report["free_bytes_after"] = status(store)["free_bytes"]
    report["stages_sec"] = stages
    report["total_sec"] = round(sum(stages.values()), 2)
    report["scope"] = "합성 320×240 영상으로 접수→설문→파일 등록→구간 확정→전처리 흐름 검증; 현장 원본 용량·시간·AI 채점은 포함하지 않음"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", type=int, default=72)
    parser.add_argument("--seconds", type=float, default=45.0, help="합성 기준 영상 길이(초)")
    parser.add_argument("--event", default="REHEARSAL")
    parser.add_argument("--data-dir", type=Path, help="새 빈 폴더(저장소 밖). 비우면 임시 폴더를 쓰고 끝나면 지운다. 지정한 폴더는 실패해도 지우지 않는다")
    parser.add_argument("--report", type=Path, help="결과 JSON을 저장할 파일")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 10000 or args.seconds < 10:
        parser.error("--pairs는 1~10000, --seconds는 10 이상이어야 합니다.")
    try:
        if args.data_dir:
            if args.data_dir.exists() and any(args.data_dir.iterdir()):
                parser.error("--data-dir는 새 빈 폴더여야 합니다. 운영 자료 폴더를 지정하지 마세요.")
            report = rehearse(args.data_dir, args.pairs, args.seconds, args.event)
        else:
            with tempfile.TemporaryDirectory(prefix="kdog-rehearsal-") as temporary:
                report = rehearse(Path(temporary), args.pairs, args.seconds, args.event)
    except (RehearsalError, subprocess.SubprocessError, OSError, ValueError) as exc:
        parser.exit(1, f"리허설 실패: {exc}\n")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
