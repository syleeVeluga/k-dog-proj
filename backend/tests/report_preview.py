"""Render actual M4 exports with disposable synthetic fixtures for visual QA."""

from pathlib import Path
import sys

from app.exports import capture, render
from app.report_models import ExportRequest
from app.storage import encode
from tests.test_reporting import ReportingTests


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = ReportingTests()
    fixture.setUp()
    try:
        fixture.test_original_frame_membership_time_hash_and_snapshot_image()
        snapshot = capture(fixture.store, ExportRequest(format="pdf", case_id=fixture.item["case_id"], run_id=fixture.run_id), "operator")
        for format in ("pdf", "xlsx", "csv"):
            snapshot["format"] = format
            raw, ext = render(snapshot)
            (output / f"m4-synthetic.{ext}").write_bytes(raw)
        (output / "snapshot.json").write_text(encode(snapshot), encoding="utf-8")
        print(output)
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
