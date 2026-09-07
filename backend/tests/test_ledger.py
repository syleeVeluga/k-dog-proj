"""Guide-order attribution, program-owned counts and the shared-fact cross-check."""

import unittest

from app.ledger import (
    COUNT_ITEM_STEPS, STEPS, VERSION, branch_items, command_counts, context, count_problem,
    event_problem, ledger_schema, measures, validate_events,
)
from app.observation_models import LedgerResponse, MediaInfo
from app.video_models import LedgerEvent, Measurement, VideoItem


def media(audio="present", duration=60.0):
    return MediaInfo(video_id="v1", storage_ref="v1.mp4", sha256="a" * 64, size_bytes=10, duration_sec=duration,
                     codec="h264", width=320, height=240, audio_status=audio, mime_type="video/mp4", quality_flags=[])


def event(**value):
    base = {"step": "command_1", "kind": "command_utterance", "start_sec": 1.0, "end_sec": 2.0, "subject": "owner",
            "modality": "audio_video", "command": "c1", "observation": "가상 사건", "quality_flags": []}
    return LedgerEvent.model_validate({**base, **value})


def item(item_id, option, measurements):
    return VideoItem.model_validate({"item_id": item_id, "status": "scored", "selected_option_id": option,
                                     "evidence_ids": ("ev-1",), "reason": "합성", "coverage": "sufficient",
                                     "coverage_reason": "합성", "measurements": tuple(measurements)})


class LedgerContractTests(unittest.TestCase):
    def test_guide_order_covers_the_documented_capture_segments_once(self):
        self.assertEqual([s["step"] for s in STEPS], ["entry", "baseline_no_response", "separation", "reunion",
                         "command_1", "command_2", "command_3", "command_4", "play", "exit"])
        self.assertEqual([s["segment"] for s in STEPS],
                         ["입장", "분리", "분리", "분리", "훈련", "훈련", "훈련", "훈련", "놀이", "퇴장"])
        # R-09: 지시② is recorded but has no scoring row, so no item may be counted in it.
        self.assertEqual(next(s for s in STEPS if s["step"] == "command_2")["command"], "c2")
        self.assertFalse(any("command_2" in steps for steps in COUNT_ITEM_STEPS.values()))
        self.assertEqual(COUNT_ITEM_STEPS["OWN-11"], ("command_1", "command_3", "command_4"))
        self.assertEqual(len(branch_items("dog")), 36)
        self.assertEqual(len(branch_items("owner")), 19)
        self.assertEqual(set(branch_items("dog")) & set(branch_items("owner")), set())

    def test_schema_and_context_expose_the_order_without_scores(self):
        schema = ledger_schema(60.0)
        properties = schema["properties"]["events"]["items"]["properties"]
        self.assertEqual(properties["start_sec"]["maximum"], 60.0)
        self.assertNotIn("value", properties)
        self.assertNotIn("count", properties)
        self.assertNotIn("selected_option_id", properties)

        class Session:
            capture_mode, route_note, checklist = "sequential", "", {}

        value = context(Session(), media(), {"mode": "agentic"})
        self.assertEqual([s["order"] for s in value["steps"]], list(range(1, 11)))
        self.assertFalse(next(s for s in value["steps"] if s["step"] == "command_2")["scored"])
        self.assertEqual(value["sampling"], {"mode": "agentic"})
        self.assertEqual(value["scope"], "this_video_only")

    def test_silent_media_and_unattributed_voice_are_rejected(self):
        self.assertIsNone(event_problem(event(), media(), {}))
        self.assertIn("오디오가 없는", event_problem(event(), media(audio="absent"), {}))
        self.assertIn("보호자의 음성", event_problem(event(subject="dog"), media(), {}))
        self.assertIn("보호자의 음성", event_problem(event(modality="video"), media(), {}))
        self.assertIn("영상 길이", event_problem(event(start_sec=59.0, end_sec=61.0), media(), {}))
        self.assertIn("끝이 시작보다", event_problem(event(start_sec=5.0, end_sec=1.0), media(), {}))
        self.assertIn("다른 지시어", event_problem(event(command="c3"), media(), {}))
        # An operator checklist mark may not veto an observed fact.
        self.assertIsNone(event_problem(event(), media(), {"training": "skipped"}))
        self.assertIsNone(event_problem(event(step="unknown"), media(), {"training": "skipped"}))
        with self.assertRaises(ValueError):
            validate_events([event(), event(subject="staff")], media(), {})

    def performance(self, command, start, **value):
        return event(kind="dog_performance", subject="dog", modality="video", command=command,
                     start_sec=start, end_sec=start + 0.5, **value)

    def test_a_trial_ends_only_when_the_commanded_behavior_is_performed(self):
        events = [event(start_sec=1.0, end_sec=1.5), event(start_sec=2.0, end_sec=2.5),
                  self.performance("c1", 3.0), event(start_sec=4.0, end_sec=4.5),
                  event(step="command_3", command="c3", start_sec=10.0, end_sec=10.5),
                  self.performance("none", 11.0, step="command_3"),
                  event(step="command_3", command="c3", start_sec=12.0, end_sec=12.5)]
        counts = command_counts(events)
        # 지시① ends at its own performance; the later call belongs to no count.
        self.assertEqual(counts["command_1"], {"count": 2, "talk_count": 2})
        # An unrelated behavior at 11s must not end 지시③.
        self.assertEqual(counts["command_3"], {"count": 2, "talk_count": 2})
        self.assertEqual(counts["command_4"], {"count": 0, "talk_count": 0})

    def test_guardian_talk_counts_mixed_words_and_play_cues(self):
        events = [event(start_sec=1.0, end_sec=1.5), event(command="other", start_sec=2.0, end_sec=2.5),
                  event(start_sec=3.0, end_sec=3.5),
                  event(step="play", kind="play_cue", command="other", start_sec=20.0, end_sec=20.5),
                  event(step="play", kind="play_cue", command="other", start_sec=21.0, end_sec=21.5),
                  event(step="play", kind="play_cue", command="other", start_sec=22.0, end_sec=22.5)]
        counts = command_counts(events)
        # DOG-13 asks how often 지시① itself was given; OWN-11 asks how much the guardian talked.
        self.assertEqual(counts["command_1"], {"count": 2, "talk_count": 3})
        # play_cue is the kind the prompt assigns to 놀이 지시·말, so OWN-18 must see it.
        self.assertEqual(counts["play"], {"count": 3, "talk_count": 3})
        value = measures(events)
        self.assertEqual({row["step"] for row in value["command_counts"]}, {"command_1", "play"})
        interval = next(row for row in value["command_counts"] if row["step"] == "command_1")
        self.assertEqual((interval["start_sec"], interval["end_sec"]), (1.0, 3.5))
        self.assertNotIn("unknown", value["observed_steps"])

    def test_segments_without_a_command_get_no_count_row(self):
        events = [event(step="entry", kind="other", subject="dog", modality="video", command="none",
                        start_sec=0.0, end_sec=1.0),
                  event(step="reunion", kind="dog_settled", subject="dog", modality="video", command="none",
                        start_sec=5.0, end_sec=6.0)]
        value = measures(events)
        self.assertEqual(value["command_counts"], [])
        self.assertEqual({row["step"] for row in value["step_intervals"]}, {"entry", "reunion"})

    def test_unknown_attribution_is_never_counted(self):
        counts = command_counts([event(step="unknown"), event(step="unknown")])
        self.assertEqual(sum(row["talk_count"] for row in counts.values()), 0)
        self.assertEqual(measures([event(step="unknown")])["command_counts"], [])

    def test_branch_measurement_must_match_the_ledger_count(self):
        value = measures([event(start_sec=1.0, end_sec=1.5), self.performance("c1", 2.0)])
        good = Measurement(kind="command_count", value=1.0, start_sec=1.0, end_sec=1.5)
        self.assertIsNone(count_problem(item("DOG-13", "DOG-13:S1", [good]), good, value))
        wrong = Measurement(kind="command_count", value=3.0, start_sec=1.0, end_sec=1.5)
        self.assertIn("사건 원장 계산값", count_problem(item("DOG-13", "DOG-13:S2", [wrong]), wrong, value))
        # DOG-14 belongs to 지시③, which this ledger never recorded.
        self.assertIn("귀속되지 않습니다", count_problem(item("DOG-14", "DOG-14:S1", [good]), good, value))
        # Items without a shared count keep their own evidence rules.
        self.assertIsNone(count_problem(item("BS-01", "BS-01:S1", [good]), good, value))

    def test_a_measurement_outside_every_allowed_trial_is_never_accepted(self):
        # 지시② carries four calls but has no scoring row, and 지시①/③/④ have one each.
        events = [event(start_sec=1.0, end_sec=1.5),
                  *[event(step="command_2", command="c2", start_sec=t, end_sec=t + 0.5) for t in (20.0, 21.0, 22.0, 23.0)],
                  event(step="command_3", command="c3", start_sec=30.0, end_sec=30.5),
                  event(step="command_4", command="c4", start_sec=40.0, end_sec=40.5)]
        value = measures(events)
        inside_two = Measurement(kind="command_count", value=4.0, start_sec=20.0, end_sec=23.5)
        self.assertIn("귀속되지 않습니다", count_problem(item("OWN-11", "OWN-11:S3", [inside_two]), inside_two, value))
        whole = Measurement(kind="command_count", value=3.0, start_sec=1.0, end_sec=40.5)
        self.assertIn("여러 시행", count_problem(item("OWN-11", "OWN-11:S2", [whole]), whole, value))
        one = Measurement(kind="command_count", value=1.0, start_sec=30.0, end_sec=30.5)
        self.assertIsNone(count_problem(item("OWN-11", "OWN-11:S1", [one]), one, value))

    def test_guardian_items_are_checked_against_talk_and_dog_items_against_the_command(self):
        events = [event(start_sec=1.0, end_sec=1.5), event(command="other", start_sec=2.0, end_sec=2.5),
                  event(start_sec=3.0, end_sec=3.5), self.performance("c1", 4.0)]
        value = measures(events)
        span = {"start_sec": 1.0, "end_sec": 3.5}
        talk = Measurement(kind="command_count", value=3.0, **span)
        same = Measurement(kind="command_count", value=2.0, **span)
        self.assertIsNone(count_problem(item("OWN-11", "OWN-11:S2", [talk]), talk, value))
        self.assertIn("사건 원장 계산값", count_problem(item("OWN-11", "OWN-11:S2", [same]), same, value))
        self.assertIsNone(count_problem(item("DOG-13", "DOG-13:S2", [same]), same, value))
        self.assertIn("사건 원장 계산값", count_problem(item("DOG-13", "DOG-13:S2", [talk]), talk, value))

    def test_guardian_play_talk_cannot_be_scored_as_silence(self):
        events = [event(step="play", kind="play_cue", command="other", start_sec=t, end_sec=t + 0.5)
                  for t in (20.0, 21.0, 22.0)]
        value = measures(events)
        row = next(r for r in value["command_counts"] if r["step"] == "play")
        self.assertEqual(row["talk_count"], 3)
        silent = Measurement(kind="command_count", value=0.0, start_sec=20.0, end_sec=22.5)
        self.assertIn("사건 원장 계산값", count_problem(item("OWN-18", "OWN-18:S4", [silent]), silent, value))
        honest = Measurement(kind="command_count", value=3.0, start_sec=20.0, end_sec=22.5)
        self.assertIsNone(count_problem(item("OWN-18", "OWN-18:S2", [honest]), honest, value))

    def test_a_stored_ledger_from_an_earlier_counting_rule_is_not_re_derived(self):
        from app.analysis import validated_ledger

        class Run:
            run_id = "r1"

        events = [event(start_sec=1.0, end_sec=1.5)]
        payload = {"run_id": "r1", "video_id": "v1", "events": [e.model_dump(mode="json") for e in events],
                   "measures": measures(events), "unconfirmed_conditions": [], "usage": {}}
        self.assertEqual(validated_ledger(payload, Run(), "v1").video_id, "v1")
        tampered = {**payload, "measures": {**payload["measures"], "command_counts": []}}
        with self.assertRaises(ValueError):
            validated_ledger(tampered, Run(), "v1")
        # An older ledger version keeps the values its run was judged under.
        frozen = {**payload, "measures": {**payload["measures"], "version": "ledger-1.0", "command_counts": []}}
        self.assertEqual(validated_ledger(frozen, Run(), "v1").measures["version"], "ledger-1.0")
        self.assertEqual(payload["measures"]["version"], VERSION)

    def test_response_contract_selects_the_ledger_model(self):
        from app.gemini import response_contract
        schema, model = response_contract({"ledger": True}, 12.0)
        self.assertIs(model, LedgerResponse)
        self.assertEqual(schema, ledger_schema(12.0))
        self.assertEqual(response_contract({"direct_video": True}, 12.0)[1].__name__, "VideoResponse")
        self.assertEqual(response_contract({}, 12.0)[1].__name__, "ObservationResponse")


if __name__ == "__main__":
    unittest.main()
