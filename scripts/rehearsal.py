"""S1 합성 리허설: Forms → 3개 클라이언트 수신 → 촬영 → 전처리 → 독립 미관찰 제출 → PDF.

운영 자료 폴더는 절대 열지 않는다. 자료는 임시 폴더(또는 --data-dir로 지정한 새 빈 폴더)에만 쓰고, 참가자·보호자·반려견
이름은 모두 합성 문자열이며 공급자 키나 AI 호출은 없다. 처리량 보장이 아니라 흐름 검증이다 — 합성 영상은 320×240 45초이므로
현장의 5.7K 원본 시간·용량을 대표하지 않는다.

    # backend/에서 실행 (httpx는 개발 의존성이므로 uv sync --locked가 필요하다)
    uv run --locked python -X utf8 ../scripts/rehearsal.py --pairs 72 --report "D:/tmp/rehearsal.json"
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.auth import create_user  # noqa: E402
from app.domain.catalog_v4 import OPTIONAL_CODES, load_catalog_v4
from app.input_models import UserCreate
from app.maintenance import status  # noqa: E402
from app.worker import Worker

ORDER = ("entry", "baseline", "alone", "reunion", "ignore", "walk", "stranger", "exit")
PASSWORD = "Rehearsal-synthetic-only-42"
HEADERS = {"X-KDOG-Request": "1"}


class RehearsalError(RuntimeError):
    pass


def synthetic_video(path: Path, seconds: float, pattern: str):
    """A small H.264/AAC file from FFmpeg generators; different patterns give different hashes."""
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", f"{pattern}=size=320x240:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=300)


def csv_bytes(columns, rows):
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def timed(stages, name):
    class Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, *exc):
            stages[name] = round(stages.get(name, 0) + time.perf_counter() - self.start, 3)
    return Timer()


def rehearse(data_dir: Path, pairs: int, seconds: float, event: str):
    if data_dir.exists() and any(data_dir.iterdir()):
        raise RehearsalError("새 빈 폴더만 사용할 수 있습니다.")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RehearsalError(f"{tool}이 PATH에 없습니다.")
    started = time.perf_counter()
    app = create_app(data_dir)
    store = app.state.store
    with store.connect(write=True) as db:
        for name in ("main", "cam1", "cam2", "cam3"):
            create_user(db, UserCreate(username=f"rehearsal-{name}", password=PASSWORD, role="operator"))
    clients = [TestClient(app, base_url="http://127.0.0.1:8000", headers=HEADERS) for _ in range(4)]
    stages = {}
    report = {"spec": "20261002", "pairs": pairs, "event_id": event, "reference_seconds": seconds,
              "logical_clients": 3, "physical_pcs_verified": False, "external_ai_calls": 0}
    def call(method, path, *, client=None, binary=False, **kwargs):
        response = getattr(client or clients[0], method)(path, **kwargs)
        if response.status_code >= 400:
            raise RehearsalError(f"{method.upper()} {path} → {response.status_code} {response.text[:300]}")
        return response.content if binary else response.json()
    try:
        for client, name in zip(clients, ("main", "cam1", "cam2", "cam3")):
            call("post", "/api/auth/login", client=client, json={"username": f"rehearsal-{name}", "password": PASSWORD})
        with tempfile.TemporaryDirectory(prefix="kdog-rehearsal-media-") as media:
            files = []
            with timed(stages, "synthetic_media"):
                for index, pattern in enumerate(("testsrc", "testsrc2", "smptebars"), 1):
                    source = Path(media) / f"CAM{index}.mp4"
                    synthetic_video(source, seconds, pattern)
                    files.append(source.read_bytes())
            columns = ["participant_id", "dog_name", "guardian_name", "consent_analysis_feedback"] + [f"s{i:02}" for i in range(1, 26)]
            rows = [[f"{i:04}", f"합성견{i:02}", f"합성보호자{i:02}", "confirmed", *([2] * 25)] for i in range(1, pairs + 1)]
            with timed(stages, "forms_import"):
                preview = call("post", "/api/forms/preview", json={"file_base64": base64.b64encode(csv_bytes(columns, rows)).decode(),
                    "config": {"request_id": "rehearsal-preview", "event_id": event, "filename": "synthetic.csv", "format": "csv",
                        "mapping": {"version": "synthetic-s1", "source_profile": "합성 리허설", "survey_version": "survey-20260929-v3",
                                    "columns": {key: key for key in columns}}}})
                if preview["errors"]:
                    raise RehearsalError("합성 Forms 미리보기에 오류가 있습니다.")
                imported = call("post", "/api/forms/commit", json={"request_id": "rehearsal-commit", "preview_id": preview["preview_id"], "preview_hash": preview["preview_hash"]})
            clips = clip_bytes = issued = 0
            for imported_row in imported["rows"]:
                item = call("get", "/api/cases/" + imported_row["case_id"])
                base = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}"
                def upload(index):
                    key = f"{item['case_id']}-cam{index}"
                    data = files[index - 1]
                    receipt = call("post", "/api/uploads", client=clients[index], json={"request_id": key, "filename": f"CAM{index}.mp4", "expected_size": len(data)})
                    return call("put", f"/api/uploads/{receipt['upload_id']}/content", client=clients[index], params={"request_id": key}, content=data)
                with timed(stages, "concurrent_upload"):
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        receipts = list(pool.map(upload, (1, 2, 3)))
                video_ids = []
                with timed(stages, "video_link"):
                    for index, receipt in enumerate(receipts, 1):
                        linked = call("post", f"/api/uploads/{receipt['upload_id']}/link", json={"case_id": item["case_id"],
                            "session_id": item["selected_session_id"], "expected_revision": item["input_revision"], "camera_id": f"CAM{index}"})
                        video_ids.append(linked["video_id"])
                        item = call("get", "/api/cases/" + item["case_id"])
                with timed(stages, "recording"):
                    record = {"video_id": video_ids[0], "procedure_edition": "s1_confirmed", "procedure_note": "합성 입장 구간만 수행", "confirmed": True,
                        "segments": [{"segment": key, "video_id": video_ids[0], **({"start_sec": 0.0, "end_sec": min(2.0, seconds)} if key == "entry" else {"state": "not_performed", "reason": "합성 리허설에서 수행하지 않음"})} for key in ORDER],
                        "video_offsets": [{"video_id": key, "offset_seconds": 0.0, "confirmed": True, "note": "동일 길이 합성 영상의 시작 시각"} for key in video_ids[1:]]}
                    item = call("put", base + "/recording-s1", json={"expected_revision": item["input_revision"], "recording": record})
                with timed(stages, "preprocess"):
                    batch = call("post", base + "/preprocess-s1", json={"request_id": "rehearsal-batch", "expected_revision": item["input_revision"], "camera_priority": ["CAM1", "CAM2", "CAM3"]})
                    pointer = call("get", base + "/preprocess-s1")["result_pointer"]
                    for clip in batch["clips"]:
                        for kind in ("original", "ai"):
                            file = clip.get(kind)
                            if file:
                                data = store.path(file["ref"]).read_bytes()
                                if hashlib.sha256(data).hexdigest() != file["hash"]:
                                    raise RehearsalError("전처리 클립 해시가 일치하지 않습니다.")
                                clip_bytes += len(data)
                    clips += len(batch["clips"])
                with timed(stages, "independent_sheet_and_calculation"):
                    sheet = call("post", base + "/sheets-s1", json={"expected_revision": item["input_revision"], "assigned_username": "rehearsal-main",
                        "rater_id": "synthetic-human", "rater_name": "합성 미관찰 기록", "preprocess": {**pointer, "batch_id": batch["batch_id"]}})
                    sheet_url = "/api/score-sheets-s1/" + sheet["sheet_id"]
                    observations = [{"code": entry.code, "value": None, "status": "unobserved", "reason": "합성 영상으로 행동을 평가하지 않음"}
                                    for entry in load_catalog_v4().rated_items() if entry.code not in OPTIONAL_CODES]
                    call("put", sheet_url, json={"expected_revision": 1, "observations": observations})
                    submitted = call("post", sheet_url + "/submit", json={"expected_revision": 2, "reason": "합성 미관찰 제출"})
                    basic = call("post", sheet_url + "/basic-results-s1", json={"input": {"sheet_id": sheet["sheet_id"], "revision": submitted["revision"], "ref": submitted["manifest_ref"], "hash": submitted["manifest_hash"]}})["summary"]
                    final = call("post", base + "/final-results-s1", json={"basic": {"result_id": basic["result_id"], "revision": basic["revision"], "ref": basic["manifest_ref"], "hash": basic["manifest_hash"]}, "reason": "합성 명시 최종 선택"})
                with timed(stages, "report_publish"):
                    run = call("post", base + "/report-runs-s1", json={"expected_revision": item["input_revision"], "request_id": "rehearsal-report", "final": final["reference"]})
                    Worker(store).once()
                    run = call("get", "/api/report-runs-s1/" + run["run_id"])
                    if run["status"] != "succeeded":
                        raise RehearsalError(f"합성 보고서 발급 실패: {run['status']}")
                    output = base + "/report-runs-s1/" + run["run_id"] + "/files/"
                    for kind in ("html", "pdf"):
                        data = call("get", output + kind, binary=True)
                        if (kind == "pdf" and not data.startswith(b"%PDF-")) or (kind == "html" and b"data-section" not in data):
                            raise RehearsalError("발급 파일 형식이 다릅니다.")
                    manifest = call("get", output + "manifest")
                    if manifest["profile"]["source"]["final"] != final["reference"]:
                        raise RehearsalError("발급 manifest의 최종 판본이 다릅니다.")
                    issued += 1
            report.update({"clips": clips, "clip_bytes": clip_bytes, "clips_per_pair": clips // pairs,
                           "uploaded_bytes": sum(map(len, files)) * pairs, "published_reports": issued})
    finally:
        for client in clients:
            client.close()
    report["total_sec"] = round(time.perf_counter() - started, 3)
    report["stages_sec"] = stages
    report["data_dir_bytes"] = sum(path.stat().st_size for path in data_dir.rglob("*") if path.is_file())
    report["free_bytes_after"] = status(store)["free_bytes"]
    report["scope"] = "S1 합성 HTTP/실제 FFmpeg/Worker/HTML/PDF 통합. 3개 논리 클라이언트 수신이며 실제 LAN·PC·대용량·AI 채점·정확도 실측은 제외."
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
