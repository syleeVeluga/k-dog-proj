"""Context validation against the catalogs; structural model validation comes first at each boundary."""

from typing import Literal

from .catalog import BehaviorCatalog, SurveyCatalog
from .contracts import ScoreSheet, SessionSegments, SurveyAnswers


def validate_score_sheet(
    sheet: ScoreSheet, catalog: BehaviorCatalog, *, mode: Literal["production", "test"] = "production",
) -> None:
    """A sheet holds exactly the rated items, and every scored value is one the item's scale allows."""
    if mode not in ("production", "test"):
        raise ValueError("unknown execution mode")
    if catalog.provenance != "excel_verified" and mode != "test":
        raise ValueError("test catalog is forbidden in production")
    if sheet.catalog_version != catalog.version:
        raise ValueError("sheet/catalog version mismatch")
    rated = {item.item_id: item for item in catalog.rated_items()}
    if {item.item_id for item in sheet.items} != set(rated):
        raise ValueError("sheet must contain exactly the rated items (derived items are computed, not entered)")
    for entry in sheet.items:
        if entry.status != "scored":
            continue
        item = rated[entry.item_id]
        if item.value_type != "count" and entry.score not in item.allowed_scores:
            raise ValueError(f"{entry.item_id}: {entry.score} is not a labelled value of this item")


def validate_segments(segments: SessionSegments, duration_sec: float) -> None:
    if segments.windows[-1].end_sec > duration_sec:
        raise ValueError("segments exceed the recording length")


def validate_survey_answers(answers: SurveyAnswers, catalog: SurveyCatalog) -> None:
    allowed = {item.item_id for item in catalog.items if item.allows_not_applicable}
    if not set(answers.not_applicable) <= allowed:
        raise ValueError("해당 없음 is only offered for items 7 to 9")
