# PR-RP01 설문 응답 정책 적용

버전: v1.0 · 2026-10-07 · 상태: 계획·미구현 · 선행: 없음

상위: [수용안 적용 계획](K-DOG_리포트수용안적용계획_v1.0_20261007.md). 연결: A01, D05/P05 중 설문, R02/R07, T14/T25, RP-T01~03.

브랜치 제안: `veluga/rp01-survey-policy` · PR 제목: `feat: apply complete-response survey policy`

## 문제와 목표

비공포 문항이 누락되면 현재 `policy_pending`과 D05 미확정 안내를 반환한다. 회신은 비공포 문항의 필수 응답과 전체 응답 전제 계산을 확정했다. 정상 제출의 계산식을 유지하고 예외 누락은 해당 묶음의 보완 필요 상태로 처리한다. 구글폼 필수 설정은 의뢰자가 수행하며 앱은 실제 입력의 누락을 다시 확인한다.

## 변경 범위

| 기존/제안 파일 | 변경 내용 |
| --- | --- |
| `backend/app/survey_v4.py`, `resources/rules/survey-policy-v4.json` | 원본 추출 정책은 보존. 제안 신규 `resources/rules/survey-policy-20261007.json`을 runtime에서 선택하여 완전응답·누락 상태·근거 판본 분리 |
| `backend/app/domain/catalog_v4.py`, `backend/app/domain/comparisons_v4.py` | 기존 S1 정책에 고정된 상수·Literal·snapshot 기본값의 읽기/신규 생성 경계를 함께 개정 |
| `backend/app/forms_v4.py`, `backend/app/api.py` | 파일/수동 입력의 누락 문항 안내와 반환 계약 확인. 원입력 저장·접수 전체를 일괄 거절하는 조건 추가 없음 |
| `backend/app/comparisons_v4.py`, `backend/app/exports_v4.py`, `backend/app/report_profile_v4.py` | 공통 산출 함수의 정책 버전·상태 변경을 모든 소비 경로에 반영 |
| `frontend/src/types.ts`, `frontend/src/SurveyView.tsx`, `frontend/src/FormsImporter.tsx` | 미확정 정책 안내를 응답 보완 안내로 변경. Q10~14 규칙과 단일값 구분 |
| 기존 설문·Forms·비교·export·report 시험 | 상태 변경과 완전응답 계산 회귀, 판본이 다른 집단 제외 |

`survey_scores_v4`의 Graft 호출 관계는 설문 API·집단 snapshot·연구 export·리포트로 이어진다. UI 문구만 바꾸거나 리포트에서 별도 평균을 계산하지 않는다.

## 구현 순서

1. 회신 적용 정책의 출처·버전과 원래 문항 판본을 분리한다. 문항 원문·척도·역채점은 변경하지 않는다. `registration_completion`을 수정할 때 구글폼 필수 응답과 앱 접수/촬영 완료 요건을 혼동하지 않는다.
2. Q10~11·Q12~14는 현행 그대로 둔다. Q1~6·Q7~9·Q15~21·Q22~23·Q26~28은 전부 응답했을 때만 기존 평균을 계산한다. 누락 시 numerator/denominator/mean을 계산값으로 제공하지 않고 누락 ID와 보완 사유를 반환한다.
3. Q24·Q25는 단일 응답이며 평균 묶음으로 합치지 않는다. Q26~28은 `6-원응답`을 유지한다. 유효값 0과 null을 구별한다.
4. Forms 파일/직접 입력/과거 S1 자료에서 누락을 처리한다. 유효한 다른 영역은 정상 산출하고 임의 0 대체·부분평균·전체 리포트 차단을 추가하지 않는다.
5. 자체 집단·외부 비교 범위·내보내기의 정책 판본 연결을 갱신한다. 기존 snapshot을 새 정책으로 소급 재계산하지 않는다. 원본 추출 검사와 회신 적용 정책 검사를 분리한다.

### Cold review 수용: 판본 전환의 소비 경로

`SurveyPolicyV4`/`SurveyResultV4`, 비교 `SurveyPolicy` Literal·`CohortSnapshotV4`/`CohortPublicV4`, `comparisons_v4.target_scope`/`aggregate`와 frontend 타입은 기존 정책 이름에 고정되어 있다. 새 자산 파일을 선택하는 것만으로는 새 결과가 이 경로를 통과하지 못한다. 새 실행은 새 정책을 명시하고, 과거 S1 snapshot 읽기는 저장된 정책·내용을 그대로 검증하도록 구분한다. 모든 판본을 허용하거나 과거 파일에 새 기본값을 주입하는 방식은 사용하지 않는다. 기존 외부 비교의 허용 범위도 새 설문 정책으로 자동 승인하지 않는다.

## 검증과 완료 조건

- RP-T01~03 전수 결측 위치, 원응답/역채점, 단일값, 잘못된 척도, 원입력 불변을 확인한다.
- 비공포 부분 응답은 더 이상 연구 정책 결정 대기로 표시하지 않으며 실제 응답 보완 대상으로 안내한다.
- 동일 입력의 API·자체 집단·CSV/XLSX·리포트 값과 정책 버전이 일치한다.
- 기존 정책 S1 snapshot의 읽기·다운로드는 보존되며, 새 정책 집단의 생성·조회가 성공한다. 신구 정책을 섞은 집단은 거절하고 기존 외부 비교 범위와 새 정책 불일치는 계속 차단한다. 이 시험은 RP01에서 수행하고 RP05까지 미루지 않는다.
- D05의 추가 관찰 무효 규칙, D03 관찰창과 외부 비교 기준표 대기는 해제하지 않는다.

구현 후 backend에서 `uv run --locked python -X utf8 -m unittest tests.test_survey_v4 tests.test_forms_import_v4 tests.test_forms_api_v4 tests.test_comparisons_v4 tests.test_exports_v4 tests.test_report_content_v4 -v`를 수행한다. frontend에서는 `npm run build`, S1 환경(`$env:KDOG_TEST_INTAKE_SPEC='20261002'`)에서 `npx playwright test tests/survey-v4.spec.ts tests/importer-v4.spec.ts tests/comparisons-v4.spec.ts`를 수행한다. 현재는 실행하지 않았다.

## 인계

RP02/RP03에 새 설문 정책 버전·필드·결측 예제를 전달한다. 구글폼 필수 설정 확인과 앱 구현 검증은 별도로 기록한다. 코드·시험·UI 계약을 함께 변경하되 운영 데이터 초기화는 하지 않는다.
