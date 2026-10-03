import unittest

from app import analysis, report_profile_v4 as reports, report_scenes_v4 as scenes
from app.domain.contracts_v4 import EvidenceV4
from tests.report_fixture_v4 import fixture


def views(code='개5', cameras=3):
    final,_,_=fixture({code:1},cameras=cameras)
    original=next(row for row in final.basic_document.input_document.sheet.observations if row.code==code).evidence[0]
    return [original.model_copy(update={'video_id':f'v{i}','video_sha256':str(i)*64,'camera_id':f'CAM{i}',
        'start_seconds':original.start_seconds+i-1,'end_seconds':original.end_seconds+i-1}).model_dump(mode='json') for i in range(1,cameras+1)]


class SceneSelectionV4Tests(unittest.TestCase):
    def test_zero_one_two_and_three_scene_limit(self):
        for values,expected in (({},0),({'개5':1},1),({'개5':1,'개19':-1},2),({'개5':1,'개19':-1,'개51':1,'보23':-2},3)):
            with self.subTest(values=values):
                final,pointer,batch=fixture(values)
                profile=reports.build(final,pointer,batch=batch)
                self.assertEqual(len(profile.scenes),expected)

    def test_three_synchronized_views_one_explicit_event_one_scene(self):
        evidence=views()
        final,pointer,batch=fixture({'개5':1},cameras=3,evidence={'개5':evidence})
        event=scenes.CommonEventV4.model_validate_json(analysis.encode({'event_id':'common-one','item_codes':['개5'],'evidence':evidence,'source_ref':'runs/source.json','source_hash':'e'*64}))
        profile=reports.build(final,pointer,batch=batch,common_events=(event,))
        self.assertEqual(len(profile.scenes),1)
        self.assertEqual(len(profile.scenes[0].evidence),3)
        self.assertEqual(profile.scenes[0].reference_start_seconds,0)
        self.assertEqual(profile.scenes[0].reference_end_seconds,30)
        self.assertEqual(profile.scene_review,())
        self.assertEqual(profile.source.event_sources[0].hash,'e'*64)

    def test_overlapping_cameras_without_common_event_are_pending_not_merged(self):
        final,pointer,batch=fixture({'개5':1},cameras=3,evidence={'개5':views()})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.scenes,())
        self.assertEqual(len(profile.scene_review),3)
        self.assertTrue(profile.scene_notice)

    def test_verified_common_event_preserves_other_views_not_copied_into_raw_row(self):
        evidence=views()
        final,pointer,batch=fixture({'개5':1},cameras=3,evidence={'개5':evidence[:1]})
        event=scenes.CommonEventV4.model_validate_json(analysis.encode({'event_id':'common-one','item_codes':['개5'],'evidence':evidence,'source_ref':'runs/source.json','source_hash':'e'*64}))
        profile=reports.build(final,pointer,batch=batch,common_events=(event,))
        self.assertEqual(len(profile.scenes),1)
        self.assertEqual(len(profile.scenes[0].evidence),3)

    def test_before_after_change_is_selected_before_unrelated_earlier_scene(self):
        final,pointer,batch=fixture({'개5':1,'개58':2,'개18':0})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.scenes[0].priority,'before_after')
        self.assertEqual(profile.scenes[1].priority,'before_after')

    def test_different_actual_items_do_not_merge_from_time_overlap(self):
        final,pointer,batch=fixture({'개5':1,'개6':1})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(len(profile.scenes),2)
        self.assertEqual(profile.scenes[0].reference_start_seconds,profile.scenes[1].reference_start_seconds)
        self.assertNotEqual(profile.scenes[0].common_event_id,profile.scenes[1].common_event_id)

    def test_completed_explicit_scene_selection_wins_over_earlier_source(self):
        final,pointer,batch=fixture({'개5':1,'개8':1,'개19':-1,'개51':1},scene_codes=('개51',))
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.scenes[0].priority,'completed_opinion')
        self.assertEqual(profile.scenes[0].claims[0].fact_ids,('observation:개51',))

    def test_item_code_without_explicit_scene_ref_is_not_nomination(self):
        final,pointer,batch=fixture({'개5':1,'개51':1},opinion={'domains':[{'domain':'people_response','text':'접촉 장면 확인','evidence_codes':['개51']}]})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.scenes[0].claims[0].fact_ids,('observation:개5',))
        self.assertFalse(any(scene.priority=='completed_opinion' for scene in profile.scenes))

    def test_common_event_foreign_hash_video_and_time_are_rejected(self):
        evidence=views(cameras=1)
        final,pointer,batch=fixture({'개5':1},evidence={'개5':evidence})
        for change in ({'video_sha256':'0'*64},{'video_id':'foreign'},{'start_seconds':1.0,'observed_seconds':29.0}):
            with self.subTest(change=change):
                altered=EvidenceV4.model_validate_json(analysis.encode(evidence[0])).model_copy(update=change)
                event=scenes.CommonEventV4(event_id='foreign',item_codes=('개5',),evidence=(altered,),source_ref='runs/source.json',source_hash='e'*64)
                with self.assertRaises(ValueError): reports.build(final,pointer,batch=batch,common_events=(event,))

    def test_common_event_provenance_changes_profile_identity(self):
        final,pointer,batch=fixture({'개5':1})
        evidence=next(row for row in final.basic_document.input_document.sheet.observations if row.code=='개5').evidence
        event=scenes.CommonEventV4(event_id='event',item_codes=('개5',),evidence=evidence,source_ref='runs/source.json',source_hash='e'*64)
        one=reports.build(final,pointer,batch=batch,common_events=(event,))
        two=reports.build(final,pointer,batch=batch,common_events=(event.model_copy(update={'source_hash':'f'*64}),))
        self.assertNotEqual(one.source_hash,two.source_hash)

    def test_earliest_actual_time_breaks_equal_priority_ties(self):
        final,pointer,batch=fixture({'개5':1,'개6':1,'개8':1})
        profile=reports.build(final,pointer,batch=batch)
        starts=[scene.reference_start_seconds for scene in profile.scenes]
        self.assertEqual(starts,sorted(starts))

    def test_zero_count_has_no_positive_scene(self):
        final,pointer,batch=fixture({'바14':0})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.scenes,())

    def test_ai_event_adapter_replays_original_response_and_keeps_global_times(self):
        from app import scoring_ai_v4 as ai
        from tests.test_scoring_ai_v4 import snapshot,group,response,basis
        source,stage=snapshot(3),group('바14')
        evidence=[basis(f'c{n}',start=n-1,end=30+n-1) for n in range(1,4)]
        event_views=[basis(f'c{n}',start=5+n-1,end=6+n-1) for n in range(1,4)]
        raw=response(stage,'바14',1,evidence+event_views,whole_interval_observed=True,event_ids=['event'])
        raw['events']=[{'event_id':'event','item_codes':['바14'],'views':event_views,'note':'one event, three actual views'}]
        payload={**ai.normalize(source,stage,raw),'response':raw,'usage':{}}
        found=scenes.events_from_ai(source,stage,payload,'runs/output.json','e'*64)
        self.assertEqual(len(found),1)
        self.assertEqual([v.start_seconds for v in found[0].evidence],[5,6,7])
        payload['observations'][0]['value']=3
        with self.assertRaises(ValueError):scenes.events_from_ai(source,stage,payload,'runs/output.json','e'*64)
