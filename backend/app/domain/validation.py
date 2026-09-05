"""Context validation must follow structural model validation at each boundary."""

from typing import Literal

from .contracts import (
    BehaviorCatalog, BranchEvaluation, Evidence, ItemScore, ReportResult,
    RunInput, require_unique,
)


def validate_evidence(run: RunInput, evidence: tuple[Evidence, ...]) -> None:
    """Validate fresh observations; cross-run reuse requires a future manifest adapter."""
    require_unique(tuple(item.evidence_id for item in evidence), "evidence_id")
    videos = {video.video_id: video for video in run.videos}
    for item in evidence:
        if (item.run_id, item.case_id, item.session_id) != (run.run_id, run.case_id, run.session_id):
            raise ValueError("evidence belongs to a different run/case/session")
        video = videos.get(item.video_id)
        if video is None or video.camera_id != item.camera_id:
            raise ValueError("unknown video or mismatched camera")
        if item.source_end_sec > video.duration_sec:
            raise ValueError("evidence exceeds original video duration")
        if item.modality in ("audio", "audio_video") and video.audio_status != "present":
            raise ValueError("audio evidence requires usable audio")


def resolve_branch_scores(
    run: RunInput,
    branch: BranchEvaluation,
    catalog: BehaviorCatalog,
    evidence: tuple[Evidence, ...],
    *,
    mode: Literal["production", "test"] = "production",
) -> tuple[ItemScore, ...]:
    """Look up source scores only; aggregate/scoring-rule execution belongs to M3."""
    if mode not in ("production", "test"):
        raise ValueError("unknown execution mode")
    if catalog.provenance != "excel_verified" and mode != "test":
        raise ValueError("test catalog is forbidden in production")
    if run.catalog_version != catalog.version or branch.run_id != run.run_id:
        raise ValueError("run/catalog version mismatch")
    validate_evidence(run, evidence)
    allowed_evidence = {item.evidence_id: item for item in evidence}
    catalog_items = {item.item_id: item for item in catalog.items}
    scores = []
    for item in branch.items:
        for evidence_id in item.evidence_ids:
            linked = allowed_evidence.get(evidence_id)
            if linked is None or item.item_id not in linked.candidate_item_ids:
                raise ValueError("unknown or unrelated evidence reference")
        option = None
        if item.status == "scored":
            option = next((
                candidate for candidate in catalog_items[item.item_id].options
                if candidate.option_id == item.selected_option_id
            ), None)
            if option is None:
                raise ValueError("option is not defined for this item")
        scores.append(ItemScore(
            item_id=item.item_id, status=item.status,
            raw_score=option.score if option else None,
            direction=option.direction if option else None, reason=item.reason,
        ))
    return tuple(scores)


def validate_report_evidence(run: RunInput, report: ReportResult, evidence: tuple[Evidence, ...]) -> None:
    validate_evidence(run, evidence)
    if report.run_id != run.run_id or report.report_mapping_version != run.report_mapping_version:
        raise ValueError("report run/mapping version mismatch")
    allowed = {item.evidence_id for item in evidence}
    for part in (report.cover, *report.domains, report.cross_type, *report.tips):
        if not set(part.evidence_ids) <= allowed:
            raise ValueError("report references unknown evidence")
