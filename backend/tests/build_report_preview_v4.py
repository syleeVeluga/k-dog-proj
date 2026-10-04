"""Write reproducible, wholly synthetic standalone HTML for browser/print QA."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from app.domain.report_profile_v4 import ReportProfileV4
from app.domain.report_render_v4 import ReportHeaderV4, SceneImageV4
from app.report_profile_v4 import build
from app.report_render_v4 import comparison_rows, presentation, render_html, survey_rows
from tests.report_fixture_v4 import fixture


def write_previews(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    header = ReportHeaderV4(dog_name="합성 반려견", guardian_name="합성 보호자", participant_id="S1-PRINT",
        event_name="합성 브라우저 인쇄 검증", observed_date="2026-10-04", generated_at="2026-10-04T00:00:00Z")
    answers = {f"s{i:02}": 3 for i in range(1, 29)}
    answers.update(s10=0, s11=0, s12=0, s13=0, s14=0, s26=1, s27=1, s28=1)
    final, pointer, batch = fixture({"개5": -2, "개58": -2, "보23": 2}, survey=answers, scene_codes=("개5", "개58", "보23"))
    filled = build(final, pointer, batch=batch)
    missing_final, missing_pointer, missing_batch = fixture()
    missing = build(missing_final, missing_pointer, batch=missing_batch)
    long_claim = filled.summary[0].model_copy(update={"text": ("긴 한국어 근거 설명을 누락 없이 보존합니다. " * 300) + "마지막검증표식"})
    long_profile = ReportProfileV4.model_validate_json(filled.model_copy(update={"summary": (long_claim,)}).model_dump_json())
    unsafe_name = '<img src="https://invalid.example/x" onerror="window.reportXss=1"><script>window.reportXss=1</script>'
    pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII=")
    images = []
    for scene in filled.scenes:
        evidence = scene.evidence[0]
        images.append(SceneImageV4(scene_id=scene.scene_id, video_id=evidence.video_id, video_sha256=evidence.video_sha256,
            camera_id=evidence.camera_id, source_seconds=evidence.start_seconds, image_sha256=hashlib.sha256(pixel).hexdigest(), mime="image/png", data=pixel))
    variants = {"filled": (filled, header, ()), "missing": (missing, header, ()),
        "long": (long_profile, header.model_copy(update={"dog_name": "아주 긴 합성 이름 " * 8}), ()),
        "escaped": (filled, header.model_copy(update={"dog_name": unsafe_name}), ()),
        "preview": (filled, header.model_copy(update={"preview": True}), ()), "images": (filled, header, tuple(images))}
    for name, (profile, title, photos) in variants.items():
        (output / f"{name}.html").write_bytes(render_html(profile, title, photos))
    expected = {"sections": presentation()["sections"], "scenes": len(filled.scenes), "unsafe_name": unsafe_name,
        "survey": survey_rows(filled), "comparisons": comparison_rows(filled), "long_marker": "마지막검증표식"}
    (output / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    write_previews(parser.parse_args().output.resolve())
