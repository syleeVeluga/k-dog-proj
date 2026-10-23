"""Read the eight S1 segment boundaries from the recording tool's on-screen caption, with no provider call.

The recording tool burns a two-line caption into every camera: camera name, participant number, wall clock, elapsed
time and "N. 구간이름 (구간 mm:ss)" (or "구간 표시 전" before the first segment). The segment-name field changes only when
the operator advances the segment, so a persistent change in that field is a boundary. This measures those changes
against segments.csv for docs/plans/K-DOG_영상자동구간과자동분석계획_v1.0_20261023.md. Pillow and the cached FFmpeg only.

    # backend/
    uv run --locked python -X utf8 ../scripts/overlay_boundary_spike.py --csv "../docs/plans/확정 영상 및 구분_20261014/segments.csv" \
        --video CAM1 "../docs/plans/확정 영상 및 구분_20261014/5_2_CAM1_복도정면.mkv" --report "D:/tmp/overlay-spike.json"
"""

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
# 1080p caption geometry: the second caption line, and the segment-name field inside it (after "경과 hh:mm:ss |").
BAND = "crop=1200:60:0:70"
FIELD = (285, 0, 475, 60)
GLYPH = 235        # caption glyphs are pure white; the dark box keeps anything behind it well below this
CHANGED = 0.02     # fraction of field pixels that must change
STABLE = 0.01      # later seconds must agree with the new state this closely
FPS = 30


def ffmpeg():
    cached = ROOT / "releases/.cache/ffmpeg-9.0.2-kdog/bin/ffmpeg.exe"
    found = str(cached) if cached.is_file() else shutil.which("ffmpeg")
    if not found:
        raise SystemExit("ffmpeg를 찾을 수 없습니다 (releases/.cache 또는 PATH).")
    return found


def glyphs(path):
    return Image.open(path).crop(FIELD).convert("L").point(lambda value: 255 if value > GLYPH else 0)


def differs(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / 255


def transitions(video, workdir):
    coarse_dir = workdir / "coarse"
    coarse_dir.mkdir()
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vf", f"fps=1,{BAND}", str(coarse_dir / "f%05d.png")], check=True)
    frames = [glyphs(path) for path in sorted(coarse_dir.glob("f*.png"))]   # frame i is t = i seconds
    found = []
    for i in range(1, len(frames) - 3):
        # A boundary persists: the next three seconds all leave the old state and agree with the new one.
        if differs(frames[i], frames[i - 1]) > CHANGED and all(
                differs(frames[i + k], frames[i - 1]) > CHANGED and differs(frames[i + k], frames[i]) < STABLE for k in (1, 2, 3)):
            fine_dir = workdir / f"fine{i}"
            fine_dir.mkdir()
            subprocess.run([ffmpeg(), "-v", "error", "-y", "-ss", str(i - 1), "-t", "1.2", "-i", str(video), "-vf", BAND,
                            str(fine_dir / "g%03d.png")], check=True)
            fine = sorted(fine_dir.glob("g*.png"))
            base = glyphs(fine[0])
            offset = next((k for k, path in enumerate(fine) if differs(glyphs(path), base) > CHANGED), None)
            found.append(round(i - 1 + offset / FPS, 3) if offset is not None else float(i))
    return found


def truth(path, camera):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("종류") == "구간"]
    return {int(row["구간번호"]): (row["구간이름"], float(row[f"{camera}_영상초"])) for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--video", nargs=2, action="append", metavar=("CAMERA", "PATH"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {"csv": str(args.csv), "videos": []}
    with tempfile.TemporaryDirectory(prefix="kdog-overlay-spike-") as temporary:
        for index, (camera, raw) in enumerate(args.video):
            workdir = Path(temporary) / str(index)
            workdir.mkdir()
            expected = truth(args.csv, camera)
            found = transitions(Path(raw), workdir)
            # The first change is the caption appearing ("구간 표시 전"); the eight segment boundaries follow.
            boundaries = found[1:] if found and found[0] < 3 else found
            rows = []
            for number in range(1, 9):
                name, csv_sec = expected[number]
                overlay = boundaries[number - 1] if number - 1 < len(boundaries) else None
                rows.append({"number": number, "name": name, "csv_sec": csv_sec, "overlay_sec": overlay,
                             "lag_sec": round(overlay - csv_sec, 3) if overlay is not None else None})
            lags = [row["lag_sec"] for row in rows if row["lag_sec"] is not None]
            mean = round(sum(lags) / len(lags), 3) if lags else None
            summary = {"transitions": len(found), "boundaries": len(boundaries), "lag_mean_sec": mean,
                       "lag_min_sec": min(lags) if lags else None, "lag_max_sec": max(lags) if lags else None,
                       "max_abs_error_after_lag_sec": round(max(abs(lag - mean) for lag in lags), 3) if lags else None}
            print(f"{camera}: {json.dumps(summary, ensure_ascii=False)}", flush=True)
            report["videos"].append({"camera": camera, "video": Path(raw).name, "summary": summary, "segments": rows, "all_transitions": found})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"보고서: {args.report}")


if __name__ == "__main__":
    main()
