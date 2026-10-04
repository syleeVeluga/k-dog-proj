"""Shared FFmpeg probe and clip regression using synthetic media."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.media import MediaError, cut_clip, probe

RULES = {"codec": "libx264", "crf": 23, "preset": "veryfast", "scale_height": 240}

def synthetic_video(path: Path, seconds=45):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=120)


def stream_stats(path: Path):
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], check=True, capture_output=True, timeout=60).stdout
    data = json.loads(raw)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    numerator, denominator = video["avg_frame_rate"].split("/")
    return {"duration": float(data["format"]["duration"]), "fps": round(int(numerator) / int(denominator), 1),
            "audio": any(s["codec_type"] == "audio" for s in data["streams"]), "width": video["width"], "height": video["height"]}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class PreprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory(prefix="kdog-media-")
        self.addCleanup(self.temp_media.cleanup)
        self.source = Path(self.temp_media.name) / "reference.mp4"
        synthetic_video(self.source)

    def test_probe_and_cut_clip_keep_audio_and_apply_frame_rate(self):
        info = probe(self.source)
        self.assertEqual((info["width"], info["height"], info["audio_status"]), (320, 240, "present"))
        self.assertAlmostEqual(info["duration_sec"], 45.0, delta=0.5)
        target = Path(self.temp_media.name) / "clip.mp4"
        cut_clip(self.source, target, 8.0, 13.0, 8, {**RULES, "scale_height": 120})
        stats = stream_stats(target)
        self.assertAlmostEqual(stats["duration"], 5.0, delta=0.3)
        self.assertEqual((stats["fps"], stats["audio"], stats["height"]), (8.0, True, 120))
        with self.assertRaises(MediaError):
            cut_clip(self.source, Path(self.temp_media.name) / "empty.mp4", 5.0, 5.0, 8, RULES)
        with self.assertRaises(MediaError):
            probe(Path(self.temp_media.name) / "missing.mp4")
