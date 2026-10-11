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
        self.assertTrue(compare.for_report(self.store,one.reference,self.user))

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

    def test_unknown_consent_blocks_creation_but_reviewer_can_manage_candidates(self):
        self.edit(0,lambda manifest:setattr(manifest.consents,'analysis_feedback','unknown'))
        self.assertTrue(self.create().reference)
        compare.list_snapshots(self.store,self.reviewer)
        self.assertEqual(compare.candidates(self.store,self.reviewer), compare.candidates(self.store,self.user))

    def test_deleted_member_blocks_full_snapshot_and_removes_shared_reference(self):
        value = self.create()
        original = self.store.path(value.reference.ref).read_bytes()
        with self.store.connect(write=True) as db:
            db.execute('UPDATE cases SET deletion_requested=1 WHERE case_id=?', (self.ids[1],))
            self.store.audit(db, self.user.username, self.ids[1], 'deletion.record', {'event_id':'legacy','participant_id':'legacy'})
        from app.maintenance import clean
        clean(self.store)
        self.assertTrue(compare.for_report(self.store,value.reference,self.user))
        self.assertEqual(len(compare.list_snapshots(self.store,self.user)), 1)
        self.assertEqual(self.store.path(value.reference.ref).read_bytes(), original)

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
        with patch.object(compare,'_write',side_effect=deleted):self.create()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM changes WHERE action=?',(compare.COHORT_ACTION,)).fetchone()[0],1)

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
    def definition(self, **kwargs):
        from tests.test_external_comparisons_v4 import define
        return define(self.store, user=self.user, **kwargs)[0]

    def gate(self, **kwargs):
        return compare.external_for_report(self.store,'us2026-stranger-fear',compare.target_scope('us2026-stranger-fear'),self.user,**kwargs)

    def test_missing_definition_never_exposes_reference_numbers(self):
        payload=encode(compare.public_sources())+self.gate().model_dump_json(exclude_none=True)
        for number in ('0.66','0.91','42926','1.03','0.78','42764','43517'):
            self.assertNotIn(number,payload)
        self.assertEqual(self.gate().status,'blocked')
        self.assertEqual(compare.definition_inventory(self.store,self.user),compare.definition_inventory(self.store,self.admin))

    def test_save_applies_actual_definition_without_confirmation_or_activation(self):
        pointer=self.definition()
        result=self.gate()
        self.assertEqual(result.status,'ready')
        self.assertEqual(result.definition,pointer)
        self.assertIsNone(result.confirmation);self.assertIsNone(result.activation_revision)
        self.assertEqual((result.values.valid_n,result.values.total_n),(42926,43517))
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action IN ('comparison.research','comparison.activation')").fetchone()[0],0)

    def test_missing_or_invalid_numeric_definition_is_not_permission(self):
        from app.domain.comparisons_v4 import ComparisonDefinitionInputV4
        pointer=self.definition()
        document=compare.definition_document(self.store,pointer).model_dump(mode='json')
        for key in ('definition_id','revision','actor','recorded_at','artifact_kind'):document.pop(key)
        for values in ({'mean':None},{'valid_n':0},{'valid_n':43518},{'standard_deviation':-1},{'mean':5}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                ComparisonDefinitionInputV4.model_validate_json(encode({**document,'values':{**document['values'],**values}}))

    def test_exact_scope_and_actual_population_remain_required(self):
        self.definition(population={'study_scope':'synthetic-eligible'})
        self.assertEqual(self.gate().status,'blocked')
        self.assertEqual(self.gate(population={'study_scope':'synthetic-eligible'}).status,'ready')
        target=compare.target_scope('us2026-stranger-fear')
        for change in ({'survey_version':'old-1-5-comfort'},{'scale_minimum':1},{'direction':'higher_comfort'},
                       {'question_text_hash':'0'*64},{'domain':'가르치는 방식'},{'missing_policy':'partial_mean'}):
            with self.subTest(change=change):
                value=compare.external_for_report(self.store,'us2026-stranger-fear',target.model_copy(update=change),self.user,population={'study_scope':'synthetic-eligible'})
                self.assertEqual(value.status,'blocked');self.assertIsNone(value.values)

    def test_new_revision_is_immediate_retirement_excludes_new_selection_and_stale_save_fails(self):
        from tests.test_external_comparisons_v4 import retire
        first=self.definition()
        second=self.definition(revision=1)
        self.assertEqual(self.gate().definition,second)
        retired=retire(self.store,second,self.admin)
        self.assertEqual(self.gate().status,'blocked')
        self.assertEqual(retired.revision,3)
        with self.assertRaises(HTTPException):self.definition(revision=1)
        self.assertEqual(compare.definition_document(self.store,first).revision,1)

    def test_actual_evidence_tamper_blocks_values(self):
        first=self.definition()
        doc=compare.definition_document(self.store,first)
        self.store.path(doc.evidence[0].ref).write_bytes(b'changed')
        self.assertEqual(self.gate().status,'blocked')
        with self.assertRaises(HTTPException):compare.definition_document(self.store,first)
