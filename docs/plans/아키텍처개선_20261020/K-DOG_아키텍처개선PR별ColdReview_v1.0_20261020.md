# K-DOG 아키텍처 개선 PR별 추가 Cold Review

버전: v1.0 · 2026-10-20 · 검토 기준: `main / d693315` · 상태: **AC01~AC05 독립 검토 완료 / 수용0건**

사용자가 각 PR에 대해 `cold review(subagents) → 수용 건만 반영 → 병합`을 요청하여 수행한 추가 독립 검토다. [최초 구현·검증](K-DOG_아키텍처개선실행기록_v1.0_20261020.md)의 검토와 구별한다. 착수 시 #107~#111은 이미 병합되어 있었다. 기존 병합 이력은 보존하고, 새로운 수용 건이 있으면 담당 원 PR에 연결한 후속 PR에서 수정·검증·재검토 후 병합한다.

## 1 PR별 검토 범위

각 담당자는 이전 검토 결론을 근거로 삼지 않고 diff·현재 main·실제 호출자·해당 계획의 보존 조건을 대조했다. Graft wiring은 동기화 상태이고 deep 의미 요약은 미생성이다. 운영 DB·참가자 데이터·실제 공급자는 사용하지 않는다.

| PR | 독립 reviewer | 담당 diff | 상태 |
| --- | --- | --- | --- |
| AC01 [#107](https://github.com/syleeVeluga/k-dog-proj/pull/107) | `ac01_fresh_cold` | `f58b21e..f949d55` 및 현재 연결 | 완료; actionable P1/P2 0건 |
| AC02 [#108](https://github.com/syleeVeluga/k-dog-proj/pull/108) | `ac02_fresh_cold` | `f949d55..0e01185`; 저장 예외·T09 후속 포함 | 완료; 새 actionable P1/P2 0건 |
| AC03 [#109](https://github.com/syleeVeluga/k-dog-proj/pull/109) | `ac03_fresh_cold` | `0f8445e..4bbe1f0` 및 현재 연결 | 완료; actionable P1/P2 0건 |
| AC04 [#110](https://github.com/syleeVeluga/k-dog-proj/pull/110) | `ac04_fresh_cold` | `4bbe1f0..78f4695` 및 현재 연결 | 완료; actionable P1/P2 0건 |
| AC05 [#111](https://github.com/syleeVeluga/k-dog-proj/pull/111) | `ac05_fresh_cold` | `3ede709..8bfd28e` 및 최종 병합 `d693315` | 완료; actionable0건 |

## 2 발견사항 판단과 반영

재현 조건·업무 영향·담당 범위를 확인한 건만 수용한다. 제안이나 시험 한계 자체를 제품 결함으로 기록하지 않는다. 기존 문제와 추출로 생긴 회귀를 구별한다.

| PR | 판단 근거·반영 |
| --- | --- |
| AC01 | 기존 merge 식과 순수 module의 저장 JSON·배열 순서·출처/hash·미실시/누락·수동 필드 보존이 동등하다. bytes/hash·strict UTF-8·요청/대상/회차/record guard·기준 영상 변경·unmount·revision 저장 경계를 확인했다. 수용0건 |
| AC02 | pending 저장/복원/예외, 선택, POST·poll·제어 순서와 접근 상실, revision/visibility/unmount, 부분 성공·4xx 의미를 확인했다. 담당 source와 두 spec은 `0e01185..d693315`에서 추가 변경 없다. 수용0건 |
| AC03 | 동일 BEGIN IMMEDIATE에서 현재 run/running/claim/lease와 실제 실행 계정·입력 판본을 검사한다. Worker 네 쓰기, credential 실패의 예약 commit, 한번 예약·호출 상한·usage와 once 별도 오류 종료를 확인했다. 수용0건 |
| AC04 | 채택·S1/애착 완료·AI 게시·리포트 완료 다섯 쓰기에서 원 step token·최신 attempt·envelope/stamp·usage·실제 retry actor·중복/충돌·계정/시트/결과/감사 원자성을 확인했다. 담당 제품5파일은 `78f4695..d693315`에서 변경 없다. 수용0건 |
| AC05 | 17파일 manifest를 통합전/후3commit에 대조하고, 6PNG 크기/hash/정적 표시·PR 부모·원로그·실제 시험 이름/본문·9쓰기/80잔존·공식 의존성 근거를 확인했다. 전체150+후속3, 역사v3 skip2와 S1원본 대조/G01·G04미수령 및 미실측 인수가 구별된다. 수용0건 |

AC01 검토 한계: 새 순수 fixture의 events·coverage·tail은 빈 배열이므로 비어 있지 않은 값의 보존은 실행 검증 대신 기존 object spread와 diff로 확인했다. 이번 검토자는 Playwright 서버를 실행하지 않았다. 대상/회차 전환 보호는 keyed remount·cleanup 호출 경로로 확인했다.

AC02 검토 한계: Node core in-memory harness는 실제 hook body의 타입만 제거한 경쟁 조건6개 및 실제 adapter의 복원·부분 실패/409 경로를 검증했다. 실제 React/browser E2E는 다시 실행하지 않았으며 source harness를 브라우저 통합 시험으로 간주하지 않는다.

AC05 검토 한계: 전체 회귀는 기존 로그·고정 hash·실제 시험 코드로 대조했다. 정적 PNG가 상호작용 전체를 보증하지 않으며 실제 공급자·현장 검수·새 배포는 재실행하지 않았다. 공식 registry 재조회에서 기록의 최신/선택판·engine/peer와 모순을 찾지 못했다.

수용0건이므로 제품·시험·리소스는 검토 기준 `d693315` 그대로 유지한다. 이번 후속 변경은 검토 기록과 해당 문서로의 링크다.

## 3 검증 근거와 통합

루트에서 실제 실행한 확인: `graft check` wiring sync, 기존 동결 manifest 17파일 및 화면 PNG6개 hash 일치. OS 임시 로그의 기존 결과는 backend795/1352.898초/OK(skip2), 전체 E2E150/9.8분, 후속3/21.5초와 일치한다. 이는 이전 실행 결과의 대조이며 새 전체 시험 실행으로 표시하지 않는다.

AC03 reviewer 새 실행: `uv run --locked python -X utf8 -m unittest tests.test_owned_run_write tests.test_run_v4 tests.test_gemini_key_fallback tests.test_execution_actor_v4 -v` → **46 tests / 162.966초 / OK**. 실행 출력으로 확인했으며 별도 로그 파일은 없다. 임시 합성 SQLite·가짜 공급자만 사용했다.

AC04 reviewer 새 실행: 원 token/attempt 회복·report 감사/bytes·AI 게시6건 **15.818초 OK**, attachment 정상/actor 취소·S1 부분실패/output 변경·report output 변경5건 **28.448초 OK**. 총 **11 tests / 44.266초 / OK**. 실제 다중 프로세스 경합의 실측·실공급자·현장 인수는 수행하지 않았다. Graft static callers가 놓친 module-qualified 호출3곳은 exhaustive 검색과 Worker dispatch로 보완했다.

AC04 재현 명령(`backend/`):

```powershell
uv run --locked python -X utf8 -m unittest -v tests.test_owned_run_write.OwnedRunWriteTests.test_recovery_keeps_original_step_token_and_rejects_older_attempt tests.test_owned_run_write.OwnedRunWriteTests.test_report_issue_audit_failure_rolls_back_publication_and_recovers_bytes tests.test_scoring_ai_v4.AiPublicationV4Tests
uv run --locked python -X utf8 -m unittest -v tests.test_attachment_ai_v4.AttachmentOpinionTests.test_opinion_interpretation_preserves_basic_and_original_text_withdrawal_blocks_reuse tests.test_attachment_ai_v4.AttachmentOpinionTests.test_revoked_actor_cannot_adopt_opinion_inference tests.test_run_v4.RunV4Tests.test_partial_group_failure_publishes_explicit_nulls_and_preserves_successes tests.test_run_v4.RunV4Tests.test_file_changed_after_validation_cannot_be_adopted tests.test_report_runs_v4.ReportRunV4Tests.test_mutated_output_between_validation_and_adoption_is_rejected
```

최신/선택 의존성과 유지 이유는 동일 세션 2026-10-20에 확인한 [실행 기록 §2](K-DOG_아키텍처개선실행기록_v1.0_20261020.md#2-공식-버전호환성-확인)를 따른다. 새 의존성을 설치하거나 잠금을 바꾸지 않는다.

새 실행은 위 Node source harness 및 backend46건+11건이며 기존 전체 시험의 재실행으로 기록하지 않는다. 후속 PR의 최종 병합 상태는 GitHub 이력으로 확인한다. 원래의 G01/G04 실물 미수령, 실공급자 품질, 물리 PC 검수 및 배포 후속은 유지한다.

후속 기록 자체도 `ac05_fresh_cold`가 읽기 전용으로 재검토하여 actionable0건이었다. 문서10개·상대 링크107개·서로 다른 대상53개·요구12/시험ID22 및 동결17파일 검사에서 오류0건을 확인했다. `git diff --check` 통과, 제품/시험/리소스는 검토 기준과 동일하다.
