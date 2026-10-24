"""Parallel measurement scope and observed inference evidence; no provider calls."""
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from tests import test_benchmark_s1 as benchmark_fixture

bench = benchmark_fixture.bench

def clock(**changes):
    return bench.ClockTrace.model_validate_json(json.dumps({
        'version':'benchmark-clock-20261024-pa06','ai_run_id':'synthetic','report_run_id':'report',
        'clock_id':'observer','observer':'synthetic','started_at_utc':'2026-10-24T00:00:00+00:00',
        'ai_request_start':10,'shared_preparation_seconds':900,'pdf_published':100,
        'stages':[{'stage':'ai','start':10,'end':80},{'stage':'html_pdf_publish','start':80,'end':100}],**changes}))

class Pa06MeasurementTests(unittest.TestCase):
    def test_ai_request_scope_excludes_shared_preparation(self):
        result=bench.timing(clock())
        self.assertEqual(result['measurement_scope'],'ai_request_to_pdf')
        self.assertEqual(result['ai_request_to_pdf_seconds'],90)
        self.assertEqual(result['measured_wall_seconds'],90)
        self.assertIsNone(result['server_receive_to_pdf_seconds'])
        self.assertIsNone(result['pc_upload_to_pdf_seconds'])
        self.assertEqual(result['shared_preparation_seconds'],900)
        self.assertEqual(result['stage_union_seconds'],90)

    def test_clock_versions_cannot_relabel_or_repeat_preparation(self):
        for changes in ({'server_receive_start':0},{'ai_request_start':None},
                {'pdf_published':9},{'stages':[{'stage':'probe_preprocess','start':10,'end':20}]}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):clock(**changes)
        with self.assertRaises(ValidationError):
            clock(version='benchmark-clock-1',server_receive_start=0)

    def test_historical_manifest_rejects_ai_only_clock(self):
        data=bench.template()
        data.update(sample_kind='synthetic',app_commit='synthetic',planned_repetitions=1,planned_provider_call_budget=10,
            trials=[{'condition':bench.CONDITIONS[0],'pair_id':'pair','repeat':1,'case_id':'case','session_id':'session',
                'ai':{'run_id':'synthetic','input_hash':'1'*64,'config_hash':'2'*64},
                'pairing':{'ref':'benchmark/pair.json','hash':'3'*64},'cache':'cold','fps_condition':'source','pc_upload_mode':'one_pc'}])
        manifest=bench.BenchmarkManifest.model_validate_json(json.dumps(data))
        with patch.object(bench,'inspect_trial',return_value=({'timing':bench.timing(clock())},None)),self.assertRaisesRegex(ValueError,'historical S16'):
            bench.summarize(manifest)

    def test_inference_overlap_is_independent_of_request_overlap_and_other_clocks(self):
        def step(clock,left,right):
            return {'call_reserved':1,'usage_json':json.dumps({'request_interval':{'clock_id':clock,'start':0,'end':30},
                'provider_intervals':[{'clock_id':clock,'phase':'inference_seconds','start':left,'end':right}]})}
        value=bench.concurrency_evidence([step('a',5,8),step('a',10,15),step('b',0,30)])
        self.assertEqual(value['actual_max_requests'],2)
        self.assertEqual(value['inference']['actual_max_inferences'],1)
        self.assertEqual(value['inference']['clock_count'],2)
        self.assertTrue(value['inference']['complete'])

    def test_missing_and_invalid_inference_evidence_stays_visible(self):
        base={'call_reserved':1,'usage_json':json.dumps({'request_interval':{'clock_id':'a','start':0,'end':30}})}
        value=bench.concurrency_evidence([base])
        self.assertTrue(value['complete'])
        self.assertFalse(value['inference']['complete'])
        self.assertEqual(value['inference']['missing_reserved_intervals'],1)
        base['usage_json']=json.dumps({'provider_intervals':[{'clock_id':'a','phase':'inference_seconds','start':5,'end':4}]})
        with self.assertRaises(ValueError):bench.concurrency_evidence([base],inference=True)

