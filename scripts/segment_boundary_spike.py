"""Measure how well Gemini finds the eight S1 segment boundaries in a full session video.

Development-only spike for docs/plans/K-DOG_영상자동구간과자동분석계획_v1.0_20261023.md. It uploads each whole
video once, asks for the eight segment start times, and compares them with the recording tool's segments.csv
(the CAMk_영상초 column of the matching camera). Real provider calls cost money; nothing is written to the app DB.

    # backend/, same Windows user that registered the Gemini key
    uv run --locked python -X utf8 ../scripts/segment_boundary_spike.py --csv "../docs/plans/확정 영상 및 구분_20261014/segments.csv" \
        --video CAM1 "D:/sample/6_CAM1_복도-정면.mkv" --video CAM2 "D:/sample/6_CAM2_테스트룸-입구.mkv" --report "D:/tmp/segment-spike.json"
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.gemini import BASE, INTERACTION_TIMEOUT, ProviderError, interaction_request, interaction_text, request  # noqa: E402
from app.secrets import credential  # noqa: E402
from app.storage import Store  # noqa: E402

SEGMENTS = ["입장", "기준", "혼자", "재회", "무시", "걷기", "낯선 사람", "퇴장"]
PROMPT = """너는 반려견 애착 행동 평가 영상에서 절차 구간의 경계 시각을 찾는 보조자다.
영상은 고정 카메라 한 대로 촬영한 한 회차 전체이며 오디오가 없을 수 있다. 절차는 아래 8구간이 이 순서로 진행된다.
1 입장: 보호자와 개가 방에 들어온다. 2 기준: 보호자와 개가 함께 방에 있다. 3 혼자: 보호자가 방을 나가고 개만 남는다.
4 재회: 보호자가 돌아온다. 5 무시: 보호자가 개를 무시한다. 6 걷기: 보호자가 개와 함께 이동·정지를 반복한다.
7 낯선 사람: 낯선 사람이 들어온다. 8 퇴장: 보호자와 개가 나간다.
각 구간의 실제 시작 시각(초, 영상 시작 기준, 소수 첫째 자리)을 영상에서 직접 본 시각 단서와 함께 보고한다.
보이지 않거나 확신할 수 없는 구간은 start_sec를 null로 두고 reason에 이유를 적는다. 예정 길이나 순서로 시각을 추정하지 않는다.
구간이 이 카메라 시야 밖에서 시작하면 그 사실을 reason에 적는다. 모든 시각은 0 이상 duration_sec 이하다."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["segments"], "properties": {"segments": {
    "type": "array", "minItems": 8, "maxItems": 8, "items": {"type": "object", "additionalProperties": False,
    "required": ["number", "name", "start_sec", "cue", "confidence", "reason"], "properties": {
        "number": {"type": "integer", "minimum": 1, "maximum": 8}, "name": {"type": "string"},
        "start_sec": {"type": ["number", "null"]}, "cue": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]}, "reason": {"type": "string"}}}}}}


def ffmpeg(name):
    cached = ROOT / f"releases/.cache/ffmpeg-9.0.2-kdog/bin/{name}.exe"
    found = str(cached) if cached.is_file() else shutil.which(name)
    if not found:
        raise SystemExit(f"{name}를 찾을 수 없습니다 (releases/.cache 또는 PATH).")
    return found


def truth(path, camera):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("종류") == "구간"]
    column = f"{camera}_영상초"
    if rows and column not in rows[0]:
        raise SystemExit(f"CSV에 {column} 열이 없습니다.")
    return {int(row["구간번호"]): float(row[column]) for row in rows}


def duration(path):
    out = subprocess.run([ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def as_mp4(path, workdir):
    # Gemini accepts MP4, not Matroska; H.264 in MKV remuxes without re-encoding.
    if path.suffix.lower() == ".mp4":
        return path
    target = workdir / (path.stem + ".mp4")
    subprocess.run([ffmpeg("ffmpeg"), "-v", "error", "-y", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(target)], check=True)
    return target


def ask(key, mp4, seconds, model, fps, resolution):
    size = mp4.stat().st_size
    if size > 2_000_000_000:
        raise SystemExit(f"{mp4.name}: 2GB를 넘는 파일은 보내지 않습니다.")
    timing, started = {}, time.monotonic()
    _, headers = request("POST", BASE + "/upload/v1beta/files", key, data={"file": {"display_name": "kdog-segment-spike"}},
                         headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                                  "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": "video/mp4"})
    with mp4.open("rb") as handle:
        uploaded, _ = request("POST", headers["X-Goog-Upload-URL"], key, data=handle, timeout=INTERACTION_TIMEOUT,
                              headers={"Content-Length": str(size), "Content-Type": "video/mp4",
                                       "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"})
    remote = uploaded["file"]
    name = remote["name"]
    if not re.fullmatch(r"files/[A-Za-z0-9_-]+", name):
        raise SystemExit("원격 파일 이름이 올바르지 않습니다.")
    timing["upload_seconds"] = time.monotonic() - started
    try:
        started = time.monotonic()
        while remote.get("state") == "PROCESSING":
            if time.monotonic() - started > 600:
                raise SystemExit("원격 처리 시간 초과")
            time.sleep(3)
            remote, _ = request("GET", BASE + "/v1beta/" + name, key)
        timing["processing_seconds"] = time.monotonic() - started
        if remote.get("state") != "ACTIVE":
            raise SystemExit("원격 파일 처리 실패")
        video = {"type": "video", "uri": remote["uri"], "mime_type": "video/mp4", "processing": {"type": "static", "fps": fps}}
        if resolution:
            video["resolution"] = resolution
        inputs = [video, {"type": "text", "text": json.dumps({"duration_sec": round(seconds, 1), "sampling_fps": fps}, ensure_ascii=False)}]
        usage = {"model": model}
        started = time.monotonic()
        result, _ = request("POST", BASE + "/v1beta/interactions", key, timeout=INTERACTION_TIMEOUT,
                            data=interaction_request(model, PROMPT, inputs, SCHEMA, 8192))
        timing["inference_seconds"] = time.monotonic() - started
        text = interaction_text(result, "incomplete", usage)
        return json.loads(text)["segments"], usage, timing
    finally:
        try:
            request("DELETE", BASE + "/v1beta/" + name, key)
        except ProviderError as exc:
            print(f"원격 파일 삭제 실패: {name} ({exc.code}). 공급자 콘솔에서 확인하세요.", file=sys.stderr)


def compare(found, expected):
    rows = []
    for number, name in enumerate(SEGMENTS, 1):
        item = next((value for value in found if value.get("number") == number), {})
        start = item.get("start_sec")
        error = None if start is None or number not in expected else round(start - expected[number], 2)
        rows.append({"number": number, "name": name, "expected_sec": expected.get(number), "found_sec": start,
                     "error_sec": error, "confidence": item.get("confidence"), "cue": item.get("cue"), "reason": item.get("reason")})
    errors = [abs(row["error_sec"]) for row in rows if row["error_sec"] is not None]
    summary = {"found": len(errors), "missing": 8 - len(errors),
               "mean_abs_error_sec": round(sum(errors) / len(errors), 2) if errors else None,
               "max_abs_error_sec": round(max(errors), 2) if errors else None,
               "within_2s": sum(error <= 2 for error in errors), "within_5s": sum(error <= 5 for error in errors)}
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True, help="녹화 도구 segments.csv (정답)")
    parser.add_argument("--video", nargs=2, action="append", metavar=("CAMERA", "PATH"), required=True, help="카메라 ID와 전체 회차 영상")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("KDOG_DATA_DIR", Path(os.environ.get("LOCALAPPDATA", "")) / "K-DOG/data")),
                        help="Gemini 주키가 등록된 자료 폴더 (키는 같은 Windows 사용자만 읽을 수 있음)")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--media-resolution", help="생략하면 공급자 기본값")
    parser.add_argument("--repeat", type=int, default=1, help="같은 영상 반복 횟수 (편차 확인)")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="공급자 호출 없이 영상 변환·CSV 대조 경로만 확인")
    args = parser.parse_args()
    key = None if args.dry_run else credential(Store(args.data_dir), "gemini")[0]
    report = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "csv": str(args.csv), "model": args.model,
              "fps": args.fps, "media_resolution": args.media_resolution, "dry_run": args.dry_run, "videos": []}
    with tempfile.TemporaryDirectory(prefix="kdog-segment-spike-") as temporary:
        for camera, raw in args.video:
            path = Path(raw)
            expected = truth(args.csv, camera)
            mp4 = as_mp4(path, Path(temporary))
            seconds = duration(mp4)
            entry = {"camera": camera, "video": path.name, "duration_sec": round(seconds, 1), "size_bytes": mp4.stat().st_size, "runs": []}
            for index in range(args.repeat):
                if args.dry_run:
                    found, usage, timing = [], {}, {}
                else:
                    found, usage, timing = ask(key, mp4, seconds, args.model, args.fps, args.media_resolution)
                rows, summary = compare(found, expected)
                entry["runs"].append({"run": index + 1, "summary": summary, "segments": rows, "usage": usage, "timing": {k: round(v, 1) for k, v in timing.items()}})
                print(f"{camera} #{index + 1}: {json.dumps(summary, ensure_ascii=False)}")
            report["videos"].append(entry)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"보고서: {args.report}")


if __name__ == "__main__":
    main()
