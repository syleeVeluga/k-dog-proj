import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import report_profile_v4 as reports, opinions_v4 as opinions
from app.domain.report_profile_v4 import ReportProfileV4
from tests.report_fixture_v4 import fixture
from tests.test_opinions_v4 import setup_case,save_opinion,model
from tests.test_final_results_v4 import assemble


class ReportValidationV4Tests(unittest.TestCase):
    def test_regeneration_rejects_wrong_type_number_fake_noise_and_scene(self):
        final,pointer,batch=fixture({'개19':-1,'개51':1},survey={'s12':3})
        profile=reports.build(final,pointer,batch=batch)
        changes=[{'cards':(profile.cards[0].model_copy(update={'label':'새로운 유형'}),*profile.cards[1:])},
            {'facts':tuple(f.model_copy(update={'value':90}) if f.fact_id=='observation:개19' else f for f in profile.facts)},
            {'comparisons':tuple(c.model_copy(update={'direct_video_task':True,'video_fact_ids':('observation:개51',)}) if c.key=='s12' else c for c in profile.comparisons)},
            {'scenes':(profile.scenes[0].model_copy(update={'reference_start_seconds':0.0}),*profile.scenes[1:])}]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):reports.validate_profile(profile.model_copy(update=change),final,pointer,batch=batch)

    def test_placeholder_human_text_is_held_and_not_in_output_claims(self):
        final,pointer,batch=fixture({'보23':2},opinion={'domains':[{'domain':'education_attitude','text':'작성 필요: 예시 메모'}]})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.status,'review_required')
        self.assertTrue(any(issue.code=='placeholder_text' for issue in profile.validation_issues))
        self.assertFalse(any('작성 필요' in c.text for card in profile.cards for c in card.claims))

    def test_other_type_in_completed_opinion_is_held_not_rerated(self):
        final,pointer,batch=fixture({'보23':2},opinion={'domains':[{'domain':'education_attitude','text':'허용형으로 보입니다.','label':'통제형',
            'evidence_codes':['보23'],'reason':'실제 지시','counter_note':'반대 근거 검토'}]})
        profile=reports.build(final,pointer,batch=batch)
        self.assertEqual(profile.cards[0].label,'통제형')
        self.assertEqual(profile.status,'review_required')
        self.assertTrue(any(issue.code=='contradictory_type' for issue in profile.validation_issues))

    def test_typeless_named_type_text_is_held_without_inferring_selection(self):
        final,pointer,batch=fixture({'보23':2},opinion={'domains':[{'domain':'education_attitude','text':'통제형입니다.'}]})
        profile=reports.build(final,pointer,batch=batch)
        self.assertIsNone(profile.cards[0].label)
        self.assertEqual(profile.status,'review_required')
        self.assertTrue(any(issue.code=='unresolved_type_text' for issue in profile.validation_issues))
        self.assertFalse(any('통제형' in claim.text for claim in profile.cards[0].claims))

    def test_human_walking_count_and_percent_must_match_fixed_calculation(self):
        values=dict(zip(('개38','개39','개40','개41','개42','개43'),(0,1,0,2,3,2)))|{'보13':1}
        for text,blocked in (('6국면 중 5개(83.3%)에서 가까웠습니다.',True),('여섯 국면 중 3개(90%)입니다.',True),
                             ('여섯 국면 중 3개(50%)에서 가까웠습니다.',False)):
            with self.subTest(text=text):
                final,pointer,batch=fixture(values,exceptions=['none']*6,opinion={'domains':[{'domain':'tendency','text':text}],'priority_help':text})
                profile=reports.build(final,pointer,batch=batch)
                self.assertEqual(any(issue.code=='walking_claim_mismatch' for issue in profile.validation_issues),blocked)

    def test_pinned_batch_is_required_and_foreign_source_rejected(self):
        final,pointer,batch=fixture()
        with self.assertRaises(ValueError):reports.build(final,pointer)
        with self.assertRaises(ValueError):reports.build(final,pointer,batch=batch.model_copy(update={'case_id':'other'}))

    def test_claim_fact_references_must_exist(self):
        final,pointer,batch=fixture()
        profile=reports.build(final,pointer,batch=batch)
        changed=profile.cards[0].model_copy(update={'claims':(profile.cards[0].claims[0].model_copy(update={'fact_ids':('invented',)}),)})
        with self.assertRaises(ValueError):ReportProfileV4.model_validate(profile.model_copy(update={'cards':(changed,*profile.cards[1:])}))


class ReportProfileServiceV4Tests(unittest.TestCase):
    setUp=setup_case

    def final(self):
        return assemble(self,save_opinion(self))

    def test_from_final_uses_exact_original_and_does_not_refresh_opinion(self):
        final=self.final()
        profile=reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)
        reopened=opinions.action(self.store,self.case_id,self.session_id,model(opinions.OpinionActionV4,expected_revision=1,reason='synthetic reopen'),self.user,'reopen')
        save_opinion(self,expected_revision=reopened['reference']['revision'],domains=[{'domain':'education_attitude','text':'수정된 새 의견'}])
        same=reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)
        self.assertEqual(profile,same)
        self.assertEqual(profile.source.final.hash,final['reference']['hash'])

    def test_source_tamper_during_build_is_not_returned(self):
        final=self.final()
        original=reports.build
        def tamper(*args,**kwargs):
            result=original(*args,**kwargs)
            self.store.path(final['reference']['ref']).write_text('{}',encoding='utf-8')
            return result
        with patch.object(reports,'build',side_effect=tamper):
            with self.assertRaises(HTTPException) as failure:
                reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)
        self.assertEqual(failure.exception.status_code,409)

    def test_delete_requested_case_cannot_produce_report_profile(self):
        final=self.final()
        with self.store.connect(write=True) as db:
            db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?',(self.case_id,))
        with self.assertRaises(HTTPException):reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)


class ReportDisclosureV4Tests(unittest.TestCase):
    def test_own_score_does_not_bypass_other_authors_final_disclosure(self):
        from app import final_results_v4 as finals,disclosures_v4 as disclosure
        from tests.test_disclosures_v4 import DisclosureV4Tests
        DisclosureV4Tests.setUp(self)
        final=finals.assemble(self.store,self.case_id,self.session_id,model(finals.AssembleFinalV4,
            basic=self.basic_ref,opinion=self.opinion['reference'],viewer_sheet_id=self.admin_sheet['sheet_id'],reason='synthetic final'),self.admin)
        with self.assertRaises(HTTPException):reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)
        request=model(disclosure.InterpretationRevealV4,target=disclosure.target('final',final['reference']).model_dump(mode='json'),
            viewer_sheet_id=self.sheet['sheet_id'],expected_viewer_revision=self.sheet['revision'],reason='synthetic explicit reveal')
        disclosure.reveal(self.store,self.case_id,self.session_id,request,self.user)
        profile=reports.from_final(self.store,self.case_id,self.session_id,final['reference']['final_id'],self.user)
        self.assertEqual(profile.source.final.hash,final['reference']['hash'])
