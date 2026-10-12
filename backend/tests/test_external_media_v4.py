"""Prepared MP4 provenance, time boundaries and immutable execution acceptance."""
import shutil
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import uploads, preprocess_v4 as preprocess, preprocess_executions_v4 as queries
from app.api import create_app
from app.domain.media_v4 import ExternalProcessingEditV4, ExternalProcessingV4, UploadCreateV4
from app.domain.preprocess_v4 import FileV4
from app.recording_v4 import validate_recording_timeline_v4
from app.scoring_ai_v4 import clips_for
from app.maintenance import backup, clean, references, restore
from app.storage import Store, encode
from tests import test_preprocess_v4 as helpers, test_uploads_api_v4 as api_helpers
from tests.support import AppCase


class ExternalMediaApiV4Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root)
        self.store = self.app.state.store
        self.client = self.client_for("operator")
    receive = api_helpers.UploadApiV4Tests.receive
    link = api_helpers.UploadApiV4Tests.link

    def test_single_file_shared_registration_patch_restart_and_immutable_ledger(self):
        item = self.make_case()
        data = b"synthetic external MP4 bytes"
        receipt = self.receive("external", data, source_kind="external_360_mp4", external_processing={})
        self.assertFalse(receipt["analysis_ready"])
        self.assertEqual(receipt["external_processing"]["timeline"], "unknown")
        self.assertEqual(self.link(receipt, item).status_code, 422)
        self.assertEqual(self.link(receipt, item, "EXT360").status_code, 200)
        item = self.get_case(item)
        video = item["manifest"]["sessions"][0]["videos"][0]
        self.assertEqual((video["camera_id"], video["source_original_number"], video["parents"]), ("EXT360", None, []))
        with self.store.connect() as db:
            before = dict(db.execute("SELECT * FROM upload_receipts").fetchone())
            old = dict(self.store.case(db, item["case_id"]))
        old_bytes = self.store.path(old["manifest_ref"]).read_bytes()
        url = f"/api/cases/{item['case_id']}/videos/{video['video_id']}/external-processing"
        edit = {"session_id": item["selected_session_id"], "expected_revision": item["input_revision"],
                "external_processing": {"projection": "flat", "timeline": "preserved", "note": "ref storage_ref clips/no-file"}}
        for role in ("reviewer", "admin", "developer"):
            client = self.client_for(role)
            edit["expected_revision"] = self.get_case(item)["input_revision"]
            edit["external_processing"]["tool_name"] = role
            response = client.patch(url, json=edit)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.patch(url, json=edit).status_code, 409)
        self.assertEqual(self.store.path(old["manifest_ref"]).read_bytes(), old_bytes)
        with self.store.connect() as db:
            self.assertEqual(before, dict(db.execute("SELECT * FROM upload_receipts").fetchone()))
            references(self.store, db)
        reopened = Store(self.root)
        self.assertEqual(uploads.download_path(reopened, receipt["upload_id"], "operator").read_bytes(), data)
        # Original receipt retries still use the original declaration.
        response = self.client.post("/api/uploads", json={"request_id": receipt["request_id"], "filename": receipt["filename"],
            "expected_size": len(data), "source_kind": "external_360_mp4", "external_processing": {}})
        self.assertEqual(response.status_code, 201, response.text)
        changed = self.receive("changed", data, source_kind="external_360_mp4", external_processing={})
        self.assertEqual(self.link(changed, self.get_case(item), "EXT360").status_code, 409)

    def test_invalid_contracts_and_legacy_canonical_request(self):
        legacy = {"schema_version": "4.0", "request_id": "legacy", "filename": "one.mp4", "expected_size": 1, "expected_sha256": None,
                  "case_id": None, "session_id": None, "source_kind": "original", "parents": [], "conversion": None}
        self.assertEqual(encode(UploadCreateV4(**legacy).model_dump(mode="json")), encode(legacy))
        base = dict(request_id="external", filename="one.mp4", expected_size=1,
                    source_kind="external_360_mp4", external_processing={})
        for change in ({"filename": "one.insv"}, {"external_processing": None},
                       {"source_kind": "original"}, {"conversion": {"tool": "x", "tool_version": "1", "settings": {}}},
                       {"parents": [{"upload_id": "fake", "sha256": "0" * 64}]},
                       {"external_processing": {"projection": "invented"}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                UploadCreateV4(**(base | change))

    def test_preserved_external_registration_keeps_file_and_original_retry_after_correction(self):
        item = self.upload(self.make_case(), b"preserved synthetic external").json()
        video = item["manifest"]["sessions"][0]["videos"][0]
        url = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}/videos/{video['video_id']}/registration"
        request = {"request_id": "preserved-external", "expected_revision": item["input_revision"], "camera_id": "EXT360",
            "source_kind": "external_360_mp4", "external_processing": {}}
        response = self.client.put(url, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        current = updated["manifest"]["sessions"][0]["videos"][0]
        self.assertEqual((current["video_id"], current["storage_ref"], current["sha256"]),
                         (video["video_id"], video["storage_ref"], video["sha256"]))
        edit_url = f"/api/cases/{item['case_id']}/videos/{video['video_id']}/external-processing"
        response = self.client.patch(edit_url, json={"session_id": item["selected_session_id"],
            "expected_revision": updated["input_revision"], "external_processing": {"projection": "flat", "timeline": "preserved"}})
        self.assertEqual(response.status_code, 200, response.text)
        # A repeated original registration does not overwrite effective metadata.
        self.assertEqual(self.client.put(url, json=request).status_code, 200)
        self.assertEqual(self.get_case(item)["manifest"]["sessions"][0]["videos"][0]["external_processing"]["projection"], "flat")

    def test_patch_rejects_tampered_ledger_and_hashing_races(self):
        item = self.make_case()
        receipt = self.receive("tamper", b"synthetic", source_kind="external_360_mp4", external_processing={})
        self.assertEqual(self.link(receipt, item, "EXT360").status_code, 200)
        item = self.get_case(item)
        video_id = item["manifest"]["sessions"][0]["videos"][0]["video_id"]
        url = f"/api/cases/{item['case_id']}/videos/{video_id}/external-processing"
        edit = {"session_id": item["selected_session_id"], "expected_revision": item["input_revision"],
                "external_processing": {"projection": "flat", "timeline": "preserved"}}
        with self.store.connect() as db:
            original = dict(db.execute("SELECT * FROM upload_receipts").fetchone())
        mutations = [{"request_hash": "0" * 64}, {"link_json": encode(json.loads(original["link_json"]) | {"camera_id": "CAM1"})}]
        changed = encode(json.loads(original["request_json"]) | {"source_kind": "original", "external_processing": None})
        mutations.append({"request_json": changed, "request_hash": hashlib.sha256(changed.encode()).hexdigest()})
        for extra in ({"expected_sha256": "0" * 64}, {"case_id": "other", "session_id": "other"}, {"request_id": "changed"}):
            changed = encode(json.loads(original["request_json"]) | extra)
            mutations.append({"request_json": changed, "request_hash": hashlib.sha256(changed.encode()).hexdigest()})
        mutations.append({"link_json": encode(json.loads(original["link_json"]) | {"case_id": "other"})})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE upload_receipts SET request_json=?,request_hash=?,link_json=?",
                        tuple((original | mutation)[key] for key in ("request_json", "request_hash", "link_json")))
                self.assertEqual(self.client.patch(url, json=edit).status_code, 409)
                self.assertEqual(self.get_case(item)["input_revision"], item["input_revision"])
        with self.store.connect(write=True) as db:
            db.execute("UPDATE upload_receipts SET request_json=?,request_hash=?,link_json=?",
                tuple(original[key] for key in ("request_json", "request_hash", "link_json")))
        real = uploads._verify_sources
        def changed_login(*args):
            result = real(*args)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET session_hash='replaced-session' WHERE username='operator'")
            return result
        with patch.object(uploads, "_verify_sources", side_effect=changed_login):
            self.assertEqual(self.client.patch(url, json=edit).status_code, 403)
        with self.store.connect() as db:
            self.assertEqual(self.store.case(db, item["case_id"])["input_revision"], item["input_revision"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Synthetic FFmpeg required")
class ExternalMediaPreprocessV4Tests(unittest.TestCase):
    setUpClass = classmethod(helpers.PreprocessV4Tests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.PreprocessV4Tests.tearDownClass.__func__)
    setUp = helpers.PreprocessV4Tests.setUp
    current = helpers.PreprocessV4Tests.current
    upload = helpers.PreprocessV4Tests.upload
    recording = helpers.PreprocessV4Tests.recording
    run_batch = helpers.PreprocessV4Tests.run_batch

    def edit(self, video, projection, timeline, actor="review"):
        return uploads.update_external_processing(self.store, self.case_id, video.video_id,
            ExternalProcessingEditV4(session_id=self.session_id, expected_revision=self.current()["input_revision"],
                external_processing=ExternalProcessingV4(projection=projection, timeline=timeline)), actor)

    def test_all_nine_combinations_keep_normal_view_and_exclude_unsupported_supplier_clips(self):
        normal = self.upload("two")
        external = self.upload("one", "EXT360", source_kind="external_360_mp4", external_processing={})
        for projection in ("flat", "equirectangular", "unknown"):
            for timeline in ("preserved", "edited", "unknown"):
                with self.subTest(projection=projection, timeline=timeline):
                    self.edit(external, projection, timeline)
                    # Unknown/edited file remains in the draft offset list without a time anchor.
                    self.recording(normal.video_id, ((external.video_id, 0 if timeline == "preserved" else None),))
                    batch = self.run_batch(projection + timeline)
                    window = next(value for value in batch.windows if value.window.window_id == "entry_whole")
                    view = next(value for value in window.views if value.video_id == external.video_id)
                    supported = projection == "flat" and timeline == "preserved"
                    self.assertEqual(view.availability, "available" if supported else "conversion_required")
                    supplier = clips_for(SimpleNamespace(batch=batch), SimpleNamespace(window_ids=("entry_whole",), input_variant="ai"))
                    self.assertTrue(any(clip.video_id == normal.video_id for clip in supplier))
                    self.assertEqual(any(clip.video_id == external.video_id for clip in supplier), supported)
                    self.assertEqual(batch.status, "complete" if supported else "partial")
                    if not supported:
                        self.assertTrue(any(reason.startswith("external_") for reason in view.reasons))

    def test_time_anchor_projection_independence_drafts_and_reconfirmation(self):
        normal = self.upload("two")
        external = self.upload("one", "EXT360", source_kind="external_360_mp4", external_processing={})
        for timeline in ("edited", "unknown", "preserved"):
            self.edit(external, "equirectangular", timeline)
            for anchor in ("reference", "event", "offset", "coverage"):
                events = [{"event_id": "e", "kind": "occlusion", "video_id": external.video_id,
                           "seconds": 1, "end_seconds": 2, "note": "synthetic"}] if anchor == "event" else []
                coverage = [{"evidence_id": "coverage", "window_id": "entry_whole", "video_id": external.video_id, "modality": "visual",
                    "start_seconds": 1, "end_seconds": 2, "observed_seconds": 1, "coverage": "whole", "note": "synthetic"}] if anchor == "coverage" else []
                self.recording(external.video_id if anchor == "reference" else normal.video_id,
                    ((external.video_id, 0 if anchor == "offset" else None),) if anchor != "reference" else (), events=events, coverage=coverage)
                with self.store.connect() as db:
                    session = self.store.manifest(self.store.case(db, self.case_id)).sessions[0]
                if timeline == "preserved":
                    validate_recording_timeline_v4(session, session.recording_s1)
                else:
                    with self.assertRaises(HTTPException):
                        validate_recording_timeline_v4(session, session.recording_s1)
                    session.recording_s1 = session.recording_s1.model_copy(update={"confirmed": False})
                    validate_recording_timeline_v4(session, session.recording_s1)

    def test_metadata_revision_keeps_historical_execution_and_guard_rejects_inflight_publish(self):
        external = self.upload("one", "EXT360", source_kind="external_360_mp4",
            external_processing={"projection": "flat", "timeline": "preserved"})
        self.recording(external.video_id)
        batch = self.run_batch()
        pointer = FileV4(ref=f"{preprocess.status(self.store, self.case_id, self.session_id, 'op').result_pointer.ref}",
                         hash=preprocess.status(self.store, self.case_id, self.session_id, 'op').result_pointer.hash)
        self.edit(external, "unknown", "preserved")
        detail = queries.execution(self.store, self.case_id, self.session_id, batch.batch_id, "dev")
        self.assertTrue(detail.outdated)
        self.assertEqual(detail.result, batch)
        with self.assertRaises(HTTPException):
            preprocess.verified_batch(self.store, self.case_id, self.session_id, pointer, "review")
        self.assertEqual(preprocess.verified_batch(self.store, self.case_id, self.session_id, pointer, "review",
            expected_input=batch.input, expected_revision=batch.input_revision), batch)
        self.edit(external, "flat", "preserved")
        real = preprocess._ai_clip
        def interrupted(*args):
            real(*args)
            self.edit(external, "flat", "edited")
        with patch.object(preprocess, "_ai_clip", side_effect=interrupted), self.assertRaises(HTTPException):
            self.run_batch("inflight")
        items = queries.executions(self.store, "op").items
        self.assertEqual(items[0].status, "failed")
        self.assertIsNone(items[0].result_pointer)
        self.assertEqual(items[1].result_pointer, pointer)
        with self.store.connect() as db:
            session = self.store.manifest(self.store.case(db, self.case_id)).sessions[0]
            self.assertFalse(session.recording_s1.confirmed)
            self.assertTrue(session.recording_review_required)

    def test_snapshot_restore_notes_and_fail_before_clean_deletes(self):
        external = self.upload("one", "EXT360", source_kind="external_360_mp4",
            external_processing={"note": "storage_ref clips/not-a-file", "tool_name": "ref"})
        self.edit(external, "flat", "preserved")
        self.recording(external.video_id)
        self.run_batch()
        with self.store.connect() as db:
            refs = references(self.store, db)
        destination = self.store.root.parent / "snapshot"
        backup(self.store, destination, "op")
        restored_path = self.store.root.parent / "restored"
        restore(self.store, destination, restored_path)
        restored = Store(restored_path)
        with restored.connect() as db:
            self.assertEqual(references(restored, db), refs)
        orphan = self.store.path("clips/orphan")
        orphan.write_bytes(b"orphan")
        source = uploads.download_path(self.store, external.upload_id, "op")
        source.unlink()
        with self.assertRaises((HTTPException, OSError)):
            clean(self.store)
        self.assertTrue(orphan.exists())
