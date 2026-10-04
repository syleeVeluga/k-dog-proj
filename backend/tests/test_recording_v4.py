import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.domain.catalog_v4 import ITEM_CODES
from app.domain.recording_v4 import ActualEventV4, RecordingV4, WindowCoverageV4
from app.recording_v4 import (build_windows_v4, item_capture_gates_v4, safe_base_sequence_v4,
                              validate_recording_media_v4, observation_clear_v4)


def fixture():
    times = {"entry": (0, 30), "baseline": (30, 50), "alone": (52, 112), "reunion": (112, 142),
             "ignore": (142, 162), "walk": (167, 207), "stranger": (215, 245), "exit": (250, 280)}
    phase_times = ((167, 171), (171, 176), (176, 189), (189, 194), (194, 202), (202, 207))
    phases = ("move_1", "stop_1", "move_2", "stop_2", "move_3", "stop_3")
    return {"procedure_edition": "s1_confirmed", "procedure_note": "합성 표준절차 확인", "video_id": "v1", "confirmed": True,
            "segments": [{"segment": key, "video_id": "v1", "start_sec": start, "end_sec": end} for key, (start, end) in times.items()],
            "walk_phases": [{"phase": phase, "video_id": "v1", "start_sec": start, "end_sec": end, "proximity_exception": "none"}
                            for phase, (start, end) in zip(phases, phase_times)]}


def recording(value=None):
    return RecordingV4.model_validate_json(json.dumps(value or fixture(), ensure_ascii=False))


def event(key, kind, segment, seconds=None, end=None, status="observed", video="v1"):
    return {"event_id": key, "kind": kind, "video_id": video, "segment": segment, "status": status,
            "seconds": seconds, "end_seconds": end, "note": "합성 실제 사건"}


def coverage(key, start, end, *, amount=None, state="whole", video="v1", modality="visual", evidence="proof"):
    return {"evidence_id": evidence, "window_id": key, "video_id": video, "start_seconds": start, "end_seconds": end,
            "observed_seconds": end - start if amount is None else amount, "coverage": state, "modality": modality, "note": "합성 관찰 근거"}


def windows(value):
    return {window.window_id: window for window in build_windows_v4(recording(value))}


def gates(value):
    return {gate.code: gate for gate in item_capture_gates_v4(recording(value))}


class RecordingV4Tests(unittest.TestCase):
    def test_explicit_loss_overrides_whole_evidence_for_affected_item_and_can_use_other_camera(self):
        value = fixture()
        value["coverage"] = [coverage("entry_whole", 0, 30)]
        loss = event("hidden", "body_not_visible", "entry", 5, 9)
        loss["affected_codes"] = ["바14"]
        value["events"] = [loss]
        self.assertFalse(windows(value)["entry_whole"].whole_visual_observed)
        self.assertEqual(gates(value)["바14"].status, "unobserved")
        self.assertEqual(gates(value)["바46"].status, "ready")
        value["video_offsets"] = [{"video_id": "v2", "offset_seconds": 2, "confirmed": True, "note": "합성 확인"}]
        value["coverage"].append(coverage("entry_whole", 2, 32, video="v2", evidence="other"))
        self.assertEqual(gates(value)["바14"].status, "ready")
        value["events"].append(event("lost-audio", "audio_loss", "entry", 6, 8))
        self.assertFalse(observation_clear_v4(recording(value), "v1", 0, 30, modality="audio"))
        self.assertTrue(observation_clear_v4(recording(value), "v1", 9, 30, modality="audio"))
        self.assertTrue(observation_clear_v4(recording(value), "v2", 2, 32, modality="visual", code="바14"))

    def test_actual_windows_do_not_equal_split_or_force_five_second_movement(self):
        result = windows(fixture())
        self.assertEqual((result["alone_later"].start_seconds, result["alone_later"].end_seconds), (62, 112))
        self.assertEqual((result["reunion_later"].start_seconds, result["reunion_later"].end_seconds), (127, 142))
        self.assertEqual((result["walk_phase_3"].start_seconds, result["walk_phase_3"].end_seconds), (176, 189))
        self.assertEqual(result["stranger_call"].status, "unobserved")
        self.assertNotIn("floor_shake", result)
        self.assertNotIn("separation_shake", result)
        self.assertEqual(set(gates(fixture())), set(ITEM_CODES))

    def test_stranger_actual_events_override_scheduled_16_second_call(self):
        value = fixture()
        value["events"] = [event("gate", "stranger_gate_wait", "stranger", 215, 226),
                           event("approach", "stranger_approach", "stranger", 228, 234),
                           event("call", "stranger_name", "stranger", 234)]
        result = windows(value)
        self.assertEqual((result["stranger_call"].start_seconds, result["stranger_call"].end_seconds), (234, 238))
        self.assertEqual(result["stranger_approach"].start_seconds, 228)
        self.assertEqual(result["stranger_gate"].end_seconds, 226)

    def test_legacy_stranger_before_reunion_is_preserved_and_not_standard(self):
        value = fixture()
        by_id = {window["segment"]: window for window in value["segments"]}
        by_id["stranger"].update(start_sec=112, end_sec=142)
        by_id["reunion"].update(start_sec=215, end_sec=245)
        with self.assertRaises(ValidationError):
            recording(value)
        value["procedure_edition"] = "legacy"
        value["procedure_note"] = "예비촬영 실제 낯선 사람→재회"
        result = windows(value)
        self.assertEqual(result["reunion_whole"].start_seconds, 215)
        self.assertEqual(result["stranger_whole"].start_seconds, 112)
        self.assertEqual(result["reunion_whole"].status, "compatibility_pending")
        self.assertEqual(recording(value).segments[3].start_sec, 215)

    def test_skipped_and_interrupted_separation_and_short_reunion(self):
        value = fixture()
        value["segments"][2].update(state="not_performed", start_sec=None, end_sec=None, reason="합성 생략")
        with self.assertRaises(ValidationError):
            recording(value)
        value["segments"][3].update(state="not_performed", start_sec=None, end_sec=None, reason="분리 생략")
        self.assertEqual(windows(value)["reunion_contact"].status, "not_performed")
        value = fixture()
        value["segments"][2].update(state="welfare_stopped", end_sec=90, reason="합성 복지 중단")
        value["segments"][3].update(state="shortened", start_sec=90, end_sec=110, reason="실제 20초")
        result = windows(value)
        self.assertEqual(result["alone_later"].status, "partial")
        self.assertEqual(result["reunion_later"].status, "partial")
        self.assertEqual(result["reunion_later"].end_seconds, 110)
        value["segments"][3]["start_sec"] = 91
        with self.assertRaises(ValidationError):
            recording(value)

    def test_no_contact_does_not_erase_later_body_or_avoidance_response(self):
        value = fixture()
        value["events"] = [event("no-contact", "reunion_contact_start", "reunion", status="not_occurred")]
        value["coverage"] = [coverage("reunion_later", 127, 142)]
        result = gates(value)
        self.assertEqual(result["개19"].status, "no_opportunity")
        self.assertEqual(result["개44"].status, "no_opportunity")
        self.assertEqual(result["개18"].status, "ready")
        self.assertEqual(result["보22"].window_ids, ("reunion_later",))
        self.assertEqual(result["보22"].status, "ready")
        value["events"] = [event("contact", "reunion_contact_start", "reunion", 132),
                           event("stop", "staff_stop", "reunion", 134)]
        self.assertEqual(windows(value)["reunion_contact"].status, "partial")
        self.assertEqual(len(recording(value).events), 2)

    def test_event_absence_and_nonobservation_have_null_times(self):
        for status in ("not_occurred", "unobserved"):
            value = event("unknown", "reunion_contact_start", "reunion", status=status)
            self.assertEqual(ActualEventV4.model_validate_json(json.dumps(value)).status, status)
            value["seconds"] = 0
            with self.assertRaises(ValidationError):
                ActualEventV4.model_validate_json(json.dumps(value))

    def test_unconfirmed_offset_preserves_raw_but_never_resolves_event_window(self):
        value = fixture()
        value["events"] = [event("contact", "reunion_contact_start", "reunion", 152, video="v2"),
                           event("end", "reunion_contact_end", "reunion", 155, video="v2")]
        value["video_offsets"] = [{"video_id": "v2", "offset_seconds": 20, "confirmed": False, "note": "합성 수동 확인 전"}]
        result = recording(value)
        self.assertEqual(result.events[0].seconds, 152)
        self.assertIsNone(result.event_times(result.events[0]))
        self.assertEqual(windows(value)["reunion_contact"].status, "unobserved")
        value["video_offsets"][0]["confirmed"] = True
        value["coverage"] = [coverage("reunion_contact", 152, 155, video="v2")]
        result = windows(value)["reunion_contact"]
        self.assertEqual((result.start_seconds, result.end_seconds), (132, 135))
        source = result.source_intervals[-1]
        self.assertEqual(source.start_seconds - source.offset_seconds, result.start_seconds)
        self.assertTrue(result.whole_visual_observed)

    def test_tail_requires_first_turn_full_two_three_seconds_and_same_conditions(self):
        value = fixture()
        value["events"] = [event("turn", "reunion_head_turn", "reunion", 130)]
        value["tail_selections"] = [{"code": "바54", "event_id": "turn", "first_clear_confirmed": True,
                                     "same_posture": True, "same_movement": True, "tail_visible_before": True,
                                     "tail_visible_after": True, "note": "합성 비교 가능"}]
        result = windows(value)["reunion_tail_event"]
        self.assertEqual((result.start_seconds, result.end_seconds), (128, 133))
        self.assertTrue(result.trial_only)
        for field in ("same_posture", "same_movement", "tail_visible_before", "tail_visible_after"):
            changed = copy.deepcopy(value)
            changed["tail_selections"][0][field] = False
            self.assertEqual(windows(changed)["reunion_tail_event"].status, "unobserved")
        value["events"][0]["seconds"] = 113
        self.assertEqual(windows(value)["reunion_tail_event"].status, "unobserved")
        value["events"][0]["seconds"] = 140
        self.assertEqual(windows(value)["reunion_tail_event"].status, "unobserved")

    def test_whole_count_and_exploration_gates_retain_partial_observed_events(self):
        value = fixture()
        value["events"] = [event("scratch", "body_scratch", "reunion", 125, 126)]
        value["coverage"] = [coverage("reunion_whole", 112, 142, amount=15, state="partial")]
        self.assertEqual(gates(value)["바49"].status, "unobserved")
        self.assertEqual(recording(value).events[0].seconds, 125)
        self.assertIn("scratch", windows(value)["reunion_whole"].event_ids)
        self.assertEqual(gates(value)["개8"].status, "unobserved")
        self.assertEqual(gates(value)["개12"].status, "unobserved")
        value["coverage"] = [coverage("reunion_whole", 112, 142)]
        self.assertEqual(gates(value)["바49"].status, "ready")
        bad = coverage("reunion_whole", 112, 142, amount=29)
        with self.assertRaises(ValidationError):
            WindowCoverageV4.model_validate_json(json.dumps(bad))

    def test_unknown_window_and_transition_inside_main_segment_are_rejected(self):
        value = fixture()
        value["coverage"] = [coverage("floor_shake", 0, 5)]
        with self.assertRaises(ValueError):
            windows(value)
        value = fixture()
        value["events"] = [event("prepare", "walk_to_s_start", None, 150)]
        with self.assertRaises(ValidationError):
            recording(value)

    def test_camera_observation_durations_are_not_added_together(self):
        value = fixture()
        value["video_offsets"] = [{"video_id": "v2", "offset_seconds": 20, "confirmed": True, "note": "합성 동기화"}]
        value["coverage"] = [coverage("reunion_whole", 112, 142, modality="audio"),
                             coverage("reunion_whole", 132, 162, modality="audio", video="v2", evidence="second")]
        result = windows(value)["reunion_whole"]
        self.assertTrue(result.whole_audio_observed)
        self.assertFalse(result.whole_visual_observed)
        self.assertEqual([proof.observed_seconds for proof in result.coverage], [30, 30])
        self.assertEqual(result.end_seconds - result.start_seconds, 30)

    def test_policy_pending_is_not_missing_observation_or_extra_invalidity(self):
        value = fixture()
        value["events"] = [event("check", "reunion_check", "reunion", 139),
                           event("deviation", "route_deviation", "walk", 180)]
        result = gates(value)
        self.assertEqual(result["개21"].status, "policy_pending")
        self.assertEqual(result["개21"].window_ids, ("reunion_approach",))
        self.assertEqual(result["개21"].policy_ids, ("D03",))
        self.assertEqual(result["보5"].status, "policy_pending")
        self.assertEqual(result["개38"].status, "ready")
        self.assertEqual(recording(value).events[0].seconds, 139)
        value["walk_phases"][0].update(proximity_exception="recheck", proximity_note="확인 필요")
        self.assertEqual(gates(value)["개38"].status, "unobserved")

    def test_departure_preparation_is_not_the_alone_window_and_memo_is_separate(self):
        value = fixture()
        value["events"] = [event("prepare", "guardian_departure_preparation", None, 50),
                           event("outside", "guardian_fully_outside", None, 52)]
        value["linked_memos"] = [{"memo_id": "memo", "text": "실제 사건 메모", "item_codes": ["개10"], "event_ids": ["outside"]}]
        result = windows(value)["separation_departure"]
        self.assertEqual((result.start_seconds, result.end_seconds), (50, 52))
        self.assertEqual(gates(value)["보10"].window_ids, ("separation_departure",))
        self.assertEqual(recording(value).linked_memos[0].code, "개59")
        self.assertNotIn("개59", gates(value))

    def test_safe_base_requires_actual_order_not_exploration_categories(self):
        value = fixture()
        self.assertEqual(safe_base_sequence_v4(recording(value)).status, "unconfirmed")
        value["events"] = [event("approach", "guardian_approach", "reunion", 116),
                           event("contact", "guardian_contact", "reunion", 130, 131),
                           event("explore", "exploration_resumed", "reunion", 136)]
        value["safe_base_sequence"] = {"approach_event_id": "approach", "contact_event_id": "contact",
                                        "exploration_event_id": "explore", "note": "합성 실제 순서"}
        self.assertEqual(safe_base_sequence_v4(recording(value)).status, "confirmed_sequence")
        value["events"][2]["seconds"] = 129
        result = safe_base_sequence_v4(recording(value))
        self.assertEqual(result.status, "unconfirmed")
        self.assertEqual(result.reference_seconds, (116, 130, 129))

    def test_media_hash_length_cross_camera_and_insv_are_validated_without_real_probe(self):
        with tempfile.TemporaryDirectory(prefix="kdog-recording-test-") as folder:
            root = Path(folder)
            payload = b"synthetic-not-real-media"
            (root / "v1.mp4").write_bytes(payload)
            video = SimpleNamespace(video_id="v1", media_status="pending_probe", storage_ref="v1.mp4",
                                    size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            store, session = SimpleNamespace(path=lambda ref: root / ref), SimpleNamespace(videos=[video])
            with patch("app.recording_v4.probe", return_value={"duration_sec": 300}):
                self.assertEqual(validate_recording_media_v4(store, session, recording()), {"v1": 300})
            with patch("app.recording_v4.probe", return_value={"duration_sec": 270}):
                with self.assertRaises(HTTPException) as caught:
                    validate_recording_media_v4(store, session, recording())
                self.assertEqual(caught.exception.status_code, 422)
            video.media_status = "storage_only"
            with self.assertRaises(HTTPException) as caught:
                validate_recording_media_v4(store, session, recording())
            self.assertEqual(caught.exception.status_code, 422)
            video.media_status = "pending_probe"
            (root / "v1.mp4").write_bytes(b"x" * len(payload))
            with self.assertRaises(HTTPException) as caught:
                validate_recording_media_v4(store, session, recording())
            self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
