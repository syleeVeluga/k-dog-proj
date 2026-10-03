"""S1 receipt→sheet→PDF rehearsal uses synthetic media in a throwaway folder."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load_script():
    spec = importlib.util.spec_from_file_location("rehearsal", ROOT / "scripts/rehearsal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for the rehearsal")
class RehearsalTests(unittest.TestCase):
    def test_two_pairs_end_to_end_in_a_temporary_folder(self):
        rehearsal = load_script()
        with tempfile.TemporaryDirectory(prefix="kdog-rehearsal-test-") as temporary:
            report = rehearsal.rehearse(Path(temporary), pairs=2, seconds=20.0, event="RTEST")
            self.assertEqual((report["pairs"], report["clips"]), (2, 2 * report["clips_per_pair"]))
            self.assertEqual(report["published_reports"], 2)
            self.assertEqual(report["spec"], "20261002")
            self.assertEqual(report["logical_clients"], 3)
            self.assertFalse(report["physical_pcs_verified"])
            self.assertEqual(report["external_ai_calls"], 0)
            self.assertGreater(report["clip_bytes"], 0)
            self.assertEqual(set(report["stages_sec"]), {"synthetic_media", "forms_import", "concurrent_upload", "video_link", "recording", "preprocess", "independent_sheet_and_calculation", "report_publish"})
            self.assertGreaterEqual(report["total_sec"], sum(report["stages_sec"].values()) - 0.02)

    def test_cli_refuses_a_non_empty_data_dir(self):
        with tempfile.TemporaryDirectory(prefix="kdog-rehearsal-cli-") as temporary:
            (Path(temporary) / "kdog.sqlite3").write_bytes(b"not empty")
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/rehearsal.py"), "--pairs", "1", "--data-dir", temporary],
                                    capture_output=True, timeout=120, cwd=ROOT / "backend")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("새 빈 폴더", result.stderr.decode("utf-8", errors="replace"))
