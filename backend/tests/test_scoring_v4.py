"""SRC02 §7–8, Appendix B/C and acceptance T03–T18 synthetic goldens."""
import copy
from fractions import Fraction
import json
from types import SimpleNamespace
import unittest

from pydantic import ValidationError
from app.domain.catalog_v4 import load_catalog_v4, load_rules_v4
from app.domain.contracts_v4 import ScoreSheetV4
from app.domain.results_v4 import CalculationConditionsV4
from app.recording_v4 import build_windows_v4
from app.scoring_v4 import calculate, dominant_type, vocal_score
from app.sheets_v4 import asset_hashes
from tests.test_recording_v4 import event, fixture, recording


def document(values=None, *, exceptions=None, events=None, missing=None, vocal=None):
    raw = fixture()
    raw["events"] = events or [event("contact", "stranger_contact_start", "stranger", 235), event("contact-end", "stranger_contact_end", "stranger", 238)]
    capture = recording(raw)
    windows = build_windows_v4(capture)
    indexed = {window.window_id: window for window in windows}
    catalog = {item.code: item for item in load_catalog_v4().items}
    observations = []
    for code, value in (values or {}).items():
        definition = catalog[code]
        window = indexed[definition.windows[0]]
        start = window.start_seconds or 0
        end = window.end_seconds or start + 1
        observation = {"code": code, "value": value, "status": "observed", "opportunity": "present", "validity": "valid", "whole_interval_observed": True,
            "evidence": [{"video_id": "v1", "video_sha256": "1" * 64, "camera_id": "CAM1", "window_id": window.window_id,
                          "start_seconds": start, "end_seconds": end, "observed_seconds": end-start, "note": "synthetic actual evidence"}]}
        if code in (vocal or {}):
            observation["vocalization"] = {"listened_seconds": end-start, "cumulative_vocal_seconds": vocal[code], "whole_interval_judged": True, "note": "synthetic whole audio"}
        observations.append(observation)
    for code in missing or ():
        observations.append({"code": code, "value": None, "status": "unobserved", "reason": "synthetic missing"})
    phases = [{"code": f"개{38+i}", "proximity_exception": (exceptions or ["none"]*6)[i]} for i in range(6)]
    sheet = ScoreSheetV4.model_validate_json(json.dumps({"sheet_id": "s", "case_id": "c", "session_id": "session", "batch_id": "batch",
        "rater_id": "human", "rater_kind": "human", "input_revision": 1, "input_sha256": "2"*64,
        "observations": observations, "walk_phases": phases}))
    return SimpleNamespace(sheet=sheet, source=SimpleNamespace(session=SimpleNamespace(recording_s1=capture), windows=windows, asset_hashes=asset_hashes()))


def metrics(doc, **kwargs):
    return {item.key: item for item in calculate(doc, **kwargs).metrics}


class ScoringV4Tests(unittest.TestCase):
    def test_walk_six_denominator_and_guardian_approach(self):
        values = dict(zip((f"개{n}" for n in range(38,44)), (0,0,2,3,2,0))) | {"보13": 1}
        result = metrics(document(values))
        self.assertEqual((result["개26"].value,result["개36"].value,result["개27"].value), (1,2,.5))
        result = metrics(document(values, exceptions=["none"]*5+["guardian_approach"]))
        self.assertEqual((result["개27"].numerator,result["개27"].denominator,result["개27"].value), (2,6,2/6))

    def test_walk_far_recheck_close_unknown_and_missing_hold(self):
        values = dict(zip((f"개{n}" for n in range(38,44)), (0,0,2,3,2,0))) | {"보13": 1}
        for exceptions in (["none","none","recheck","none","none","none"], ["unknown"]+["none"]*5):
            self.assertEqual(metrics(document(values,exceptions=exceptions))["개27"].status,"condition_unknown")
        values.pop("개43")
        self.assertIsNone(metrics(document(values))["개27"].value)

    def test_walk_caution_invalid_and_departure_excluded(self):
        values={f"개{n}":1 for n in range(38,44)}|{"보13":2,"개37":3}
        self.assertTrue(metrics(document(values))["개27"].caution)
        self.assertEqual(metrics(document(values))["개27"].value,1)
        values["보13"]=3
        self.assertEqual(metrics(document(values))["개27"].status,"invalid")

    def test_w_is_independent_of_ignore_contact_and_keeps_direction(self):
        for alone,reunion,expected in [(-2,0,2),(2,0,2),(-2,2,0),(0,0,0)]:
            result=metrics(document({"개58":alone,"개18":reunion,"보12":3},missing=["개19","개44"]))["W"]
            self.assertEqual(result.value,expected)
            self.assertEqual([item.value for item in result.inputs[:2]],[alone,reunion])

    def test_all_25_separation_rows_match_appendix_c_descriptions(self):
        initial=["문·안전문을 향해 뛰거나 앞발을 걸어 올림", "위 행동 없이 문을 코·앞발로 건드림", "접촉 없이 문 앞 몸길이 1개 이내에서 처음 10초 중 합계 5초 초과 머묾", "문 쪽을 향하거나 다가갔으나 위 행동은 없음", "문 쪽 방향 전환·접근이 관찰되지 않음"]
        later=["문을 반복해서 긁거나 문·안전문을 넘으려 시도함", "위 행동 없이 문을 코·앞발로 건드리거나, 문을 떠났다가 확인하러 2회 이상 돌아옴", "위 행동 없이 관찰 시간의 절반 초과를 문 앞에서 조용히 서거나 앉거나 엎드려 머묾", "위 행동 없이 관찰 시간의 절반 초과를 문에서 떨어진 곳에서 조용히 서거나 앉거나 엎드려 머묾", "위 행동 없이 관찰 시간의 절반 초과를 환경 탐색·자기 활동으로 보냄"]
        for a in range(-2,3):
            for b in range(-2,3):
                with self.subTest(a=a,b=b):
                    expected=f"처음 10초: {initial[a+2]}. 이후 50초: {later[b+2]}."
                    self.assertTrue(metrics(document({"개9":a,"개10":b}))["개60"].value.startswith(expected))
        self.assertIsNone(metrics(document({"개9":2}))["개60"].value)

    def test_object_same_identity_condition_and_no_nose_latency(self):
        values={"개30":3,"개34":0,"보14":1}
        self.assertEqual(metrics(document(values))["object_change"].status,"condition_unknown")
        for same,status in [(True,"calculated"),(False,"invalid")]:
            condition=CalculationConditionsV4(same_object=same,same_object_reason="synthetic identity inspection")
            item=metrics(document(values),conditions=condition)["object_change"]
            self.assertEqual(item.status,status)
            if same:self.assertEqual(item.value,"회피 감소")
        values["보14"]=2
        self.assertTrue(metrics(document(values),conditions=CalculationConditionsV4(same_object=True,same_object_reason="same"))["object_change"].caution)

    def test_entry_object_positive_is_hesitation_not_advance(self):
        self.assertEqual(metrics(document({"개5":1,"개30":2},missing=["개6"]))["BY"].value,"자극에 따라 다름")
        self.assertEqual(metrics(document({"개5":0,"개30":2}))["BY"].value,"주저 근거")
        self.assertIsNone(metrics(document({"개30":2}))["BY"].value)

    def test_people_four_values_direction_and_internal_ax(self):
        result=metrics(document({"개13":-2,"개14":-1,"개15":0,"개55":1}))
        self.assertEqual([result[key].value for key in ("BD","BE","BF","people_negative_mean","people_positive_mean","AX")],[3,1,4,.75,.25,50])
        self.assertTrue(result["AX"].internal_only)
        self.assertIsNone(metrics(document({"개13":-2,"개14":-1,"개15":0}))["AX"].value)

    def test_no_stranger_contact_excludes_contact_values(self):
        result=metrics(document({"개13":0,"개14":0,"개51":0,"개52":0,"개53":2}))
        self.assertEqual(result["BF"].value,2)
        self.assertTrue({"개51","개52"} <= set(result["BF"].excluded))
        self.assertIsNone(result["AX"].value)

    def test_reunion_direction_sum_is_not_divided_by_six(self):
        values={"개17":-2,"개19":-1,"개22":2,"보12":1}
        result=metrics(document(values))
        self.assertEqual((result["AE"].value,result["AF"].value),(3,2))
        values["보12"]=3
        self.assertEqual(metrics(document(values))["AE"].status,"invalid")

    def test_vocal_exact_thresholds_actual_interval_and_no_audio(self):
        for seconds,expected in [(0,0),(20,1),(40,2),(40.1,3)]:
            self.assertEqual(vocal_score(60,seconds),expected)
            doc=document({"개11":expected},vocal={"개11":seconds})
            self.assertEqual(metrics(doc,audio_available={"개11":True})["개11"].value,expected)
            self.assertIsNone(metrics(doc,audio_available={"개11":False})["개11"].value)
        self.assertEqual(vocal_score(30,10),1)
        for value in (True,float('nan'),float('inf'),"10"):
            with self.assertRaises((ValueError,OverflowError)):vocal_score(60,value)

    def test_vocal_inconsistent_raw_and_partial_denominator_rejected(self):
        with self.assertRaises(ValueError):metrics(document({"개11":3},vocal={"개11":20}),audio_available={"개11":True})
        doc=document({"개11":1},vocal={"개11":20})
        item=doc.sheet.observations[0]
        doc.sheet=doc.sheet.model_copy(update={"observations":(item.model_copy(update={"whole_interval_observed":False}),)})
        self.assertIsNone(metrics(doc,audio_available={"개11":True})["개11"].value)

    def test_all_29_owner_points_match_appendix_b(self):
        rows={"보6":[(2,0,0),(0,2,0),(0,2,0),(0,0,1),(0,0,2)],"보9":[(2,0,0),(0,2,0),(0,1,0),(0,0,1),(0,0,2)],
              "보22":[(0,2,0),(0,2,0),(0,0,0),(0,0,1),(0,0,2)],"보23":[(0,0,0),(0,0,0),(0,0,0),(0,0,1),(0,0,2)],
              "보24":[(0,0,1),(2,0,0),(0,2,0),(0,0,0),(0,0,2)],"보39":[(0,0,1),(2,0,0),(0,2,0),(0,0,2)]}
        count=0
        for code,points in rows.items():
            for value,expected in zip(range(0,4) if code=="보39" else range(-2,3),points):
                result=calculate(document({code:value,"보38":3,"보40":1})).owner
                actual=next(item for item in result.items if item.code==code)
                self.assertEqual(actual.points,expected)
                self.assertEqual(actual.used,bool(sum(expected)))
                count+=1
        self.assertEqual(count,29)

    def test_t10_five_source_examples_scene_averages(self):
        examples=[({"보6":-2,"보9":-2,"보39":1,"보38":1},"허용형",(1.,0.,0.)),
                  ({"보6":-1,"보9":0,"보22":-1,"보38":2},"조율형",(0.,1.,0.)),
                  ({"보6":2,"보9":1,"보22":2,"보38":2},"통제형",(0.,0.,1.)),
                  ({"보6":-2,"보9":-2,"보22":-2,"보38":2},None,(.5,.5,0.)),
                  ({"보6":-2,"보9":-2,"보22":0,"보38":2},None,None)]
        for values,label,ratios in examples:
            result=calculate(document(values)).owner
            self.assertEqual((result.label,result.ratios),(label,ratios))
            if ratios is None:self.assertEqual((result.valid_items,result.valid_scenes),(2,1))

    def test_owner_unknown_opportunity_and_safety_action_excluded(self):
        result=calculate(document({"보6":-2,"보9":-2,"보22":-2})).owner
        self.assertIsNone(result.ratios)
        self.assertEqual(next(item for item in result.items if item.code=="보22").points,(0,2,0))
        stopped=event("stop","staff_stop","entry",0)
        result=calculate(document({"보6":-2,"보9":-2,"보39":1,"보38":1},events=[stopped])).owner
        self.assertFalse(next(item for item in result.items if item.code=="보6").used)

    def test_owner_exact_dominance_and_margin_edges_not_rounded(self):
        rules=load_rules_v4()
        for ratios,expected in [((Fraction(3,5),Fraction(2,5),Fraction(0)),"허용형"),
                                ((Fraction(599999,1000000),Fraction(400001,1000000),Fraction(0)),None),
                                ((Fraction(1,2),Fraction(1,2),Fraction(0)),None)]:
            self.assertEqual(dominant_type(ratios,rules),expected)
        # A pure threshold comparison is also checked at the 15%p margin itself.
        custom=copy.deepcopy(rules);custom["owner_type_thresholds"]["dominance"]=.5
        self.assertEqual(dominant_type((Fraction(1,2),Fraction(35,100),Fraction(15,100)),custom),"허용형")
        self.assertIsNone(dominant_type((Fraction(1,2),Fraction(350001,1000000),Fraction(149999,1000000)),custom))

    def test_empty_input_no_zero_type_or_retired_calculation(self):
        result=calculate(document())
        self.assertIsNone(result.owner.ratios)
        self.assertTrue(all(item.value is None for item in result.metrics))
        self.assertFalse({item.key for item in result.metrics}&{"V","AW","AY","개32"})
        self.assertEqual(result.safe_base.status,"unconfirmed")
        self.assertEqual(set(result.policy_pending_codes),{"보5","개21"})

    def test_g_review_notes_removed_but_f_evidence_retained(self):
        doc=document({"개58":-2,"개18":0})
        item=doc.sheet.observations[0].model_copy(update={"review_memo":"DO_NOT_ANALYZE_G"})
        doc.sheet=doc.sheet.model_copy(update={"observations":(item,doc.sheet.observations[1])})
        result=calculate(doc)
        self.assertNotIn("DO_NOT_ANALYZE_G",result.model_dump_json())
        self.assertIn("synthetic actual evidence",result.model_dump_json())

    def test_raw_forged_values_and_changed_rule_snapshot_rejected(self):
        for value in [True,1.5,"1",99]:
            doc=document({"개58":0})
            item=doc.sheet.observations[0].model_copy(update={"value":value})
            doc.sheet=doc.sheet.model_copy(update={"observations":(item,)})
            with self.assertRaises(ValueError):calculate(doc)
        rules=copy.deepcopy(load_rules_v4());rules["owner_type_points"][0]["points"]=[0,0,2]
        with self.assertRaises(ValueError):calculate(document(),rules=rules)

    def test_safe_base_actual_order_has_no_numeric_score(self):
        events=[event("approach","guardian_approach","reunion",114),event("contact","guardian_contact","reunion",128,130),event("explore","exploration_resumed","reunion",135)]
        doc=document(events=events)
        raw=doc.source.session.recording_s1.model_dump(mode="json")
        raw["safe_base_sequence"]={"approach_event_id":"approach","contact_event_id":"contact","exploration_event_id":"explore","note":"actual sequence"}
        doc.source.session.recording_s1=recording(raw)
        doc.source.windows=build_windows_v4(doc.source.session.recording_s1)
        result=calculate(doc).safe_base
        self.assertEqual(result.status,"confirmed_sequence")
        self.assertEqual(result.reference_seconds,(114.,128.,135.))
        self.assertNotIn("score",result.model_dump())

    def test_source_asset_or_actual_window_cannot_be_silently_replaced(self):
        doc=document({"개58":-2,"개18":0})
        doc.source.asset_hashes["scoring"]="0"*64
        with self.assertRaises(ValueError):calculate(doc)
        doc=document({"개58":-2,"개18":0})
        doc.source.windows=doc.source.windows[:-1]
        with self.assertRaises(ValueError):calculate(doc)

    def test_later_separation_partial_observation_is_not_a_category(self):
        doc=document({"개9":2,"개10":1})
        later=doc.sheet.observations[1].model_copy(update={"whole_interval_observed":False})
        doc.sheet=doc.sheet.model_copy(update={"observations":(doc.sheet.observations[0],later)})
        self.assertIsNone(metrics(doc)["개60"].value)
