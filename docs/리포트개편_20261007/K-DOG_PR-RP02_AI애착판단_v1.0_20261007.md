# PR-RP02 근거 기반 AI 애착 판단

버전: v1.0 · 2026-10-07 · 상태: 계획·미구현 · 선행: RP01

상위: [수용안 적용 계획](K-DOG_리포트수용안적용계획_v1.0_20261007.md). 연결: A03, D04/P04, R04/R05, T11~13/T24/T32, RP-T04/05/07.

브랜치 제안: `veluga/rp02-attachment-judgement` · PR 제목: `feat: generate evidence-linked attachment judgements`

## 문제와 목표

`judgements_v4.initial_decisions`와 `scoring_ai_v4.basic_data`는 애착 label 없이 D04 보류를 만든다. 현재 기준에 따라 AI가 유형을 먼저 판단하고 교수님이 테스트로 보완하도록 변경한다. 수치 임계값을 새로 만들거나 네 유형 중 하나를 강제로 선택하지 않는다.

## 변경 범위

| 기존/제안 파일 | 변경 내용 |
| --- | --- |
| 신규 제안 `backend/app/attachment_ai_v4.py`, 판단 지침 자산 | 고정 근거 입력·구조화 응답·허용 유형·근거/반대근거·보류 검사 |
| `backend/app/scoring_ai_v4.py`, `backend/app/gemini_v4.py`, `backend/app/run_v4.py`, `backend/app/worker.py` | 검증된 관찰·계산 이후 판단 단계 및 결과 발행 연결. 공통 요청/호출 예약·사용량·수리·취소 보호 재사용 |
| `backend/app/judgements_v4.py`, `backend/app/final_results_v4.py`, 관련 `domain/results_v4.py`, `domain/final_results_v4.py`, `domain/runs_v4.py` | AI 자동 판단을 별도 출처로 저장하고 원관찰/계산과 분리. 유형 없는 완료 의견의 처리 명시 |
| `backend/app/settings_v4.py`, `frontend/src/aiTypesV4.ts`, `frontend/src/finalTypesV4.ts`, 관련 AI/최종 결과 화면 | 무조건 D04 대기 표시 제거. 개발 가능/실제 실행/보류/교수 테스트 상태 구별 |
| 신규 제안 `backend/tests/test_attachment_ai_v4.py` 및 기존 판정/최종 결과/AI 시험 | 새 계약과 기존 우선순위·독립성·발급 소비 경로 회귀 |

## 구현 순서와 판단 계약

1. 명세 9절의 네 유형 이름·관찰 해석·한계를 지침으로 고정한다. 명세에 없는 점수식·확률 문턱·다섯 번째 유형은 추가하지 않는다.
2. 응답의 최소 필드는 `status`, `type 또는 null`, `reason`, `evidence_refs`, `counter_evidence_refs`, `hold_reason`, 사용한 입력/지침/모델 판본이다. 필드명은 구현 제안이며 교수님에게 전문 기준을 개발자가 확정한 것으로 표시하지 않는다.
3. AI 원관찰과 확정 계산을 우선 입력으로 사용한다. 독립 AI 최초 판정에는 사람 평가 결과를 섞지 않는다. 허용된 완료 의견을 사용하는 후속 해석은 별도 출처/노출 이력과 결과 revision으로 구분한다.
4. 관찰·계산 완료 후 비동기 실행 단계에서 유형을 판단한다. 계산 API의 DB transaction 안에서 외부 AI를 호출하지 않는다. 요청·응답을 고정하고 기존 호출 수/비용 제한에 신규 단계를 포함한다.
5. 완료 의견→유효 수동 선택→AI 기본 결과 우선순위를 유지한다. 명시 유형이 있는 완료 의견은 AI가 변경하지 않는다. 유형 없는 완료 애착 의견에서 AI가 해석한 유형은 사람의 명시 선택으로 위장하지 않고 원문과 추론을 별도로 표시·보존한다. 원문 의미가 불명확하면 해당 유형만 보류한다. 교육태도의 확정 계산이나 다른 영역의 유형 자동화를 이 PR에서 확대하지 않는다.
6. 미존재 근거·다른 대상·허용되지 않은 유형·근거 부족·상충을 검증한다. 제한된 계약 수리 후 실패하면 유형 보류 사유를 남기고 원관찰·다른 결과는 보존한다. 추가 호출 수는 기존 예산 범위에서 명시 설정하며 무한 재시도를 만들지 않는다.
7. 원점수·계산 비율·완료 의견 원문은 그대로 보존한다. 판정 수정은 새 결과 revision으로 남기고 카드·상세·총평은 같은 최종 유형을 참조한다.

### Cold review 수용: 실행 경로와 실패 격리

기존 `scoring_ai_v4.handler`는 채점·계산·게시 단계만 처리하며 `publish_v4`는 `basic_data`와 같은 결과인지 재검증한다. 새 판단 단계를 추가할 때 실행 단계 계약·의존 관계·게시 재검증·예산을 함께 개정한다. 애착 판단 결과가 없거나 수리 후에도 유효하지 않으면 실패 종류를 기록하고, 이미 검증된 원관찰·계산은 애착 보류가 명시된 기본 결과로 채택할 수 있게 한다. 판단 단계 실패를 전체 AI 성공으로 숨기지 않으며, 그 실패만으로 다른 유효 결과를 모두 잃게 하지 않는다. 삭제·권한 철회·입력 hash 불일치·점유 상실은 이 부분 채택의 대상이 아니며 기존대로 중단한다.

완료 애착 의견을 대상으로 하는 후속 해석은 그 의견 revision/hash를 고정한 별도 실행으로 수행한다. 이미 발행한 기본 결과를 수정하거나 원영상 채점을 다시 실행하는 경로에 끼워 넣지 않는다. 저장된 해석 결과를 최종 결과 조립이 읽도록 하고, GET/다운로드/동기식 `domains_for`에서 외부 AI를 호출하지 않는다. 의견 수정·철회 시 재사용을 거절하고 새 해석·최종 결과를 생성한다.

## 검증과 완료 조건

- RP-T04/05/07: 네 허용 유형, 근거 부족, 반대 근거, 잘못된 근거/유형, 공급자 실패, 수동/완료 의견 우선·철회, 새 revision을 검증한다.
- 상태 문구만 바꾸는 것으로 완료하지 않는다. 합성 공급자 응답→기본 결과→최종 결과→리포트 근거까지 값과 출처가 연결돼야 한다.
- 자동 검증은 계약·근거 참조·명시 모순을 검사하며 애착 판정의 전문적 정답을 보장하지 않는다. 실제 적절성은 RP05 교수 테스트로 확인한다.
- 완료 의견을 AI 입력으로 본 후에도 독립 판정으로 표시하는 회귀가 없어야 한다.
- 원관찰/계산 성공 뒤 판단 timeout·잘못된 응답을 주입해 애착 보류와 유효 기본 결과 보존을 확인한다. 반대로 삭제/권한 철회/hash 변경에서는 부분 채택도 차단되는지 검사한다.
- 유형 없는 완료 의견의 해석·수정·철회·명시 재실행에서 원채점 재호출과 과거 기본 결과 변경이 없고, 의견 revision이 다른 해석을 재사용하지 않는지 확인한다.

구현 후 backend에서 `uv run --locked python -X utf8 -m unittest tests.test_attachment_ai_v4 tests.test_judgements_v4 tests.test_final_results_v4 tests.test_opinions_v4 tests.test_scoring_ai_v4 tests.test_ai_api_v4 tests.test_gemini_v4 tests.test_settings_v4 -v`를 수행한다. `test_attachment_ai_v4`는 신설 예정이다. frontend에서는 build 후 S1 환경의 `tests/judgements-v4.spec.ts`, `tests/opinions-v4.spec.ts`, `tests/scoring-ai-v4.spec.ts`를 실행한다. 현재는 미실행이다.

## 인계

RP03에 최종 유형·출처·판단/반대 근거·보류 사유 계약을 전달한다. D04는 ‘방향 확정·구현 및 교수 테스트 대기’로 관리한다. 미제공 전문 기준을 임의 완성하거나 매 발급의 사람 승인을 새 필수조건으로 추가하지 않는다.
