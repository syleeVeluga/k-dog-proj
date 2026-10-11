"""AR06 current templates and historical columns are separate from raw source preservation."""
import unittest

from app import forms_v4 as forms, intake
from tests import test_forms_import_v4 as support


class SharedInputV4Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=support.FormsImportV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store

    def test_legacy_consent_values_are_raw_only_and_missing_legacy_mapping_is_ignored(self):
        for index,value in enumerate(('confirmed','declined','unknown','', 'arbitrary historical cell')):
            with self.subTest(value=value):
                data=support.csv_bytes([['반려견','참가번호','기본 동의','분석 동의','접촉 동의','문항1','두려움'],
                    ['합성견',f'000{index}',value,value,value,'3','0']])
                request=self.fixture.request.model_copy(deep=True)
                request.request_id=f'legacy-{index}'
                request.mapping.columns.update(participant_id='참가번호',consent_confirmed='기본 동의',
                    consent_analysis_feedback='분석 동의',consent_stranger_contact='접촉 동의')
                shown=self.fixture.stage(data,request)
                self.assertEqual(shown.errors,[])
                self.assertEqual(shown.rows[0].raw_values['분석 동의'],value)
                result=self.fixture.apply(shown,request_id=f'commit-{index}',actor='reviewer')
                manifest=self.fixture.manifest(result.rows[0].case_id)
                self.assertEqual(manifest.consents.analysis_feedback,'unknown')
                self.assertEqual(manifest.sessions[0].survey['s10'],0)
                self.assertEqual(shown.rows[0].participant_id,f'000{index}')
                with self.store.connect() as db:
                    record,_,_=forms._load_preview(self.store,db,shown.preview_id)
                self.assertEqual(self.store.path(record['source']['ref']).read_bytes(),data)
                self.assertEqual(record['original_rows'][1][3],value)
        request=self.fixture.request.model_copy(deep=True)
        request.request_id='missing-legacy'
        request.mapping.columns.update(consent_confirmed='missing',consent_analysis_feedback='반려견')
        shown=self.fixture.stage(request=request)
        self.assertEqual(shown.errors,[])

    def test_new_templates_and_participant_projection_never_use_consent_columns(self):
        for format in ('csv','xlsx'):
            for kind in ('roster','full'):
                rows,_,_=forms._table(forms.template(kind,format),format,'입력' if format=='xlsx' else None)
                header=' '.join(rows[0])
                self.assertNotIn('동의',header)
        self.assertFalse(any(key.startswith('consent') for key in intake.headers('participants')))
        participant=intake.participant_row({'event_id':'AR06','participant_id':'0001','dog_name':'합성',
            'consent_confirmed':'unparseable','consent_analysis_feedback':'declined'})
        self.assertFalse(participant.consent_confirmed)
        self.assertEqual(participant.consents.analysis_feedback,'unknown')
