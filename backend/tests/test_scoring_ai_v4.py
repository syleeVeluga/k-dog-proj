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


def fractional_snapshot(sync, cut):
    data=snapshot(2).model_dump(mode="json")
    for capture in (data["session"]["recording_s1"],data["batch"]["recording"]):
        capture["video_offsets"][0]["offset_seconds"]=sync
    clip=data["batch"]["clips"][1]
    clip.update(offset_seconds=sync,source_start_seconds=cut,source_end_seconds=cut+300)
    for variant in ("original","ai"):
        clip[variant]["source_time_offset_seconds"]=cut
        clip[variant]["source_frame_times_seconds"]=[cut+time for time in clip[variant]["frame_times_seconds"]]
    for window in data["batch"]["windows"]:
        view=window["views"][1]
        view["offset_seconds"]=sync
        for key in ("source_start_seconds","source_end_seconds"):
            if view[key] is not None:
                view[key]+=sync-1
    return RunInputV4.model_validate_json(encode(data))


class AiNormalizationV4Tests(unittest.TestCase):
    def test_provider_schema_omits_only_wire_observation_array_bounds(self):
        import json
        stage=group("개37")
        original=encode(stage.response_schema)
        expected=json.loads(original)
        expected["properties"]["observations"].pop("minItems")
        expected["properties"]["observations"].pop("maxItems")
        self.assertEqual(ai.provider_schema(stage.response_schema),expected)
        self.assertEqual(encode(stage.response_schema),original)
        self.assertEqual(stage.response_schema["properties"]["observations"]["minItems"],len(stage.item_codes))
        source=snapshot()
        context=ai.context(source,stage,{"run_id":"run"},"operator")
        self.assertEqual(context["response_constraints"]["observation_count"],len(stage.item_codes))
        self.assertEqual(context["walk_phases"],[phase.model_dump(mode="json") for phase in source.session.recording_s1.walk_phases])

    def test_provider_array_simplification_keeps_exact_item_count_validation(self):
        stage=group("개37")
        raw=response(stage)
        for rows in (raw["observations"][:-1],raw["observations"]+[raw["observations"][0]]):
            with self.subTest(count=len(rows)), self.assertRaisesRegex(ValueError,"each exact direct item once"):
                ai.normalize(snapshot(),stage,{**raw,"observations":rows})

    def test_local_fractional_span_normalizes_roundoff_before_source_mapping(self):
        stage=group("개8")
        item=basis("c2","baseline_whole",29.916,49.916)
        item["observed_seconds"]=20.0
        result=ai.normalize(fractional_snapshot(0.2,0.284),stage,
            response(stage,"개8",0,[item],whole_interval_observed=True))
        observed=next(value for value in result["observations"] if value["code"]=="개8")
        self.assertEqual(observed["value"],0)
        self.assertAlmostEqual(observed["evidence"][0]["observed_seconds"],20.0,places=9)

    def test_local_span_still_rejects_real_excess_and_reversed_time(self):
        from app.domain.scoring_ai_v4 import LocalEvidenceV4
        for start,end,amount in ((29.916,49.916,20.001),(1.0,1.0-1e-10,0)):
            with self.subTest(start=start,end=end,amount=amount), self.assertRaises(ValueError):
                LocalEvidenceV4.model_validate({**basis(start=start,end=end),"observed_seconds":amount})

    def test_fractional_cut_and_camera_offset_preserve_whole_window_evidence(self):
        stage=group("개8")
        for sync,cut in ((0.2,0.3),(0.1,0.2)):
            with self.subTest(sync=sync,cut=cut):
                item=basis("c2","baseline_whole",29.9,49.9)
                item["observed_seconds"]=20.0
                result=ai.normalize(fractional_snapshot(sync,cut),stage,
                    response(stage,"개8",0,[item],whole_interval_observed=True))
                observed=next(value for value in result["observations"] if value["code"]=="개8")
                self.assertEqual(observed["value"],0)
                evidence=observed["evidence"][0]
                self.assertLessEqual(evidence["observed_seconds"],evidence["end_seconds"]-evidence["start_seconds"])
                self.assertAlmostEqual(evidence["observed_seconds"],20.0,places=9)

    def test_fractional_mapping_still_rejects_a_real_millisecond_outside_window(self):
        stage=group("개8")
        for key,delta in (("start_seconds",-0.001),("end_seconds",0.001)):
            with self.subTest(key=key):
                item=basis("c2","baseline_whole",29.9,49.9)
                item[key]+=delta
                item["observed_seconds"]=20.0
                with self.assertRaises(HTTPException):
                    ai.normalize(fractional_snapshot(0.1,0.2),stage,
                        response(stage,"개8",0,[item],whole_interval_observed=True))

    def test_camera_clock_rounding_preserves_actual_walking_phase_bounds(self):
        source=fractional_snapshot(0.1,0.3)
        phase=source.session.recording_s1.walk_phases[0]
        stage=group("개38")
        item=basis("c2","walk_whole",round(phase.start_sec-0.2,1),round(phase.end_sec-0.2,1))
        result=ai.normalize(source,stage,response(stage,"개38",1,[item]))
        self.assertEqual(next(value for value in result["observations"] if value["code"]=="개38")["value"],1)

    def test_fractional_mapping_keeps_evidence_at_the_physical_cut_end(self):
        data=snapshot().model_dump(mode="json")
        clip=data["batch"]["clips"][0]
        clip.update(source_start_seconds=0.1,source_end_seconds=0.3)
        for variant in ("original","ai"):
            clip[variant].update(source_time_offset_seconds=0.1,duration_seconds=0.2,
                frame_times_seconds=[0.0],source_frame_times_seconds=[0.1],audio_ranges=[])
        stage=group("개5")
        raw=response(stage)
        raw["observations"][0]["evidence"]=[basis("c1","entry_whole",0,0.2)]
        result=ai.normalize(RunInputV4.model_validate_json(encode(data)),stage,raw)
        self.assertEqual(result["observations"][0]["evidence"][0]["end_seconds"],0.3)

    def test_whole_coverage_joins_float_roundoff_but_not_a_real_gap(self):
        self.assertTrue(ai.sheets._covered([(0,0.3),(0.1+0.2,1)],0,1))
        self.assertTrue(ai.sheets._covered([(0,0.3)],0,0.1+0.2))
        self.assertFalse(ai.sheets._covered([(0,0.3),(0.301,1)],0,1))
        self.assertFalse(ai.sheets._covered([],0,1))

    def test_provider_gets_local_window_bounds_and_explicit_silent_audio_contract(self):
        data=fractional_snapshot(0.2,0.3).model_dump(mode="json")
        for clip in data["batch"]["clips"]:
            for variant in ("original","ai"):
                clip[variant]["audio_ranges"]=[]
        for window in data["batch"]["windows"]:
            window.update(audio_available_seconds=0,representative_audio_video_id=None,audio_selection_reason="synthetic silent media")
        info=ai.context(RunInputV4.model_validate_json(encode(data)),group("바6"),{"run_id":"synthetic"},"operator")
        rules=info["response_constraints"]
        self.assertEqual(rules["audio_unavailable_windows"],["entry_whole"])
        self.assertEqual(rules["vocal_item_codes"],["바6"])
        self.assertEqual(rules["unavailable_audio_observation"],{"value":None,"status":"unobserved","vocalization":None})
        self.assertEqual({item["window_id"] for item in rules["evidence_intervals"]},{"entry_whole"})
        second=next(item for item in rules["evidence_intervals"] if item["clip_id"]=="c2")
        self.assertEqual(second["start_seconds"],0)
        self.assertAlmostEqual(second["end_seconds"],29.9,places=9)

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
        sent=ai.context(source,stage,{"run_id":"run"}, source.requested_by)
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


class AiPublicationV4Tests(unittest.TestCase):
    def setUp(self):
        from app import analysis, run_v4, settings_v4
        from app.storage import now, uid
        from app.worker import Worker
        from tests.test_run_v4 import RunV4Tests
        self.fixture = RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        pipeline = settings_v4.defaults()
        pipeline.raw_observation_scope_confirmed = True
        config = ai.configuration(None, pipeline)
        self.fixture.enqueue(config=config)
        self.row = analysis.claim(self.store)
        self.source = run_v4.snapshot_for(self.row)
        self.worker = Worker(self.store)
        # Failed synthetic groups provide every required observation without a provider.
        with self.store.connect(write=True) as db:
            for stage in config.stages:
                if stage.stage in ("score_v4", "attachment_v4"):
                    db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,usage_json,created_at,updated_at) "
                               "VALUES(?,?,?,?,1,'failed',?,'{}',?,?)",
                               (uid(), self.row["run_id"], stage.stage, stage.key, self.row["claim_token"], now(), now()))
        self.calculation = ai.calc_payload(self.worker, self.row, self.source)

    def publish(self):
        return ai.publish(self.worker, self.row, self.source, self.calculation)

    def counts(self):
        from app.domain.sheets_v4 import AI_ACCOUNT
        with self.store.connect() as db:
            return tuple(db.execute(sql, parameters).fetchone()[0] for sql, parameters in (
                ("SELECT COUNT(*) FROM users WHERE username=?", (AI_ACCOUNT,)),
                ("SELECT COUNT(*) FROM score_sheets", ()),
                ("SELECT COUNT(*) FROM basic_results", ()),
                ("SELECT COUNT(*) FROM changes WHERE action='ai.publish'", ())))

    def test_identical_publication_is_idempotent_and_conflicting_document_is_rejected(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        first = self.publish()
        ref = first["basic_result"]["ref"]
        before = self.store.path(ref).read_bytes()
        self.assertEqual(self.publish()["basic_result"], first["basic_result"])
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        changed = ai.basic_data(self.worker, self.row, self.calculation)
        changed["change_reason"] = "synthetic conflicting document"
        with patch.object(ai, "basic_data", return_value=changed):
            with self.assertRaises(HTTPException) as error:
                self.publish()
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        self.assertEqual(self.store.path(ref).read_bytes(), before)

    def test_ai_account_collision_does_not_create_sheet_result_or_audit(self):
        from app.domain.sheets_v4 import AI_ACCOUNT
        from fastapi import HTTPException
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO users(username,password_hash,role,active) VALUES (?,?,'operator',1)", (AI_ACCOUNT, "synthetic"))
        with self.assertRaises(HTTPException) as error:
            self.publish()
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.counts(), (1, 0, 0, 0))

    def test_actor_revoked_after_file_checks_cannot_publish(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        guarded = ai.guarded
        def revoke(worker, row, source):
            guarded(worker, row, source)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='operator'")
        with patch.object(ai, "guarded", side_effect=revoke):
            with self.assertRaises(HTTPException):
                self.publish()
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_audit_failure_rolls_back_account_sheet_result_and_retry_reuses_immutable_file(self):
        from unittest.mock import patch
        audit = self.store.audit
        written = []
        write_result = ai.judgements.write_result
        def capture(store, data):
            result = write_result(store, data)
            written.append((result[0], store.path(result[0]).read_bytes()))
            return result
        def fail(db, actor, target, action, detail):
            if action == "ai.publish":
                raise RuntimeError("synthetic audit failure")
            return audit(db, actor, target, action, detail)
        with patch.object(ai.judgements, "write_result", side_effect=capture), patch.object(self.store, "audit", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "synthetic audit failure"):
                self.publish()
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        self.assertEqual(len(written), 1)
        self.assertEqual(self.store.path(written[0][0]).read_bytes(), written[0][1])
        self.publish()
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        self.assertEqual(self.store.path(written[0][0]).read_bytes(), written[0][1])
