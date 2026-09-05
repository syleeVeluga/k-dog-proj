"""Inspect and decode local media without modifying originals or dropping audio."""

import hashlib
import json
from pathlib import Path
import subprocess

from app.observation_models import MediaInfo


class MediaError(Exception):
    pass


def command(arguments: list[str], timeout=900) -> str:
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise MediaError("개발자 설정 필요: FFmpeg/ffprobe를 설치하세요.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("미디어 검사 제한 시간을 초과했습니다.") from exc
    if result.returncode:
        raise MediaError("영상·오디오를 해석할 수 없습니다. 원본 파일을 확인하세요.")
    return result.stdout.decode("utf-8")


def inspect_media(path: Path, video, prepared_path: Path, prepared_ref: str) -> MediaInfo:
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if path.stat().st_size != video.size_bytes or digest != video.sha256:
            raise MediaError("등록한 영상의 크기 또는 해시가 변경되었습니다.")
        local_input = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,avi"]
        metadata = json.loads(command(["ffprobe", "-v", "error", *local_input, "-show_format", "-show_streams",
                                       "-of", "json", str(path)], timeout=60))
        streams = metadata["streams"]
        visual = next(stream for stream in streams if stream["codec_type"] == "video"
                      and not stream.get("disposition", {}).get("attached_pic"))
        audio = [stream for stream in streams if stream["codec_type"] == "audio"]
        duration = float(metadata["format"].get("duration", visual.get("duration", 0)))
        # Full decode catches damaged packets after a valid container header.
        command(["ffmpeg", "-v", "error", "-xerror", "-nostdin", *local_input, "-i", str(path),
                 "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"])
        compatible = path.suffix.lower() in (".mp4", ".mov", ".m4v") and visual["codec_name"] == "h264"
        compatible = compatible and all(stream["codec_name"] == "aac" for stream in audio)
        ref, size, mime = video.storage_ref, video.size_bytes, "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
        if not compatible:
            prepared_path.parent.mkdir(parents=True, exist_ok=True)
            command(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-n", *local_input, "-i", str(path),
                     "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                     "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:a", "aac", "-movflags", "+faststart",
                     str(prepared_path)])
            ref, size = prepared_ref, prepared_path.stat().st_size
            mime = "video/mp4"
        with (path if compatible else prepared_path).open("rb") as handle:
            prepared_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        return MediaInfo(video_id=video.video_id, storage_ref=ref, sha256=prepared_hash,
                         size_bytes=size, duration_sec=duration, codec=visual["codec_name"],
                         width=visual["width"], height=visual["height"],
                         audio_status="present" if audio else "absent", mime_type=mime,
                         quality_flags=[] if audio else ["audio_absent"])
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise MediaError("영상 메타데이터 또는 관리 파일이 올바르지 않습니다.") from exc
