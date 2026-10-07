"""All participants and research confirmations in these tests are synthetic."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app import comparisons_v4 as compare,forms_v4 as forms
from app.domain.comparisons_v4 import CohortSelectionV4,ResearchReviewV4
from app.domain.sheets_v4 import InputPointerV4
from app.storage import Store,encode
from tests.test_forms_import_v4 import csv_bytes


class ComparisonFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='kdog-comparison-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name))
        self.user=SimpleNamespace(username='operator')
        self.admin=SimpleNamespace(username='admin')
        self.reviewer=SimpleNamespace(username='reviewer')
        with self.store.connect(write=True) as db:
            for name,role in (('operator','operator'),('admin','admin'),('reviewer','reviewer')):
                db.execute('INSERT INTO users(username,password_hash,role) VALUES (?,?,?)',(name,'unused',role))
        keys=['participant_id','dog_name','consent_analysis_feedback']+[f's{i:02}' for i in range(1,29)]
        answers=[{f's{i:02}':2 for i in range(1,29)},{f's{i:02}':2 for i in range(1,29)},{}]
        answers[0].update(s10=0,s11=0,s12=1,s13=2,s14=3)
        answers[1].update(s01=None,s10=4,s11=2,s13=None,s25=None)
        for value in answers:value.update(s26=None,s27=None,s28=None)
        data=csv_bytes([keys]+[[f'SYNTHETIC-{i}',f'SyntheticDog{i}','confirmed',*[value.get(key) for key in keys[3:]]] for i,value in enumerate(answers)])
        preview=forms.preview(self.store,data,forms.FormsPreviewRequestV4(request_id='preview',event_id='TEST',filename='synthetic.csv',format='csv',
            mapping=forms.FormsMappingV4(version='synthetic',source_profile='synthetic only',survey_version='survey-20260929-v3',columns={key:key for key in keys})),self.user.username)
        self.assertEqual(preview.errors,[])
        result=forms.commit(self.store,forms.FormsCommitRequestV4(request_id='commit',preview_id=preview.preview_id,preview_hash=preview.preview_hash),self.user.username)
        self.ids=[row.case_id for row in result.rows]

    def selection(self,case_id):
        with self.store.connect() as db:
            row=self.store.case(db,case_id)
            return CohortSelectionV4(case_id=case_id,session_id=row['selected_session_id'],expected_revision=row['input_revision'],
                input=InputPointerV4(manifest_ref=row['manifest_ref'],manifest_hash=row['manifest_hash']))

    def create(self,request_id='cohort',ids=None):
        return compare.create(self.store,compare.CohortCreateV4(request_id=request_id,title='Synthetic same-edition group',reason='explicit synthetic selection',
            members=[self.selection(key) for key in (ids or self.ids)]),self.user)

    def edit(self,index,operation):
        with self.store.connect(write=True) as db:
            row=self.store.case(db,self.ids[index]);manifest=self.store.manifest(row)
            operation(manifest)
            self.store.save(db,row,manifest,self.user.username,'synthetic.edit')


class CohortComparisonV4Tests(ComparisonFixture):
    def test_rp01_previous_policy_snapshot_read_is_immutable_and_new_policy_is_explicit(self):
        from app.survey_v4 import survey_scores_v4
        previous = 'survey-policy-20261002-s1.1'
        original_assets = compare.assets
        def old_scores(session, catalog, **kwargs):
            return survey_scores_v4(session, catalog, policy_version=previous)
        with patch.object(compare, 'RUNTIME_SURVEY_POLICY_VERSION', previous), \
             patch.object(compare, 'survey_scores_v4', side_effect=old_scores), \
             patch.object(compare, 'assets', side_effect=lambda *args: original_assets(previous)):
            old = self.create('old-policy')
        before = self.store.path(old.reference.ref).read_bytes()
        shown = compare.view(self.store, old.reference.snapshot_id, self.user)
        public = compare.for_report(self.store, old.reference, self.user)
        self.assertEqual(shown.document.survey_policy, previous)
        self.assertEqual(public.survey_policy, previous)
        self.assertEqual(self.store.path(old.reference.ref).read_bytes(), before)
        new = self.create('new-policy')
        self.assertEqual(new.document.survey_policy, 'survey-policy-20261007-rp01')
        self.assertEqual(compare.for_report(self.store, new.reference, self.user).survey_policy, new.document.survey_policy)
        with self.assertRaisesRegex(ValueError, 'mixed'):
            compare.aggregate((old.document.members[0], new.document.members[1]))
        with self.assertRaises(ValueError):
            type(old.document).model_validate_json(
                encode({**old.document.model_dump(mode='json'), 'members': [old.document.members[0].model_dump(mode='json'), new.document.members[1].model_dump(mode='json')]}))

    def test_per_domain_valid_n_zero_and_undecided_partial_means(self):
        value=self.create()
        rows={row.domain:row for row in value.document.domains}
        self.assertEqual((rows['낯선 사람 두려움'].mean,rows['낯선 사람 두려움'].n),(1.5,2))
        self.assertEqual((rows['비사회적 두려움'].mean,rows['비사회적 두려움'].n),(2,1))
        self.assertEqual((rows['가르치는 방식'].mean,rows['가르치는 방식'].n),(2,1))
        self.assertEqual(rows['가르치는 방식'].excluded[self.ids[1]],'insufficient_responses')
        self.assertEqual((rows['감정의 일관성'].mean,rows['감정의 일관성'].n),(None,0))
        self.assertEqual(rows['일상 따라옴 (Q25 단일 응답)'].n,1)
        public=compare.for_report(self.store,value.reference,self.user)
        self.assertNotIn('SyntheticDog',public.model_dump_json())
        self.assertNotIn(self.ids[0],public.model_dump_json())

    def test_duplicate_case_sessions_never_increase_sample_count(self):
        item=self.selection(self.ids[0])
        request=compare.CohortCreateV4(request_id='double',title='bad',reason='synthetic',members=[item,item])
        with self.assertRaises(HTTPException) as failure:compare.create(self.store,request,self.user)
        self.assertEqual(failure.exception.status_code,422)

    def test_request_idempotency_checks_body_and_live_consent(self):
        one=self.create();two=self.create()
        self.assertEqual(one.reference,two.reference)
        with self.assertRaises(HTTPException):self.create(ids=self.ids[:1])
        self.edit(0,lambda manifest:setattr(manifest.consents,'analysis_feedback','declined'))
        with self.assertRaises(HTTPException):compare.for_report(self.store,one.reference,self.user)

    def test_input_edit_creates_new_snapshot_old_mean_is_immutable(self):
        old=self.create()
        data=self.store.path(old.reference.ref).read_bytes()
        def updated(manifest):manifest.sessions[0].survey.update(s10=4,s11=4)
        self.edit(0,updated)
        previous=compare.view(self.store,old.reference.snapshot_id,self.user)
        self.assertEqual(previous.outdated_member_case_ids,[self.ids[0]])
        newer=self.create('new')
        self.assertEqual(next(r.mean for r in previous.document.domains if r.domain=='낯선 사람 두려움'),1.5)
        self.assertEqual(next(r.mean for r in newer.document.domains if r.domain=='낯선 사람 두려움'),3.5)
        self.assertEqual(self.store.path(old.reference.ref).read_bytes(),data)

    def test_unknown_consent_and_review_role_are_rejected(self):
        self.edit(0,lambda manifest:setattr(manifest.consents,'analysis_feedback','unknown'))
        with self.assertRaises(HTTPException):self.create()
        with self.assertRaises(HTTPException):compare.list_snapshots(self.store,self.reviewer)

    def test_deleted_member_blocks_full_snapshot_and_removes_shared_reference(self):
        value=self.create()
        with self.store.connect(write=True) as db:db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?',(self.ids[1],))
        with self.assertRaises(HTTPException):compare.for_report(self.store,value.reference,self.user)
        with self.store.connect(write=True) as db:
            self.assertEqual(compare.purge_deleted(db),{value.reference.snapshot_id})
        self.assertEqual(compare.list_snapshots(self.store,self.user),[])
        with self.store.connect() as db:
            tomb=compare._record(db,'comparison.deleted',value.reference.snapshot_id)
            self.assertEqual(tomb,{'snapshot_id':value.reference.snapshot_id})

    def test_changed_selection_revision_and_tampered_source_rejected(self):
        old=self.selection(self.ids[0])
        self.edit(0,lambda manifest:manifest.sessions[0].survey.update(s10=4))
        with self.assertRaises(HTTPException):compare.create(self.store,compare.CohortCreateV4(request_id='stale',title='stale',reason='test',members=[old]),self.user)
        value=self.create()
        self.store.path(value.document.members[0].input.manifest_ref).write_bytes(b'{}')
        with self.assertRaises(HTTPException):compare.for_report(self.store,value.reference,self.user)

    def test_blob_tamper_or_late_delete_never_adopts(self):
        original=compare._write
        def tamper(store,kind,doc):
            pointer=original(store,kind,doc);store.path(pointer.ref).write_bytes(b'{}');return pointer
        with patch.object(compare,'_write',side_effect=tamper),self.assertRaises(HTTPException):self.create()
        def deleted(store,kind,doc):
            pointer=original(store,kind,doc)
            with store.connect(write=True) as db:db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?',(self.ids[0],))
            return pointer
        with patch.object(compare,'_write',side_effect=deleted),self.assertRaises(HTTPException):self.create()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM changes WHERE action=?',(compare.COHORT_ACTION,)).fetchone()[0],0)

    def test_current_account_role_is_rechecked(self):
        value=self.create()
        with self.store.connect(write=True) as db:db.execute('UPDATE users SET active=0 WHERE username=?',(self.user.username,))
        with self.assertRaises(HTTPException):compare.for_report(self.store,value.reference,self.user)

    def test_selected_member_pointer_cannot_name_another_participant_source(self):
        one,two=self.selection(self.ids[0]),self.selection(self.ids[1])
        invalid=one.model_copy(update={'input':two.input})
        with self.assertRaises(HTTPException):compare.create(self.store,compare.CohortCreateV4(request_id='foreign',title='foreign',reason='synthetic',members=[invalid]),self.user)

    def test_whole_missing_domain_and_true_zero_are_distinct(self):
        zero=self.create(ids=self.ids[:1])
        missing=self.create('empty',ids=self.ids[2:])
        one=next(row for row in zero.document.domains if row.domain=='낯선 사람 두려움')
        two=next(row for row in missing.document.domains if row.domain=='낯선 사람 두려움')
        self.assertEqual((one.mean,one.n),(0,1))
        self.assertEqual((two.mean,two.n),(None,0))

    def test_historical_comfort_version_is_never_converted_to_current_fear(self):
        def historical(manifest):
            manifest.sessions[0].survey_version='catalog-20260913-v2'
            manifest.sessions[0].survey.update(s10=1,s11=1)
        self.edit(0,historical)
        with self.assertRaises(HTTPException) as failure:self.create()
        self.assertEqual(failure.exception.status_code,422)


class ExternalComparisonGateV4Tests(ComparisonFixture):
    def confirmation(self,*,status='confirmed',requirements=None,revision=0):
        source_id='us2026-stranger-fear'
        source,digest=compare._source(source_id)
        data=b'SYNTHETIC APPROVAL FIXTURE ONLY - NOT A RESEARCH CONFIRMATION'
        path=self.store.path('comparison-evidence/synthetic.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        check={'status':status,'note':'SYNTHETIC TEST ONLY','evidence_location':'synthetic fixture section'}
        scope=compare.target_scope(source_id).model_copy(update={'population_requirements':requirements or {}})
        review=ResearchReviewV4.model_validate_json(encode({'source_id':source_id,'source_asset_hash':digest,'confirmed_by':'SYNTHETIC TEST ONLY',
            'confirmed_at':'2026-10-04','evidence':[{'ref':'comparison-evidence/synthetic.txt','hash':hashlib.sha256(data).hexdigest()}],
            'scope':scope.model_dump(mode='json'),'reason':'synthetic approval mechanics only',**{key:check for key in compare.CHECKS}}))
        return compare.confirm_research(self.store,compare.ConfirmResearchV4(expected_revision=revision,document=review),self.admin)

    def activate(self,pointer,enabled=True,revision=0):
        return compare.activate_external(self.store,compare.ActivateExternalV4(source_id='us2026-stranger-fear',expected_revision=revision,
            confirmation=pointer,enabled=enabled,reason='SYNTHETIC TECHNICAL ACTIVATION ONLY'),self.admin)

    def gate(self,**kwargs):
        return compare.external_for_report(self.store,'us2026-stranger-fear',compare.target_scope('us2026-stranger-fear'),self.user,**kwargs)

    def test_pending_sources_never_expose_reference_numbers(self):
        payload=encode(compare.public_sources())+self.gate().model_dump_json(exclude_none=True)
        for number in ('0.66','0.91','42926','1.03','0.78','42764','43517'):
            self.assertNotIn(number,payload)
        self.assertNotIn('values',self.gate().model_dump(exclude_none=True))
        with self.assertRaises(HTTPException):compare.research_inventory(self.store,self.user)
        source=compare.research_inventory(self.store,self.admin)['sources']
        self.assertEqual(source[0]['reference_values'],{'mean':0.66,'standard_deviation':0.91,'valid_n':42926,'total_n':43517})
        self.assertEqual(source[1]['reference_values']['valid_n'],42764)

    def test_research_and_admin_activation_are_distinct(self):
        pointer=self.confirmation()
        self.assertEqual(self.gate().status,'blocked')
        self.activate(pointer)
        result=self.gate()
        self.assertEqual(result.status,'approved')
        self.assertEqual(result.values.valid_n,42926)
        self.assertEqual(result.values.total_n,43517)

    def test_pending_research_cannot_be_enabled_by_admin_toggle(self):
        pointer=self.confirmation(status='pending')
        with self.assertRaises(HTTPException):self.activate(pointer)
        self.assertEqual(self.gate().status,'blocked')

    def test_only_exact_scope_is_approved_and_video_cannot_construct_target(self):
        from app.domain.comparisons_v4 import ComparisonScopeV4
        pointer=self.confirmation();self.activate(pointer)
        target=compare.target_scope('us2026-stranger-fear')
        for change in ({'survey_version':'old-1-5-comfort'},{'policy_version':'survey-policy-20261002-s1.1'},{'scale_minimum':1},{'direction':'higher_comfort'},
                       {'question_text_hash':'0'*64},{'domain':'가르치는 방식'},{'missing_policy':'partial_mean'}):
            with self.subTest(change=change):
                value=compare.external_for_report(self.store,'us2026-stranger-fear',target.model_copy(update=change),self.user)
                self.assertEqual(value.status,'blocked');self.assertIsNone(value.values)
        with self.assertRaises(ValueError):ComparisonScopeV4.model_validate_json(encode({**target.model_dump(mode='json'),'measurement':'video'}))

    def test_population_unknown_must_not_be_inferred(self):
        pointer=self.confirmation(requirements={'study_scope':'synthetic-eligible'});self.activate(pointer)
        self.assertEqual(self.gate().status,'blocked')
        self.assertEqual(self.gate(population={'study_scope':'other'}).status,'blocked')
        self.assertEqual(self.gate(population={'study_scope':'synthetic-eligible'}).status,'approved')

    def test_new_research_revision_and_revocation_block_new_output(self):
        pointer=self.confirmation();self.activate(pointer)
        old=self.gate()
        next_pointer=self.confirmation(revision=1)
        self.assertEqual(self.gate().status,'blocked')
        self.activate(next_pointer,revision=1)
        self.assertEqual(self.gate().status,'approved')
        self.activate(next_pointer,enabled=False,revision=2)
        self.assertEqual(self.gate().status,'blocked')
        self.assertEqual(old.values.mean,0.66)

    def test_damaged_research_evidence_and_nonadmin_activation_block(self):
        pointer=self.confirmation();self.activate(pointer)
        self.store.path('comparison-evidence/synthetic.txt').write_bytes(b'changed')
        self.assertEqual(self.gate().status,'blocked')
        disabled=self.activate(pointer,enabled=False,revision=1)
        self.assertFalse(disabled.enabled)
        with self.assertRaises(HTTPException):compare.activate_external(self.store,compare.ActivateExternalV4(source_id='us2026-stranger-fear',
            expected_revision=2,confirmation=pointer,enabled=False,reason='unauthorized'),self.user)

    def test_stale_activation_revision_cannot_overwrite_revocation(self):
        pointer=self.confirmation();self.activate(pointer)
        self.activate(pointer,enabled=False,revision=1)
        with self.assertRaises(HTTPException):self.activate(pointer,enabled=True,revision=1)
        self.assertEqual(self.gate().status,'blocked')
