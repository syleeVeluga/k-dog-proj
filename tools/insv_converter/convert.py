"""Offline media experiments; decoding success does not establish S1 suitability."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid


REPO = Path(__file__).resolve().parents[2]


def run(arguments):
    result = subprocess.run(arguments, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[-4000:])
    return result.stdout.decode("utf-8", errors="replace")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", str(path)]))


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 유한 값을 입력하세요.")
    return number


def parser():
    command = argparse.ArgumentParser(description="INSV/MP4 오프라인 판독·변환 실험 (스티칭 제외)")
    command.add_argument("mode", choices=("inspect", "remux", "compress"))
    command.add_argument("source", type=Path)
    command.add_argument("--output-dir", type=Path, required=True, help="저장소 밖 결과 폴더")
    command.add_argument("--layout", choices=("unknown", "flat", "equirectangular", "dual_fisheye"),
                         default="unknown", help="운영자가 알고 있는 영상 배치; 자동 추정하지 않음")
    command.add_argument("--seconds", type=positive, help="처음 N초만 검사/변환; 미지정 변환은 전체")
    command.add_argument("--full-decode", action="store_true", help="inspect 전체 판독 (기본 처음 10초)")
    command.add_argument("--crf", type=int, choices=range(0, 52), default=23, metavar="0..51")
    command.add_argument("--max-width", type=int, help="compress 최대 너비; 미지정은 원본 해상도")
    return command


def execute(args):
    source = args.source.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if output_dir.is_relative_to(REPO):
        raise ValueError("영상과 검사 기록은 저장소 밖에 저장하세요.")
    if not source.is_file() or source.suffix.lower() not in (".insv", ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"):
        raise ValueError("지원 영상 파일 경로가 필요합니다.")
    if args.full_decode and (args.mode != "inspect" or args.seconds is not None):
        raise ValueError("--full-decode는 inspect에서 --seconds 없이 사용하세요.")
    if args.max_width is not None and (args.mode != "compress" or args.max_width < 2 or args.max_width % 2):
        raise ValueError("--max-width는 compress에서 2 이상의 짝수로 지정하세요.")
    attempt = output_dir / f"{args.mode}-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True)
    report_path = attempt / "report.json"
    report = {"schema": "k-dog-media-experiment-1", "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "running", "mode": args.mode, "layout": args.layout,
              "stitching_performed": False, "s1_analysis_suitability": "unverified",
              "product_insv_direct_analysis": "unsupported_storage_only",
              "source": {"path": str(source)}, "commands": [], "output": None,
              "settings": {"seconds": args.seconds, "full_decode": args.full_decode,
                           "crf": args.crf if args.mode == "compress" else None,
                           "max_width": args.max_width}}
    try:
        print("원본 해시·스트림 검사 중…", flush=True)
        report["tools"] = {name: run([name, "-version"]).splitlines()[0] for name in ("ffmpeg", "ffprobe")}
        report["source"].update(size_bytes=source.stat().st_size, sha256=digest(source), metadata=probe(source))
        if not any(stream["codec_type"] == "video" for stream in report["source"]["metadata"]["streams"]):
            raise ValueError("영상 스트림이 없습니다.")
        arguments = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-n", "-xerror", "-i", str(source)]
        seconds = args.seconds
        if args.mode == "inspect" and not args.full_decode and seconds is None:
            seconds = 10
        if seconds is not None:
            arguments += ["-t", str(seconds)]
        arguments += ["-map", "0:v", "-map", "0:a?"]
        report["settings"]["effective_seconds"] = seconds
        target = attempt / "output.mp4"
        if args.mode == "inspect":
            arguments += ["-f", "null", "-"]
        elif args.mode == "remux":
            arguments += ["-c", "copy", "-movflags", "+faststart", str(target)]
        else:
            if args.max_width:
                arguments += ["-vf", f"scale=w='min(iw,{args.max_width})':h=-2"]
            arguments += ["-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
                          "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)]
        report["commands"].append(arguments)
        print("판독·변환 실행 중…", flush=True)
        run(arguments)
        if args.mode == "inspect":
            report["direct_decode"] = "full_passed" if args.full_decode else "sample_passed"
        else:
            metadata = probe(target)
            validation = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-xerror", "-i", str(target),
                          "-map", "0:v", "-map", "0:a?", "-f", "null", "-"]
            report["commands"].append(validation)
            print("출력 전체 판독·해시 검사 중…", flush=True)
            run(validation)
            report["output"] = {"path": str(target), "size_bytes": target.stat().st_size,
                                "sha256": digest(target), "metadata": metadata, "full_decode": "passed",
                                "size_ratio": target.stat().st_size / report["source"]["size_bytes"]}
        if digest(source) != report["source"]["sha256"]:
            raise ValueError("실행 중 원본 해시가 변경되었습니다. 결과를 사용하지 마세요.")
        report["status"] = "passed"
    except (OSError, ValueError, KeyError) as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
    except KeyboardInterrupt:
        report["status"] = "failed"
        report["error"] = "사용자가 실행을 중단했습니다."
    finally:
        with report_path.open("x", encoding="utf-8") as destination:
            json.dump(report, destination, ensure_ascii=False, indent=2)
        print(f"{report['status']}: {report_path}", flush=True)
    return 0 if report["status"] == "passed" else 1


def main():
    try:
        return execute(parser().parse_args())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
