"""Explicit disposable browser fixture; real Worker/REST assembly, fake provider only."""

from types import SimpleNamespace
from unittest.mock import patch

from app import attachment_runs_v4, final_results_v4, judgements_v4, report_runs_v4, run_v4, scoring_ai_v4, secrets, settings_v4, sheets_v4
from app.gemini_v4 import GeminiScorerV4
from app.storage import uid
from app.worker import Worker
from tests import test_attachment_ai_v4, test_report_narrative_v4, test_run_v4
from tests.test_gemini_key_fallback import BACKUP, PRIMARY, SyntheticGemini
from tests.test_opinions_v4 import model, save_opinion


def response(context):
    if context.get("task") == "attachment_v4":
        return test_attachment_ai_v4.selected(context)
    if "cards" in context:
        return test_report_narrative_v4.generated(context)
    observations = [{"code": item["code"], "value": None, "status": "unobserved", "reason": "synthetic absent observation"} for item in context["items"]]
    for item in observations:
        if item["code"] == "개18":
            definition = next(value for value in context["items"] if value["code"] == "개18")
            window = next(value["window"] for value in context["windows"] if value["window"]["window_id"] == definition["windows"][0])
            item.update(value=1, status="observed", opportunity="present", validity="valid", evidence=[{
                "clip_id": "c1", "window_id": window["window_id"], "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"],
                "observed_seconds": window["end_seconds"] - window["start_seconds"], "note": "synthetic reunion approach"}])
    return {**context["identity"], "observations": observations}


class BrowserGeminiFixture:
    def __init__(self, store):
        self.helper = test_run_v4.RunV4Tests()
        self.helper.store = store
        self.helper.setUp()
        self.store = store
        self.user = self.helper.user
        self.transport = SyntheticGemini(response)
        self.transport.cleanup_failure = True
        self.worker = Worker(store, observer=GeminiScorerV4(store, self.transport))
        secrets.change(store, "gemini", PRIMARY, "developer")
        secrets.change(store, "gemini", BACKUP, "developer", slot="backup")
        pipeline = settings_v4.defaults(); pipeline.raw_observation_scope_confirmed = True
        with store.connect() as db:
            active = settings_v4.active(db)
        draft = settings_v4.save(store, model(settings_v4.AiDraftV4, expected_active=active, config=pipeline.model_dump(mode="json")), "developer")
        settings_v4.activate(store, draft["version"], settings_v4.AiActivateV4(expected_active=active), "developer")
        self.score = self.helper.enqueue(config=scoring_ai_v4.configuration(draft["version"], pipeline))
        self.attachment = self.report = None
        self.worker.once()

    def advance(self):
        with self.store.connect(write=True) as db:
            ids = [self.score["run_id"]] + [run["run_id"] for run in (self.attachment, self.report) if run]
            for run_id in ids:
                db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=? AND status='retry_wait'", (run_id,))
        for _ in ids:
            self.worker.once()
        if self.report is None:
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM basic_results WHERE case_id=?", (self.helper.case_id,)).fetchone()
            basic = judgements_v4.document_for(self.store, row)
            reference = judgements_v4.reference(row)
            with patch.object(sheets_v4, "validate_recording_media_v4", return_value={"v1": 300.0}):
                viewer = sheets_v4.assign(self.store, self.helper.case_id, self.helper.session_id, model(sheets_v4.SheetAssignmentV4,
                    expected_revision=self.helper.current()["input_revision"], assigned_username="operator", rater_id="synthetic-gemini-viewer",
                    rater_name="합성 독립 검토자", source_sheet_id=basic.input.sheet_id), self.user)
                observations = [{"code": item.code, "value": None, "status": "unobserved", "reason": "synthetic independent missing"} for item in basic.input_document.sheet.observations]
                viewer = sheets_v4.revise(self.store, viewer["sheet_id"], model(sheets_v4.SheetEditV4, expected_revision=viewer["revision"], observations=observations, reason="synthetic independent"), self.user, "save")
                viewer = sheets_v4.revise(self.store, viewer["sheet_id"], model(sheets_v4.SheetReasonV4, expected_revision=viewer["revision"], reason="synthetic submit"), self.user, "submit")
            opinion_context = SimpleNamespace(store=self.store, case_id=self.helper.case_id, session_id=self.helper.session_id, basic_ref=reference, user=self.user)
            opinion = save_opinion(opinion_context, viewer_sheet_id=viewer["sheet_id"], domains=[{"domain": "attachment", "text": "재회 후 다가와 곁에서 몸이 편안해졌습니다."}])
            self.attachment = attachment_runs_v4.enqueue(self.store, self.helper.case_id, self.helper.session_id,
                model(attachment_runs_v4.AttachmentStartV4, request_id=uid(), basic=reference, opinion=opinion["reference"], viewer_sheet_id=viewer["sheet_id"]), self.user)
            final = final_results_v4.assemble(self.store, self.helper.case_id, self.helper.session_id, model(final_results_v4.AssembleFinalV4,
                basic=reference, opinion=opinion["reference"], viewer_sheet_id=viewer["sheet_id"], reason="synthetic Gemini final"), self.user)
            self.report = report_runs_v4.enqueue(self.store, self.helper.case_id, self.helper.session_id, model(report_runs_v4.ReportStartV4,
                expected_revision=self.helper.current()["input_revision"], request_id=uid(), final=final["reference"], viewer_sheet_id=viewer["sheet_id"]), self.user)
            self.worker.once(); self.worker.once()
        return self.state()

    def state(self):
        return {"case_id": self.helper.case_id, "session_id": self.helper.session_id, "participant_id": "S1-RUN",
                "score_run_id": self.score["run_id"], "attachment_run_id": self.attachment["run_id"] if self.attachment else None,
                "report_run_id": self.report["run_id"] if self.report else None}

    def close(self):
        self.helper.doCleanups()
