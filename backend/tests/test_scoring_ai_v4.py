"""Synthetic S1 provider contracts; never sends participant media or live API calls."""
import copy
from types import SimpleNamespace
import unittest
from fastapi import HTTPException
from pydantic import ValidationError

from app import scoring_ai_v4 as ai
from app.domain.catalog_v4 import MEMO_CODES, NUMERIC_CODES, load_catalog_v4
from app.domain.preprocess_v4 import BatchV4
from app.domain.runs_v4 import RunInputV4, StageV4
from app.input_models_v4 import new_session_v4, SessionV4
from app.preprocess_v4 import _assets
from app.recording_v4 import build_windows_v4
from app.scoring_v4 import RULE_HASH
from app.storage import encode
from tests.test_recording_v4 import fixture, recording, event


def snapshot(cameras=1):
    raw=fixture()
    raw["events"]=[event("floor","floor_contact","entry",3,4),event("object","object_stop","entry",10,15),
                   event("contact","reunion_contact_start","reunion",128),event("contact-end","reunion_contact_end","reunion",130),
                   event("stranger","stranger_contact_start","stranger",235),event("stranger-end","stranger_contact_end","stranger",238)]
    raw["video_offsets"]=[{"video_id":f"v{n}","offset_seconds":float(n-1),"confirmed":True,"note":"synthetic sync"} for n in range(2,cameras+1)]
    capture=recording(raw)
    session=new_session_v4("session").model_dump(mode="json")
    session["recording_s1"]=capture.model_dump(mode="json")
    session["videos"]=[{"schema_version":"4.0","video_id":f"v{n}","upload_id":f"u{n}","original_name":f"synthetic{n}.mp4","storage_ref":f"videos/v{n}.mp4",
                         "sha256":str(n)*64,"size_bytes":1,"camera_id":f"CAM{n}","source_original_number":str(n),"source_kind":"original","media_status":"pending_probe"} for n in range(1,cameras+1)]
    session=SessionV4.model_validate_json(encode(session))
    windows=build_windows_v4(capture)
    files=[{"ref":video.storage_ref,"hash":video.sha256} for video in session.videos]
    clips=[]
    for n in range(1,cameras+1):
        derivative={"ref":f"clips/synthetic/c{n}.mp4","hash":"f"*64,"size_bytes":1,"duration_seconds":300.,"source_time_offset_seconds":0.,
                    "frame_times_seconds":[0.,1.],"source_frame_times_seconds":[0.,1.],"audio_ranges":[{"start_seconds":0.,"end_seconds":300.}],"fps_policy":"one_actual_frame_per_second"}
        clips.append({"clip_id":f"c{n}","video_id":f"v{n}","camera_id":f"CAM{n}","source_start_seconds":0.,"source_end_seconds":300.,"offset_seconds":float(n-1),
                      "window_ids":[window.window_id for window in windows],"status":"complete","ai":derivative,"original":{**derivative,"ref":f"clips/synthetic/o{n}.mp4","fps_policy":"source_frames"}})
    logical=[]
    catalog=load_catalog_v4()
    for window in windows:
        duration=sum(part.end_seconds-part.start_seconds for part in window.source_intervals if part.evidence_id is None)
        views=[{"video_id":f"v{n}","camera_id":f"CAM{n}","offset_seconds":float(n-1),"source_start_seconds":None if window.start_seconds is None else window.start_seconds+n-1,
                "source_end_seconds":None if window.end_seconds is None else window.end_seconds+n-1,"clip_ids":[f"c{n}"],"availability":"available"} for n in range(1,cameras+1)]
        logical.append({"window":window.model_dump(mode="json"),"item_codes":[item.code for item in catalog.rated_items() if window.window_id in item.windows],
                        "views":views,"media_available_seconds":duration,"representative_audio_video_id":"v1","audio_selection_reason":"synthetic audio","audio_available_seconds":duration})
    batch=BatchV4.model_validate_json(encode({"batch_id":"batch","claim_token":"token","case_id":"case","session_id":"session","input_revision":1,
        "input":{"ref":"inputs/case-r1.json","hash":"a"*64},"created_at":"synthetic","status":"complete","request":{"request_id":"synthetic","expected_revision":1},
        "compatibility_hash":"b"*64,"asset_hashes":_assets(),"cut_settings":{},"encoder_version":"synthetic","source_files":files,"source_metadata":[],
        "recording":capture.model_dump(mode="json"),"clips":clips,"windows":logical}))
    return RunInputV4(case_id="case",session_id="session",input_revision=1,input={"manifest_ref":"inputs/case-r1.json","manifest_hash":"a"*64},session=session,
        preprocess={"ref":"clips/synthetic/batch.json","hash":"c"*64,"batch_id":"batch"},batch=batch,calculation_hash=RULE_HASH,requested_by="operator")


def group(code):
    key,definition=next((key,value) for key,value in ai.groups().items() if code in value["codes"])
    return StageV4.model_validate_json(encode({"stage":"score_v4","key":key,"item_codes":definition["codes"],"window_ids":definition["windows"],"prompt":"synthetic",
        "response_schema":ai.response_schema(definition["codes"]),"provider":"gemini" if definition["provider_call"] else "program", "provider_call":definition["provider_call"],
        "model":"gemini-3.8-flash" if definition["provider_call"] else "program","production_fps":"one_actual_frame_per_second","request_fps":1.}))


def response(stage, code=None, value=None, evidence=(), **extra):
    values=[]
    for item in stage.item_codes:
        values.append({"code":item,"value":value,"status":"observed","opportunity":"present","validity":"valid","evidence":list(evidence),**extra} if item==code else
                      {"code":item,"value":None,"status":"unobserved","reason":"synthetic missing"})
    return {"case_id":"case","session_id":"session","batch_id":"batch","observations":values,"events":[],"linked_memos":[]}


def basis(clip="c1",window="entry_whole",start=0,end=30):
    return {"clip_id":clip,"window_id":window,"start_seconds":float(start),"end_seconds":float(end),"observed_seconds":float(end-start),"note":"synthetic actual observation"}


class AiNormalizationV4Tests(unittest.TestCase):
    def test_provider_schema_requires_evidence_state_and_literal_contract_version(self):
        schema = ai.response_schema(["개5"])
        row = schema["$defs"]["AiRowV4"]
        self.assertTrue({"evidence", "opportunity", "validity", "whole_interval_observed", "event_ids", "vocalization"} <= set(row["required"]))
        for definition in [schema, *schema["$defs"].values()]:
            self.assertEqual(definition["properties"]["schema_version"]["enum"], ["4.0"])
            self.assertNotIn("const", definition["properties"]["schema_version"])
        observed, missing = row["anyOf"]
        self.assertEqual(observed["properties"]["evidence"]["minItems"], 1)
        self.assertEqual(observed["properties"]["value"]["type"], "integer")
        self.assertEqual(missing["properties"]["value"]["type"], "null")
        self.assertNotIn("observed", missing["properties"]["status"]["enum"])
        self.assertEqual(ai.response_schema(["보25"])["$defs"]["AiRowV4"]["anyOf"][0]["properties"]["value"]["type"], "string")
        self.assertIn("$ref", ai.response_schema(["바6"])["$defs"]["AiRowV4"]["anyOf"][0]["properties"]["vocalization"])

    def test_repair_errors_omit_provider_input_and_preserve_actionable_location(self):
        raw = response(group("개5"))
        raw["schema_version"] = "synthetic-private-input"
        try:
            ai.AiResponseV4.model_validate_json(encode(raw))
        except ValidationError as exc:
            errors = ai.contract_errors(exc)
        self.assertEqual(errors[0]["location"], ["schema_version"])
        instruction = ai.repair_instruction(errors)
        self.assertIn("4.0", instruction)
        self.assertIn("schema_version", instruction)
        self.assertNotIn("synthetic-private-input", instruction)
        self.assertNotIn("input_value", instruction)
        self.assertIn("null", instruction)

    def test_repair_errors_redact_dynamic_extra_field_names(self):
        raw = response(group("개5"))
        private_key = "https://synthetic.invalid/private-key-" + "x" * 2000
        raw[private_key] = "synthetic-private-value"
        raw["observations"][0][private_key] = "synthetic-private-value"
        with self.assertRaises(ValidationError) as caught:
            ai.AiResponseV4.model_validate_json(encode(raw))
        errors = ai.contract_errors(caught.exception)
        instruction = ai.repair_instruction(errors)
        self.assertNotIn(private_key, encode(errors))
        self.assertNotIn(private_key, instruction)
        self.assertNotIn("synthetic-private-value", instruction)
        self.assertEqual({tuple(error["location"]) for error in errors},
                         {("<unexpected_field>",), ("observations", 0, "<unexpected_field>")})

    def test_exact_86_direct_paths_83_numeric_3_memo_and_dynamic_groups(self):
        values=ai.groups();codes=[code for value in values.values() for code in value["codes"]]
        self.assertEqual(set(codes),set(NUMERIC_CODES+MEMO_CODES));self.assertEqual(len(codes),86)
        self.assertEqual(sum(value["provider_call"] for value in values.values()),42)
        self.assertNotIn("개59",codes)
        self.assertFalse(next(value for value in values.values() if "개21" in value["codes"])["provider_call"])

    def test_category_normalizes_to_actual_original_hash_camera_times(self):
        source=snapshot();stage=group("개5")
        raw=response(stage,"개5",1,[basis(start=1,end=2)])
        result=ai.normalize(source,stage,raw)
        evidence=next(item for item in result["observations"] if item["code"]=="개5")["evidence"][0]
        self.assertEqual((evidence["video_id"],evidence["video_sha256"],evidence["camera_id"],evidence["start_seconds"]),("v1","1"*64,"CAM1",1))
        self.assertNotIn("clip_id",evidence)

    def test_wrong_identity_auto_duplicates_retired_and_invalid_raw_values(self):
        source=snapshot();stage=group("개5");raw=response(stage)
        variants=[]
        for key in ("case_id","session_id","batch_id"):
            altered=copy.deepcopy(raw);altered[key]="foreign";variants.append(altered)
        altered=copy.deepcopy(raw);altered["observations"].append(altered["observations"][0]);variants.append(altered)
        for code in ("개26","개32","개59"):
            altered=copy.deepcopy(raw);altered["observations"][0]["code"]=code;variants.append(altered)
        for value in (True,"1",3,1.2):variants.append(response(stage,"개5",value,[basis(start=1,end=2)]))
        for value in variants:
            with self.assertRaises(ValueError):ai.normalize(source,stage,value)

    def test_foreign_clip_window_and_out_of_range_time_reject(self):
        source=snapshot();stage=group("개5")
        for evidence in (basis(clip="foreign"),basis(window="alone_whole"),basis(start=299,end=301),basis(start=29,end=31)):
            with self.assertRaises((ValueError,Exception)):ai.normalize(source,stage,response(stage,"개5",1,[evidence]))

    def test_three_views_of_one_event_never_become_count_three(self):
        source=snapshot(3);stage=group("바14")
        views=[basis(f"c{n}",start=5+n-1,end=6+n-1) for n in range(1,4)]
        evidence=[basis(f"c{n}",start=n-1,end=30+n-1) for n in range(1,4)]+views
        raw=response(stage,"바14",1,evidence,whole_interval_observed=True,event_ids=["same-event"])
        raw["events"]=[{"event_id":"same-event","item_codes":["바14"],"views":views,"note":"one body shake, three cameras"}]
        normalized=ai.normalize(source,stage,raw)
        self.assertEqual(next(item for item in normalized["observations"] if item["code"]=="바14")["value"],1)
        raw["observations"][0]["value"]=3
        with self.assertRaises(ValueError):ai.normalize(source,stage,raw)

    def test_duplicate_event_names_for_overlapping_camera_evidence_rejected(self):
        source=snapshot(3);stage=group("바14")
        raw=response(stage,"바14",2,[basis()],whole_interval_observed=True,event_ids=["one","two"])
        raw["events"]=[{"event_id":name,"item_codes":["바14"],"views":[basis(clip,start=5+offset,end=6+offset)],"note":"same moment"} for name,clip,offset in (("one","c1",0),("two","c2",1))]
        with self.assertRaises(ValueError):ai.normalize(source,stage,raw)

    def test_shared_event_identity_preserves_different_notes_but_requires_same_times_and_amount(self):
        source=snapshot();stage=group("바14")
        view=basis(start=5,end=6)
        event_basis={**view,"note":"one shared body shake"}
        row_basis={**view,"note":"body shake counted once"}
        raw=response(stage,"바14",1,[basis(),row_basis],whole_interval_observed=True,event_ids=["one"])
        raw["events"]=[{"event_id":"one","item_codes":["바14"],"views":[event_basis],"note":"shared event"}]
        normalized=ai.normalize(source,stage,raw)
        observation=next(item for item in normalized["observations"] if item["code"]=="바14")
        self.assertEqual(observation["value"],1)
        self.assertEqual(observation["evidence"][1]["note"],row_basis["note"])
        self.assertEqual(normalized["events"][0]["views"][0]["note"],event_basis["note"])
        for changes in ({"start_seconds":5.1,"observed_seconds":.9},{"observed_seconds":.5}):
            altered=copy.deepcopy(raw)
            altered["observations"][0]["evidence"][1].update(changes)
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,"actual shared-event evidence"):
                ai.normalize(source,stage,altered)

    def test_count_zero_requires_whole_interval_and_d03_is_not_inferred(self):
        source=snapshot();stage=group("바14")
        with self.assertRaises((ValueError, HTTPException)):ai.normalize(source,stage,response(stage,"바14",0,[basis(start=0,end=1)],whole_interval_observed=True))
        self.assertEqual(ai.normalize(source,stage,response(stage,"바14",0,[basis()],whole_interval_observed=True))["observations"][0]["value"],0)
        pending=group("개21")
        with self.assertRaises(ValueError):ai.normalize(source,pending,response(pending,"개21",0,[]))

    def test_representative_audio_and_actual_whole_duration_required(self):
        source=snapshot(3);stage=group("바6")
        vocal={"listened_seconds":30.,"cumulative_vocal_seconds":10.,"whole_interval_judged":True,"note":"synthetic full audio"}
        raw=response(stage,"바6",1,[basis()],whole_interval_observed=True,vocalization=vocal)
        self.assertEqual(ai.normalize(source,stage,raw)["observations"][0]["value"],1)
        for clip in ("c2","c3"):
            changed=copy.deepcopy(raw);changed["observations"][0]["evidence"]=[basis(clip,start=int(clip[1:])-1,end=30+int(clip[1:])-1)]
            with self.assertRaises(ValueError):ai.normalize(source,stage,changed)
        changed=copy.deepcopy(raw);changed["observations"][0]["vocalization"]["listened_seconds"]=15.
        with self.assertRaises((ValueError, HTTPException)):ai.normalize(source,stage,changed)

    def test_memo_path_and_separate_59_linked_memo_no_g_review_input(self):
        source=snapshot();stage=group("보25")
        raw=response(stage,"보25","실제 접촉 대응 관찰",[basis(window=stage.window_ids[0],start=128,end=129)])
        raw["linked_memos"]=[{"text":"관련 실제 사건","item_codes":["보25"],"evidence":raw["observations"][0]["evidence"]}]
        value=ai.normalize(source,stage,raw)
        self.assertEqual(value["linked_memos"][0]["code"],"개59")
        raw["observations"][0]["review_memo"]="G should never be a provider response field"
        with self.assertRaises(ValueError):ai.normalize(source,stage,raw)
        sent=ai.context(source,stage,{"run_id":"run"})
        self.assertNotIn("survey",sent);self.assertNotIn("scores",sent);self.assertNotIn("human",encode(sent))

    def test_adoption_replays_original_response_and_rejects_mutated_observation(self):
        source, stage = snapshot(), group("개5")
        raw = response(stage,"개5",1,[basis()])
        payload = {**ai.normalize(source,stage,raw),"response":raw,"usage":{}}
        self.assertEqual(ai.stored_group(source,stage,payload),payload)
        changed = copy.deepcopy(payload)
        changed["observations"][0]["value"] = 2
        with self.assertRaises(ValueError):
            ai.stored_group(source,stage,changed)

    def test_pending_group_uses_program_and_cannot_be_numeric(self):
        source, stage = snapshot(), group("개21")
        payload = ai.program_group(source,stage)
        self.assertEqual(payload["observations"][0]["status"],"policy_pending")
        self.assertIsNone(payload["observations"][0]["value"])
        ai.stored_group(source,stage,payload)
        payload["observations"][0]["value"] = 0
        with self.assertRaises(ValueError):
            ai.stored_group(source,stage,payload)

    def test_missing_clips_keep_window_reasons_without_calling_provider(self):
        source, stage = snapshot(), group("개5")
        source = source.model_copy(update={"batch": source.batch.model_copy(update={"clips": ()})})
        payload = ai.program_group(source, stage)
        self.assertIsNone(payload["observations"][0]["value"])
        self.assertEqual(payload["observations"][0]["status"], "unobserved")
        self.assertIn("유효 클립 없음", payload["program_reason"])
        self.assertEqual(ai.stored_group(source, stage, payload), payload)
