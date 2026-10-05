"""Inspect and decode local media without modifying originals or dropping audio."""

import json
from pathlib import Path
import subprocess


class MediaError(Exception):
    pass


class NoVideoError(MediaError):
    pass


LOCAL_INPUT = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,avi"]
# A packaged release uses only its own FFmpeg, never another one on PATH; development and server installs use PATH.
RUNTIME = Path(__file__).resolve().parents[2] / "runtime"


def tool(name: str) -> str:
    return str(RUNTIME / "ffmpeg/bin" / f"{name}.exe") if RUNTIME.is_dir() else name


def command(arguments: list[str], timeout=900) -> str:
    try:
        result = subprocess.run([tool(arguments[0]), *arguments[1:]], capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise MediaError("개발자 설정 필요: FFmpeg/ffprobe를 설치하세요.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("미디어 검사 제한 시간을 초과했습니다.") from exc
    if result.returncode:
        raise MediaError("영상·오디오를 해석할 수 없습니다. 원본 파일을 확인하세요.")
    return result.stdout.decode("utf-8")


def probe(path: Path) -> dict:
    """Duration, size and audio presence of a local file — what segment checks and clip planning need."""
    metadata = json.loads(command(["ffprobe", "-v", "error", *LOCAL_INPUT, "-show_format", "-show_streams", "-of", "json", str(path)], timeout=60))
    visual = next((stream for stream in metadata.get("streams", []) if stream["codec_type"] == "video"
                   and not stream.get("disposition", {}).get("attached_pic")), None)
    if visual is None:
        raise NoVideoError("실제 관찰창 안에 영상 프레임이 없습니다.")
    try:
        duration = float(metadata["format"].get("duration", visual.get("duration", 0)))
        size = {"width": visual["width"], "height": visual["height"]}
    except (KeyError, StopIteration, ValueError) as exc:
        raise MediaError("영상 메타데이터를 읽을 수 없습니다.") from exc
    if duration <= 0:
        raise MediaError("영상 길이를 읽을 수 없습니다.")
    audio_ranges = []
    for stream in metadata["streams"]:
        if stream["codec_type"] != "audio":
            continue
        try:
            start = float(stream.get("start_time", 0))
            stream_duration = float(stream["duration"])
            end, basis = min(duration, start + stream_duration), "stream_metadata"
        except (KeyError, ValueError):
            start = float(stream.get("start_time", 0)) if stream.get("start_time") not in (None, "N/A") else 0
            end, basis = duration, "container_fallback"
        audio_ranges.append({"start_sec": max(0, start), "end_sec": end, "basis": basis})
    return {"duration_sec": duration, **size,
            "fps": visual.get("avg_frame_rate", visual.get("r_frame_rate")),
            "audio_ranges": audio_ranges,
            "audio_status": "present" if any(s["codec_type"] == "audio" for s in metadata["streams"]) else "absent"}


def cut_clip(source: Path, output: Path, start_sec: float, end_sec: float, fps: float | None, rules: dict) -> None:
    """Cut [start, end) at the requested frame rate, keeping audio; optional downscale or equirectangular re-projection."""
    if end_sec <= start_sec:
        raise MediaError("클립 구간이 비어 있습니다.")
    filters = [f"fps={fps}"] if fps is not None else []  # None preserves source frames and speed.
    crop = rules.get("equirect_crop")
    if crop:
        filters.append(f"v360=e:flat:yaw={crop['yaw']}:pitch={crop['pitch']}:h_fov={crop['h_fov']}:v_fov={crop['v_fov']}:w={crop['width']}:h={crop['height']}")
    if rules.get("scale_height"):
        filters.append(f"scale=-2:{rules['scale_height']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    command(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-n", *LOCAL_INPUT, "-ss", f"{start_sec:.15f}",
             *(["-to", f"{end_sec:.15f}"] if fps is not None else []),
             "-i", str(source), *(["-t", f"{end_sec - start_sec:.15f}"] if fps is None else []),
             "-map", "0:v:0", *(["-map", "0:a?"] if rules.get("keep_audio", True) else ["-an"]),
             *(["-vf", ",".join(filters)] if filters else []), *(["-fps_mode", "passthrough", "-enc_time_base:v", "demux"] if fps is None else []),
             "-c:v", rules.get("video_codec", "libx264"), "-crf", str(rules.get("crf", 20)),
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output)], timeout=1800)
