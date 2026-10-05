"""Real FFmpeg tests on synthetic media, not camera INSV acceptance."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import convert


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe 필요")
class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="kdog-media-experiment-")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "synthetic space 한글.insv"
        convert.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-f", "lavfi", "-i",
                     "testsrc2=size=320x160:rate=12", "-f", "lavfi", "-i", "sine=frequency=440",
                     "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-f", "mp4", str(cls.source)])
        cls.original_hash = convert.digest(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def experiment(self, mode, *extra, source=None):
        destination = self.root / self.id().split(".")[-1]
        args = convert.parser().parse_args([mode, str(source or self.source), "--output-dir", str(destination), *extra])
        with redirect_stdout(io.StringIO()):
            code = convert.execute(args)
        reports = sorted(destination.glob("*/report.json"), key=lambda path: path.stat().st_mtime_ns)
        return code, json.loads(reports[-1].read_text(encoding="utf-8"))

    def test_sample_decode_does_not_claim_stitching_or_s1_support(self):
        code, report = self.experiment("inspect", "--seconds", "1")
        self.assertEqual(code, 0)
        self.assertEqual(report["direct_decode"], "sample_passed")
        self.assertFalse(report["stitching_performed"])
        self.assertEqual(report["s1_analysis_suitability"], "unverified")
        self.assertIsNone(report["output"])

    def test_full_decode_is_explicit(self):
        code, report = self.experiment("inspect", "--full-decode")
        self.assertEqual(code, 0)
        self.assertEqual(report["direct_decode"], "full_passed")
        self.assertIsNone(report["settings"]["effective_seconds"])

    def test_remux_preserves_encoded_packets_and_original(self):
        code, report = self.experiment("remux")
        self.assertEqual(code, 0)
        target = Path(report["output"]["path"])
        def packets(path):
            return json.loads(convert.run(["ffprobe", "-v", "error", "-show_packets",
                "-show_data_hash", "sha256", "-show_entries", "packet=stream_index,data_hash",
                "-of", "json", str(path)]))["packets"]
        self.assertEqual(packets(self.source), packets(target))
        self.assertEqual(convert.digest(self.source), self.original_hash)
        self.assertEqual(report["output"]["full_decode"], "passed")

    def test_compress_keeps_audio_fps_and_dimensions_when_requested(self):
        code, report = self.experiment("compress", "--max-width", "160", "--layout", "dual_fisheye")
        self.assertEqual(code, 0)
        streams = report["output"]["metadata"]["streams"]
        video = next(row for row in streams if row["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (160, 80))
        self.assertEqual(video["avg_frame_rate"], "12/1")
        self.assertTrue(any(row["codec_type"] == "audio" for row in streams))
        self.assertAlmostEqual(float(report["output"]["metadata"]["format"]["duration"]), 2, delta=0.1)
        self.assertFalse(report["stitching_performed"])

    def test_corrupt_source_records_failure_without_successful_output(self):
        broken = self.root / "broken.insv"
        broken.write_bytes(b"invalid synthetic container")
        code, report = self.experiment("remux", source=broken)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertIsNone(report["output"])

    def test_repeat_execution_preserves_prior_artifacts(self):
        _, first = self.experiment("remux")
        target = Path(first["output"]["path"])
        _, second = self.experiment("remux")
        self.assertNotEqual(first["output"]["path"], second["output"]["path"])
        self.assertEqual(convert.digest(target), first["output"]["sha256"])

    def test_repository_output_and_invalid_options_are_rejected(self):
        cases = [("--output-dir", str(convert.REPO / "runtime")),
                 ("--full-decode", "--seconds", "1"), ("--max-width", "0")]
        for options in cases:
            args = convert.parser().parse_args(["inspect", str(self.source), "--output-dir", str(self.root), *options])
            with self.subTest(options=options), self.assertRaises(ValueError):
                convert.execute(args)

    def test_cli_accepts_paths_with_spaces_and_korean(self):
        destination = self.root / "cli 한글 결과"
        result = subprocess.run([sys.executable, "-X", "utf8", str(Path(convert.__file__)),
                                 "inspect", str(self.source), "--output-dir", str(destination)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        report = json.loads(next(destination.glob("*/report.json")).read_text(encoding="utf-8"))
        self.assertEqual(report["settings"]["effective_seconds"], 10)

    def test_multiple_video_tracks_without_audio_are_retained(self):
        source = self.root / "two-tracks.insv"
        convert.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(self.source),
                     "-map", "0:v", "-map", "0:v", "-c", "copy", "-f", "mp4", str(source)])
        code, report = self.experiment("compress", source=source)
        self.assertEqual(code, 0)
        streams = report["output"]["metadata"]["streams"]
        self.assertEqual([row["codec_type"] for row in streams], ["video", "video"])


if __name__ == "__main__":
    unittest.main()
