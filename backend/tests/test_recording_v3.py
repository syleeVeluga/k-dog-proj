"""Actual procedure contracts; media probes are synthetic except the browser fixture."""

from copy import deepcopy
from unittest.mock import patch

from app.api import create_app
from app.domain.recording_v3 import WALK_PHASES
from tests.support import AppCase


class RecordingV3Tests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root, intake_spec="20260929")
        self.store = self.app.state.store
        self.client = self.client_for("operator")
        self.item = self.upload(self.make_case()).json()
        self.video = self.item["manifest"]["sessions"][0]["videos"][0]
        self.path = f"/api/cases/{self.item['case_id']}/sessions/{self.item['selected_session_id']}/recording"
        self.probe = patch("app.recording_v3.probe", return_value={"duration_sec": 100.0}).start()
        self.addCleanup(patch.stopall)

    def recording(self):
        spans = [("entry", 0, 10), ("baseline", 10, 20), ("alone", 20, 30),
                 ("reunion", 30, 40), ("ignore", 40, 50), ("walk", 52, 64),
                 ("stranger", 70, 80), ("exit", 82, 92)]
        return {"video_id": self.video["video_id"], "segments": [
            {"segment": segment, "video_id": self.video["video_id"], "start_sec": start, "end_sec": end}
            for segment, start, end in spans], "walk_phases": [
                {"phase": phase, "video_id": self.video["video_id"], "start_sec": 52 + i * 2, "end_sec": 54 + i * 2}
                for i, phase in enumerate(WALK_PHASES)]}

    def event(self, kind="stranger_contact_start", seconds=74, **extra):
        return {"event_id": kind, "kind": kind, "video_id": self.video["video_id"],
                "segment": "stranger", "seconds": seconds, "note": "실제 관찰 맥락", **extra}

    def send(self, record, *, confirm=True, revision=None):
        return self.client.put(self.path, json={"expected_revision": revision or self.item["input_revision"],
                                               "recording": record, "confirm": confirm})

    def save(self, record, *, confirm=True):
        response = self.send(record, confirm=confirm)
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        return self.item["manifest"]["sessions"][0]["recording"]

    def test_actual_boundaries_roundtrip_permissions_and_immutable_history(self):
        original = self.video.copy()
        record = self.recording()
        record["events"] = [self.event(), self.event("stranger_contact_end", 75),
                            self.event("welfare_stop", 76, affected_codes=["개53", "보22"]),
                            self.event("welfare_action", 77, note="직원 신호 뒤 즉시 접촉 중단"),
                            self.event("food", 51, segment=None, note="전환 중 먹이 발견", affected_codes=["개37"])]
        saved = self.save(record)
        self.assertTrue(saved["confirmed"])
        self.assertEqual(saved["segments"][2]["end_sec"], 30)
        self.assertEqual([e["seconds"] for e in saved["events"][:3]], [74, 75, 76])
        self.assertEqual(saved["events"][-1]["note"], "전환 중 먹이 발견")
        with self.store.connect() as db:
            previous = self.store.case(db, self.item["case_id"])["manifest_ref"]
        record["segments"][-1]["end_sec"] = 93
        self.save(record, confirm=False)
        prior = self.store.path(previous).read_text(encoding="utf-8")
        self.assertIn('"end_sec":92', prior.replace(" ", ""))
        self.assertEqual(self.item["manifest"]["sessions"][0]["videos"][0], original)
        self.assertEqual(self.get_case(self.item)["manifest"]["sessions"][0]["recording"]["segments"][-1]["end_sec"], 93)
        reviewer = self.client_for("reviewer")
        self.assertEqual(reviewer.put(self.path, json={"expected_revision": self.item["input_revision"], "recording": record}).status_code, 403)
        self.assertEqual(self.client.put(self.path.replace("/recording", "/segments"), json={
            "expected_revision": self.item["input_revision"], "video_id": self.video["video_id"],
            "windows": [{"segment": w["segment"], "start_sec": w["start_sec"], "end_sec": w["end_sec"]} for w in record["segments"]]}).status_code, 409)

    def test_skipped_and_interrupted_separation_do_not_invent_zero_windows(self):
        record = self.recording()
        for window in record["segments"][2:4]:
            window.update(state="not_performed", start_sec=None, end_sec=None, reason="보호자 요청으로 생략")
        saved = self.save(record)
        self.assertIsNone(saved["segments"][2]["start_sec"])
        bad = deepcopy(record)
        bad["segments"][2]["start_sec"] = 0
        self.assertEqual(self.send(bad).status_code, 422)
        bad = deepcopy(record)
        bad["segments"][3].update(state="performed", start_sec=30, end_sec=40)
        self.assertEqual(self.send(bad).status_code, 422)
        for length in (5, 15):
            record = self.recording()
            record["segments"][2].update(state="welfare_stopped", end_sec=20 + length, reason="불안 지속으로 즉시 복귀")
            record["segments"][3].update(start_sec=20 + length, end_sec=38)
            saved = self.save(record)
            self.assertEqual(saved["segments"][2]["end_sec"] - saved["segments"][2]["start_sec"], length)
            bad = deepcopy(record)
            bad["segments"][3]["start_sec"] += 1
            self.assertEqual(self.send(bad).status_code, 422)

    def test_window_phase_event_and_media_bounds_reject_invalid_confirmation(self):
        mutations = [
            lambda r: r["segments"][0].update(start_sec=-1),
            lambda r: r["segments"][-1].update(end_sec=101),
            lambda r: r["segments"][3].update(start_sec=29),
            lambda r: r["segments"].__setitem__(slice(3, 4), [r["segments"][6]]),
            lambda r: r.update(walk_phases=r["walk_phases"][:-1]),
            lambda r: r["walk_phases"][1].update(phase="move_1"),
            lambda r: r["walk_phases"][0].update(start_sec=53),
            lambda r: r["walk_phases"][1].update(start_sec=55),
            lambda r: r["walk_phases"][-1].update(end_sec=63),
            lambda r: [phase.update(state="not_performed", start_sec=None, end_sec=None, reason="실시하지 않음") for phase in r["walk_phases"]],
            lambda r: r.update(events=[self.event("reunion_contact_start", 38, segment="reunion"), self.event("reunion_contact_end", 35, segment="reunion")]),
            lambda r: r.update(events=[self.event(seconds=69)]),
            lambda r: r.update(events=[self.event(segment="reunion")]),
            lambda r: r.update(events=[self.event("walk_seated", 85, segment=None)]),
            lambda r: r.update(events=[self.event("walk_name", 45, segment=None)]),
            lambda r: r.update(events=[self.event("guardian_speech", 90, segment=None)]),
            lambda r: r.update(events=[self.event(video_id="not-registered")]),
            lambda r: r["segments"][2].update(state="shortened", reason="   "),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                record = self.recording()
                mutate(record)
                response = self.send(record)
                self.assertEqual(response.status_code, 422, response.text)
        record = self.recording()
        record["walk_phases"] = []
        self.assertEqual(self.send(record, confirm=False).status_code, 200)
        self.assertEqual(self.send(record, confirm=True, revision=self.get_case(self.item)["input_revision"]).status_code, 422)

    def test_non_contact_and_unobserved_never_acquire_a_time(self):
        record = self.recording()
        record["events"] = [self.event(seconds=None, status="not_occurred", note="접촉 시도하지 않음"),
                            self.event("stranger_contact_end", None, status="unobserved", note="다른 사람에 가림")]
        saved = self.save(record)
        self.assertEqual(saved["events"][0]["status"], "not_occurred")
        self.assertIsNone(saved["events"][0]["seconds"])
        record["events"][0]["seconds"] = 0
        self.assertEqual(self.send(record).status_code, 422)

    def test_interrupted_walking_keeps_actual_phases_and_skips_remaining_phases(self):
        record = self.recording()
        record["segments"][5].update(state="welfare_stopped", end_sec=57, reason="이동2 도중 불안으로 중단")
        record["walk_phases"][2].update(state="welfare_stopped", end_sec=57, reason="직원 중단 신호")
        for phase in record["walk_phases"][3:]:
            phase.update(state="not_performed", start_sec=None, end_sec=None, reason="중단 뒤 미실시")
        saved = self.save(record)
        self.assertEqual(saved["walk_phases"][2]["end_sec"], 57)
        self.assertIsNone(saved["walk_phases"][-1]["end_sec"])

    def test_other_camera_requires_manual_confirmed_offset(self):
        self.item = self.upload(self.item, data=b"second-source", name="second.mp4").json()
        other = self.item["manifest"]["sessions"][0]["videos"][1]
        record = self.recording()
        record["events"] = [self.event(seconds=79, video_id=other["video_id"])]
        self.save(record, confirm=False)
        self.assertEqual(self.send(record).status_code, 422)
        record["video_offsets"] = [{"video_id": other["video_id"], "offset_seconds": 5,
                                    "confirmed": True, "note": "양쪽 문 열림 프레임 수동 확인"}]
        saved = self.save(record)
        self.assertEqual(saved["events"][0]["seconds"], 79)  # Original source time is retained.
        record["video_offsets"][0]["note"] = "  "
        self.assertEqual(self.send(record).status_code, 422)
        record["video_offsets"][0].update(note="다시 확인", offset_seconds=100)
        self.assertEqual(self.send(record).status_code, 422)

    def test_revision_deletion_and_source_changes_during_probe_cannot_publish(self):
        record = self.recording()
        stale = self.item["input_revision"]
        self.probe.side_effect = lambda path: (self.save_metadata(), {"duration_sec": 100.0})[1]
        self.assertEqual(self.send(record, revision=stale).status_code, 409)
        self.assertIsNone(self.get_case(self.item)["manifest"]["sessions"][0]["recording"])
        self.probe.side_effect = lambda path: (path.write_bytes(b"changed-source"), {"duration_sec": 100.0})[1]
        self.assertEqual(self.send(record).status_code, 409)
        self.probe.side_effect = None
        self.assertEqual(self.send(record).status_code, 409)
        self.store.path(self.video["storage_ref"]).write_bytes(b"synthetic-video-one")
        self.probe.side_effect = lambda path: (self.delete_case(self.item), {"duration_sec": 100.0})[1]
        self.assertEqual(self.send(record).status_code, 403)

    def save_metadata(self):
        response = self.client.put(f"/api/cases/{self.item['case_id']}", json={
            "expected_revision": self.item["input_revision"], "participant_id": self.item["participant_id"],
            "dog_name": "판본 충돌 검증견"})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
