"""Synthetic clock, pairing and reference-denominator tests; no actual benchmark."""
import importlib.util
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app import analysis
from app.domain.preprocess_v4 import FileV4
from app.storage import encode
from tests import test_run_v4 as run_fixtures
from tests import test_exports_v4 as export_fixtures

SPEC = importlib.util.spec_from_file_location("benchmark_s1", Path(__file__).resolve().parents[2]/"scripts"/"benchmark_s1.py")
bench = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bench
SPEC.loader.exec_module(bench)


def parse(model, **values):
    return model.model_validate_json(encode(values))


def clock(**changes):
    return parse(bench.ClockTrace, **{"ai_run_id":"ai1","report_run_id":"report1","clock_id":"one-monotonic-clock",
        "observer":"synthetic","started_at_utc":"2026-10-04T00:00:00+00:00","server_receive_start":0.0,"pdf_published":100.0,
        "stages":[{"stage":"pc_upload","start":0.0,"end":20.0}, {"stage":"provider_upload","start":10.0,"end":30.0},
            {"stage":"ai","start":30.0,"end":70.0}, {"stage":"ai","start":40.0,"end":80.0},
            {"stage":"html_pdf_publish","start":80.0,"end":100.0}], **changes})


def trial(**changes):
    return parse(bench.Trial, **{"condition":bench.CONDITIONS[0],"pair_id":"pair1","repeat":1,"case_id":"case1","session_id":"session1",
        "ai":{"run_id":"ai1","input_hash":"1"*64,"config_hash":"2"*64},
        "pairing":{"ref":"benchmark/pairing.json","hash":"3"*64},"cache":"cold","fps_condition":"source",
        "pc_upload_mode":"one_pc", **changes})


def alignment(**changes):
    return {"video_sha256":"1"*64,"camera_id":"CAM1","common_start":0.0,"common_end":10.0,
        "source_offset_seconds":0.0,"duration_seconds":10.0,"fps":30.0,"width":1920,"height":1080,
        "video_codec":"h264","has_audio":True,**changes}


def manifest(trials=()):
    data = bench.template()
    data.update(sample_kind="synthetic",app_commit="synthetic",planned_repetitions=3,planned_provider_call_budget=10,
        trials=[row.model_dump(mode="json") for row in trials])
    data["conditions"][0]["size_range_bytes"]=[900_000_000,1_100_000_000]
    data["conditions"][1]["size_range_bytes"]=[900_000_000,1_100_000_000]
    return bench.BenchmarkManifest.model_validate_json(encode(data))


class BenchmarkMetricsTests(unittest.TestCase):
    def test_wall_clock_is_not_sum_of_overlapping_stages(self):
        result=bench.timing(clock())
        self.assertEqual(result["server_receive_to_pdf_seconds"],100)
        self.assertEqual(result["stage_sum_seconds"],140)
        self.assertEqual(result["stage_union_seconds"],100)
        self.assertEqual(result["ai_span_seconds"],70)
        self.assertEqual(result["ai_active_union_seconds"],70)
        self.assertIsNone(result["by_stage"]["queue"]["sum_seconds"])

    def test_ai_span_includes_wait_gaps_and_retries_but_union_does_not(self):
        result=bench.timing(clock(stages=[{"stage":"ai","start":20.0,"end":30.0},
            {"stage":"schema_repair","start":50.0,"end":60.0,"attempt":2}]))
        self.assertEqual(result["ai_span_seconds"],40)
        self.assertEqual(result["ai_active_union_seconds"],20)
        self.assertEqual(result["by_stage"]["schema_repair"]["interval_count"],1)

    def test_missing_pdf_and_ai_times_remain_null(self):
        result=bench.timing(clock(report_run_id=None,pdf_published=None,stages=[]))
        self.assertIsNone(result["server_receive_to_pdf_seconds"])
        self.assertIsNone(result["ai_span_seconds"])

    def test_invalid_clock_order_nonfinite_and_nonutc_are_rejected(self):
        for values in ({"pdf_published":-1.0},{"started_at_utc":"2026-10-04T00:00:00"},
                {"stages":[{"stage":"ai","start":5.0,"end":4.0}]},
                {"stages":[{"stage":"ai","start":5.0,"end":101.0}]},
                {"server_receive_start":float("nan")}):
            with self.subTest(values=values),self.assertRaises(ValidationError):clock(**values)

    def test_three_required_rows_never_fill_missing_measurements(self):
        result=bench.summarize(manifest())
        self.assertEqual([row["condition"] for row in result["conditions"]],list(bench.CONDITIONS))
        self.assertTrue(all(row["status"]=="unmeasured" and row["reason"] for row in result["conditions"]))
        self.assertFalse(result["real_measurement_complete"])
        self.assertIsNone(result["accuracy_threshold"])

    def test_duplicate_runs_conditions_and_undeclared_budget_rejected(self):
        for operation in (lambda value:value.update(trials=[trial().model_dump(mode="json")]*2),
                lambda value:value.update(conditions=value["conditions"][:2]),
                lambda value:value.update(trials=[trial().model_dump(mode="json")],planned_provider_call_budget=None)):
            data=manifest().model_dump(mode="json");operation(data)
            with self.assertRaises(ValidationError):bench.BenchmarkManifest.model_validate_json(encode(data))

    def test_size_tolerance_is_explicit_and_compressed_condition_not_rewritten(self):
        with self.assertRaises(ValidationError):parse(bench.Condition,key=bench.CONDITIONS[2],size_range_bytes=[100,200])
        self.assertIsNone(bench.BenchmarkManifest.model_validate_json(encode(bench.template())).conditions[0].size_range_bytes)

    def test_field_trials_require_real_version_and_environment_instead_of_placeholders(self):
        data=manifest([trial()]).model_dump(mode="json");data["sample_kind"]="field"
        with self.assertRaises(ValidationError):bench.BenchmarkManifest.model_validate_json(encode(data))
        data.update(app_commit="a"*40,environment={key:"recorded synthetic condition" for key in ("server","cpu","memory","network","os")})
        self.assertEqual(bench.BenchmarkManifest.model_validate_json(encode(data)).app_commit,"a"*40)

    def test_pc_upload_can_start_before_first_server_receipt_without_changing_total_scope(self):
        result=bench.timing(clock(server_receive_start=5.0))
        self.assertEqual(result["server_receive_to_pdf_seconds"],95)
        self.assertEqual(result["pc_upload_to_pdf_seconds"],100)

    def test_alignment_requires_real_common_times_and_conversion_provenance(self):
        for changes in ({"common_end":11.0},{"parent_hashes":["2"*64]},{"common_end":0.0}):
            with self.assertRaises(ValidationError):parse(bench.MediaAlignment,**alignment(**changes))

    def test_alignment_uses_source_equals_reference_plus_positive_and_negative_offset(self):
        positive=parse(bench.MediaAlignment,**alignment(source_offset_seconds=2.0,duration_seconds=12.0))
        self.assertEqual(positive.common_end+positive.source_offset_seconds,12)
        negative=parse(bench.MediaAlignment,**alignment(common_start=2.0,common_end=12.0,source_offset_seconds=-2.0))
        self.assertEqual(negative.common_start+negative.source_offset_seconds,0)
        for changes in ({"source_offset_seconds":2.0,"duration_seconds":11.9},
                {"common_start":1.9,"common_end":10.0,"source_offset_seconds":-2.0}):
            with self.assertRaises(ValidationError):parse(bench.MediaAlignment,**alignment(**changes))

    def fake_inspect(self, store, item, user, stamps):
        pair=parse(bench.Pairing,case_id=item.case_id,session_id=item.session_id,same_content_id="synthetic-content",
            confirmed_by="synthetic",confirmed_at="2026-10-04",basis="synthetic actual-frame correspondence",media=[alignment()])
        return {"reserved_calls":1,"camera_count":1,"file_sizes_bytes":[1_000_000_000],"timing":bench.timing(clock()),
            "cache":item.cache,"fps_condition":item.fps_condition,"pc_upload_mode":item.pc_upload_mode,"provider_execution":item.provider_execution,
            "configuration_hash":item.ai.config_hash},pair

    def test_synthetic_measurement_does_not_pass_field_acceptance_or_missing_three_cam(self):
        with patch.object(bench,"inspect_trial",side_effect=self.fake_inspect),patch.object(bench,"_access"):
            result=bench.summarize(manifest([trial()]))
        self.assertEqual(result["conditions"][0]["status"],"synthetic_only")
        self.assertEqual(result["conditions"][1]["status"],"unmeasured")
        self.assertFalse(result["real_measurement_complete"])
        self.assertNotIn("case1",encode(result))

    def test_wrong_case_pair_and_different_time_range_rejected(self):
        first=trial();second=trial(repeat=2,ai={"run_id":"ai2","input_hash":"1"*64,"config_hash":"2"*64})
        for wrong in ("case","time"):
            def inspect(store,item,user,stamps):
                result,pair=self.fake_inspect(store,item,user,stamps)
                if item.repeat==2:
                    if wrong=="case":pair=pair.model_copy(update={"same_content_id":"other-content"})
                    else:pair=pair.model_copy(update={"media":(pair.media[0].model_copy(update={"common_end":9.0}),)})
                return result,pair
            with patch.object(bench,"inspect_trial",side_effect=inspect),patch.object(bench,"_access"),self.assertRaises(ValueError):
                bench.summarize(manifest([first,second]))

    def test_retained_fps_claim_cannot_hide_fps_reduction(self):
        second=trial(repeat=2,fps_condition="compression_fps_kept",ai={"run_id":"ai2","input_hash":"1"*64,"config_hash":"2"*64})
        def inspect(store,item,user,stamps):
            result,pair=self.fake_inspect(store,item,user,stamps)
            if item.repeat==2:pair=pair.model_copy(update={"media":(pair.media[0].model_copy(update={"fps":1.0}),)})
            return result,pair
        with patch.object(bench,"inspect_trial",side_effect=inspect),patch.object(bench,"_access"),self.assertRaises(ValueError):
            bench.summarize(manifest([trial(),second]))

    def test_cache_and_pc_concurrency_groups_do_not_merge(self):
        second=trial(repeat=2,cache="explicit_reuse",pc_upload_mode="three_pc_concurrent",ai={"run_id":"ai2","input_hash":"1"*64,"config_hash":"2"*64})
        with patch.object(bench,"inspect_trial",side_effect=self.fake_inspect),patch.object(bench,"_access"):
            result=bench.summarize(manifest([trial(),second]))
        self.assertEqual(len(result["conditions"][0]["repeat_groups"]),2)
        self.assertTrue(all(row["sample_stdev_seconds"] is None for row in result["conditions"][0]["repeat_groups"]))

    def test_template_cli_is_exclusive_and_does_not_execute_providers(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"manifest.json";out=Path(temp)/"result.json"
            with patch.object(bench,"inspect_trial",side_effect=AssertionError("must not execute")):
                bench.main(["--template",str(path)])
                bench.main(["--manifest",str(path),"--output",str(out)])
            self.assertEqual(len(json.loads(out.read_bytes())["conditions"]),3)
            with self.assertRaises(FileExistsError):bench.main(["--template",str(path)])


class BenchmarkPinnedSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=run_fixtures.RunV4Tests(methodName="test_admission_idempotency_immutable_pin_and_private_operational_status")
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.store,self.user=self.fixture.store,self.fixture.user
        created=self.fixture.enqueue();row=self.fixture.row(created["run_id"])
        self.source=bench.run_v4.snapshot_for(row)
        video=self.source.session.videos[0]
        data=encode({"case_id":self.fixture.case_id,"session_id":self.fixture.session_id,"same_content_id":"synthetic-content",
            "confirmed_by":"synthetic","confirmed_at":"2026-10-04","basis":"synthetic correspondence",
            "media":[alignment(video_sha256=video.sha256)]}).encode()
        path=self.store.path("benchmark/pair.json");path.parent.mkdir();path.write_bytes(data)
        self.trial=trial(case_id=self.fixture.case_id,session_id=self.fixture.session_id,
            ai={"run_id":row["run_id"],"input_hash":row["input_hash"],"config_hash":analysis.digest(json.loads(row["config_snapshot_json"]))},
            pairing={"ref":"benchmark/pair.json","hash":__import__("hashlib").sha256(data).hexdigest()})

    def test_actual_source_hash_and_version_pins_are_read_without_provider_calls(self):
        readonly=bench.ReadOnlyStore(self.store.root)
        result,pair=bench.inspect_trial(readonly,self.trial,self.user,{})
        self.assertEqual(result["camera_count"],1)
        self.assertEqual(result["reserved_calls"],0)
        self.assertIsNone(result["timing"])
        self.assertEqual(result["quality"]["status"],"no_valid_human_reference")
        self.assertEqual(result["request_fps"],[1.0])
        self.assertEqual(result["insv"]["direct_read"],"unsupported_storage_only")
        self.assertNotIn("original_name",encode(result))
        with self.assertRaises(ValueError),readonly.connect(write=True):pass

    def test_changed_config_hash_or_pairing_hash_is_rejected(self):
        bad=self.trial.model_copy(update={"ai":self.trial.ai.model_copy(update={"config_hash":"0"*64})})
        with self.assertRaises(ValueError):bench.inspect_trial(self.store,bad,self.user,{})
        self.store.path(self.trial.pairing.ref).write_bytes(b"changed")
        with self.assertRaises(Exception):bench.inspect_trial(self.store,self.trial,self.user,{})

    def test_consent_withdrawal_and_wrong_role_are_rechecked(self):
        with self.store.connect(write=True) as db:db.execute("UPDATE users SET role='reviewer' WHERE username=?",(self.user.username,))
        with self.assertRaises(ValueError):bench.inspect_trial(self.store,self.trial,self.user,{})
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET role='operator' WHERE username=?",(self.user.username,))
            case=self.store.case(db,self.fixture.case_id);doc=self.store.manifest(case);doc.consents.analysis_feedback="declined"
            self.store.save(db,case,doc,self.user.username,"synthetic.decline")
        with self.assertRaises(ValueError):bench.inspect_trial(self.store,self.trial,self.user,{})

    def test_parallel_provider_claim_is_not_inferred_from_multi_pc_upload(self):
        bad=self.trial.model_copy(update={"provider_execution":"parallel","pc_upload_mode":"three_pc_concurrent"})
        with self.assertRaisesRegex(ValueError,"serially"):bench.inspect_trial(self.store,bad,self.user,{})

    def test_only_confirmed_recording_offsets_can_be_used(self):
        from app.domain.recording_v4 import VideoOffsetV4
        recording=self.source.session.recording_s1
        for offset in (-2.0,2.0):
            changed=recording.model_copy(update={"video_offsets":(VideoOffsetV4(video_id="CAM2-video",offset_seconds=offset,confirmed=True,note="synthetic"),)})
            bench.check_offset(changed,"CAM2-video",offset)
            with self.assertRaises(ValueError):bench.check_offset(changed,"CAM2-video",-offset)
        unknown=recording.model_copy(update={"video_offsets":(VideoOffsetV4(video_id="CAM2-video",offset_seconds=2.0,confirmed=False,note="synthetic"),)})
        with self.assertRaises(ValueError):bench.check_offset(unknown,"CAM2-video",2.0)
        with self.assertRaises(ValueError):bench.check_offset(recording,"unmapped-video",0.0)
        bench.check_offset(recording,recording.video_id,0.0)


class BenchmarkQualityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=export_fixtures.ExportV4Tests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.request,self.exposed=self.fixture.synthetic_ai_pair()
        created=self.fixture.create(self.request)
        self.snapshot=self.fixture.snapshot(created["export_id"])

    def test_only_adopted_export_pointer_can_be_quality_evidence(self):
        with self.fixture.store.connect() as db:record=bench.exports_v4._record(db,self.snapshot.export_id)
        pointer=FileV4(ref=record["ref"],hash=record["hash"])
        self.assertEqual(bench.verified_export(self.fixture.store,pointer,self.fixture.user,{}),self.snapshot)
        copy=bench.report_runs_v4._write_bytes(self.fixture.store,"benchmark/unadopted-export.json",self.snapshot.model_dump_json().encode())
        with self.assertRaisesRegex(ValueError,"adopted S14"):
            bench.verified_export(self.fixture.store,copy,self.fixture.user,{})

    def test_first_ai_and_independent_human_only_form_per_item_denominators(self):
        result=bench.quality(self.snapshot,"synthetic-ai-run")
        self.assertEqual(result["status"],"valid_pairs_available")
        used=[row for row in result["items"] if row["valid_pair_n"]]
        self.assertEqual([(row["code"],row["valid_pair_n"]) for row in used],[("보23",1)])
        self.assertEqual(result["reference_only_sources_in_denominator"],0)
        self.assertIsNone(result["accuracy_threshold"])
        self.assertNotIn("overall_accuracy",result)

    def test_wrong_ai_run_revised_ai_and_reference_only_values_cannot_supply_truth(self):
        self.assertEqual(bench.quality(self.snapshot,"other-run")["status"],"no_valid_human_reference")
        ai=self.snapshot.members[1]
        changed=ai.model_copy(update={"sheet":ai.sheet.model_copy(update={"revision":2})})
        snapshot=self.snapshot.model_copy(update={"members":(self.snapshot.members[0],changed),
            "reference_metadata":({"confirmation":"human_confirmed","code":"보23","value":99},)})
        result=bench.quality(snapshot,"synthetic-ai-run")
        self.assertEqual(result["status"],"no_valid_human_reference")
        self.assertEqual(result["reference_only_sources_in_denominator"],0)

    def test_human_after_ai_disclosure_is_excluded_and_reason_preserved(self):
        human=self.exposed["viewer"]
        selection=export_fixtures.model(bench.exports_v4.ExportSelectionV4,case_id=self.fixture.case_id,session_id=self.fixture.session_id,
            sheet={"sheet_id":human["sheet_id"],"revision":human["revision"],"ref":human["manifest_ref"],"hash":human["manifest_hash"]})
        shown=self.fixture.create(self.request.model_copy(update={"request_id":"review-quality","members":[selection,self.request.members[1]]}))
        result=bench.quality(self.fixture.snapshot(shown["export_id"]),"synthetic-ai-run")
        self.assertEqual(result["status"],"no_valid_human_reference")
        self.assertTrue(result["excluded_pair_reasons"]["not_independent"])


if __name__=="__main__":unittest.main()
