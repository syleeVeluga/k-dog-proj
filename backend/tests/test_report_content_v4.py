import json
import unittest

from app import report_profile_v4 as reports
from app.domain.catalog_v4 import RESOURCES
from tests.report_fixture_v4 import fixture


class ReportContentV4Tests(unittest.TestCase):
    def profile(self, values=None, **kwargs):
        final, pointer, batch = fixture(values, **kwargs)
        return reports.build(final, pointer, batch=batch)

    def test_four_cards_missing_is_not_zero_and_no_invented_actions_or_scenes(self):
        value = self.profile()
        self.assertEqual([c.key for c in value.cards], ['education_attitude','attachment','social','walking'])
        self.assertEqual(value.cards[2].status, 'insufficient')
        self.assertEqual(value.scenes, ())
        self.assertTrue(value.scene_notice)
        self.assertEqual(value.actions, ())
        self.assertTrue(value.actions_notice)
        self.assertFalse(any(f.kind == 'observation' for f in value.facts))
        self.assertEqual(value.sentence_bank_status, 'pending_G02')

    def test_only_people_subdomain_is_partial_and_uses_actual_contact_item(self):
        value = self.profile({'개51':1})
        card = value.cards[2]
        self.assertEqual(card.status,'partial')
        self.assertTrue(any('observation:개51' in c.fact_ids for c in card.claims))
        self.assertTrue(any('물건' in c.text for c in card.claims))

    def test_walking_denominator_stays_six_and_percent_is_not_duration(self):
        values = dict(zip(('개38','개39','개40','개41','개42','개43'),(0,1,0,2,3,2)))|{'보13':1}
        value = self.profile(values,exceptions=['none']*6)
        self.assertIn('3개',value.cards[-1].claims[0].text)
        self.assertIn('50%',value.cards[-1].claims[0].text)
        self.assertIn('시간이나 복종 정도를 뜻하지 않습니다',value.cards[-1].claims[1].text)
        value = self.profile(values,exceptions=['guardian_approach','none','none','none','none','none'])
        self.assertIn('2개',value.cards[-1].claims[0].text)
        self.assertIn('33.3%',value.cards[-1].claims[0].text)

    def test_missing_walk_phase_never_uses_smaller_denominator(self):
        value = self.profile({'개38':0,'보13':1},exceptions=['none']*6)
        self.assertEqual(value.cards[-1].status,'insufficient')
        self.assertNotIn('%',value.cards[-1].claims[0].text)

    def test_guardian_and_stranger_cling_have_opposite_raw_signs(self):
        value = self.profile({'개19':-1,'개51':1})
        section = next(s for s in value.details if s.key=='contact_comparison')
        self.assertEqual(len(section.claims),3)
        self.assertTrue(all('몸이 닿을 만큼 앞으로 붙임' in c.text for c in section.claims[:2]))
        self.assertIn('15초',section.claims[-1].text)
        self.assertIn('3초',section.claims[-1].text)
        self.assertFalse(any(f.fact_id=='metric:contact_difference' for f in value.facts))

    def test_survey_raw_reverse_and_noise_no_video_task(self):
        value = self.profile({'개51':1},survey={'s12':4,'s26':1,'s27':2,'s28':5})
        facts = {f.fact_id:f for f in value.facts}
        self.assertEqual(len(value.comparisons),28)
        self.assertEqual(facts['survey-raw:s26'].value,1)
        self.assertEqual(facts['survey:s26'].value,5)
        self.assertEqual(facts['survey:s12'].unit,'0~4')
        noise = next(c for c in value.comparisons if c.key=='s12')
        self.assertFalse(noise.direct_video_task)
        self.assertEqual(noise.video_fact_ids,())
        self.assertIn('직접',noise.claims[-1].text)
        self.assertEqual(value.external_comparison_status,'pending_D06')

    def test_typeless_completed_opinion_does_not_infer_new_type(self):
        value = self.profile({'보23':-2},opinion={'domains':[{'domain':'education_attitude','text':'개의 반응을 기다린 장면을 살펴보았습니다.'}]})
        self.assertIsNone(value.cards[0].label)
        self.assertEqual(value.cards[0].status,'held')
        self.assertEqual(value.cards[0].claims[-1].validation,'human_verbatim')

    def test_priority_help_uses_completed_human_text_once(self):
        text='개의 반응을 기다리며 한 번씩 안내해 보세요.'
        value=self.profile({'보23':-2},opinion={'domains':[{'domain':'education_attitude','text':'확인한 반응입니다.'}],'priority_help':text})
        self.assertEqual([c.text for c in value.actions],[text])
        self.assertEqual(value.actions[0].validation,'human_verbatim')

    def test_completed_environment_and_tendency_opinions_remain_in_details(self):
        value=self.profile(opinion={'domains':[{'domain':'environment','text':'낯선 환경에서 살핀 반응입니다.'},
            {'domain':'tendency','text':'일상 응답과 현장 관찰을 함께 살펴봅니다.'}]})
        details={section.key:section for section in value.details}
        self.assertEqual(details['environment'].claims[0].text,'낯선 환경에서 살핀 반응입니다.')
        self.assertEqual(details['tendency'].claims[0].validation,'human_verbatim')

    def test_actual_timeline_preserves_eight_segments_and_six_walk_phases(self):
        value=self.profile()
        self.assertEqual(sum(t.kind=='segment' for t in value.timeline),8)
        self.assertEqual(sum(t.kind=='walk_phase' for t in value.timeline),6)
        self.assertTrue(all(t.source_end_seconds>t.source_start_seconds for t in value.timeline))
        self.assertTrue(all(t.camera_id=='CAM1' and t.video_sha256=='1'*64 for t in value.timeline))

    def test_candidate_bank_is_source_metadata_not_approved_sentences(self):
        data=json.loads((RESOURCES/'report/feedback-candidates-v4.json').read_bytes())
        self.assertEqual(len(data['items']),126)
        self.assertFalse(data['approved_sentence_bank'])
        self.assertTrue(all(row['application_status']=='candidate_only_G02' for row in data['items']))

    def test_same_pinned_source_yields_same_content(self):
        final,pointer,batch=fixture({'개51':1})
        one=reports.build(final,pointer,batch=batch)
        two=reports.build(final,pointer,batch=batch)
        self.assertEqual(one,two)
        self.assertEqual(reports.validate_profile(one,final,pointer,batch=batch),one)

