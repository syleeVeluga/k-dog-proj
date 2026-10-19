# PR-AC04 산출물 채택과 게시

버전: v1.0 · 2026-10-20 · 상태: **계획 / 구현·시험 미착수** · 조사 기준: `bdc526f` · 직접 선행: AC03 병합

브랜치 제안: `veluga/ac04-owned-result-publication` · 제목 제안: `refactor: use owned transactions for result adoption and publication`

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 선행 계약: [AC03](K-DOG_PR-AC03_점유쓰기와Worker_v1.0_20261020.md). 요구 AC-R06·R08·R09·R11·R12.

## 1 문제와 완료 결과

AC03의 Worker 쓰기 외에도 산출물 채택, 실행 종료, AI 기본 결과 게시가 각각 점유와 현재 실행 계정을 재검사한다. 동일한 트랜잭션 수명은 AC03의 module을 사용하고, 입력/출력의 hash·stamp·최신 attempt·발급 감사 등 업무별 조건은 기존 위치의 같은 body에 둔다.

완료 결과는 아래 **다섯 쓰기 구간**이 같은 점유 interface를 사용하면서 각 결과의 의미를 유지하는 것이다. 결과 종류별 finish를 하나의 범용 상태 전환 함수로 합치지 않는다.

## 2 파일별 변경과 전환 순서

| 순서·대상 | 공통화 | 같은 body에 남길 검증/쓰기 |
| --- | --- | --- |
| 1. [analysis.adopt](../../../backend/app/analysis.py#L127) | 139~143행 연결·현재 run·점유 검사 | 원/출력 stamp, 최신 attempt 검사, step 상태·output_ref/hash·usage 반영 |
| 2. [run_v4.finish](../../../backend/app/run_v4.py#L352) | 354~358행 연결·점유/현재 계정 검사 | source stamps, publish_v4 성공 step 선택, 성공/부분실패의 result pointer, 점유 해제 |
| 3. [attachment_runs_v4.process](../../../backend/app/attachment_runs_v4.py#L246) | 종료부의 247~251행 검사 | 마지막 step에 따른 succeeded/retry_wait/failed와 결과 pointer·점유 해제 |
| 4. [scoring_ai_v4.publish](../../../backend/app/scoring_ai_v4.py#L402) | 413~417행 연결·점유/계정 검사 | 입력 stamps, 기존 결과 일치, AI 기록 계정 충돌, 시트·결과·ai.publish 감사 원자 기록 |
| 5. [report_runs_v4.finish](../../../backend/app/report_runs_v4.py#L682) | 685~689행 연결·점유/계정 검사 | source/asset stamps, publication pointer, 점유 해제, report.s1.issue 감사 |

예정 시험 변경: 기존 `test_run_v4.py`, `test_scoring_ai_v4.py`, `test_attachment_ai_v4.py`, `test_report_runs_v4.py`, `test_gemini_key_fallback.py`, `test_execution_actor_v4.py`. 추가 공통 트랜잭션 시험은 AC03의 `test_owned_run_write.py`에 필요한 경우만 보완한다. `storage.py` schema, domain DTO, 출력 renderer, `gemini_keys.py`는 변경 대상이 아니다.

## 3 채택과 복구의 상세 계약

1. `adopt`의 파일 읽기·hash 검증·candidate 구성과 source/output stamp 수집을 기존 트랜잭션 밖에서 수행한다. body 진입 뒤 current run과 실제 실행 계정을 재검사한다.
2. 같은 body에서 source stamps와 산출물의 마지막 file stamp를 확인하고, 해당 stage/branch의 **가장 최신 attempt**인지 확인한다. 검사와 `steps.status='succeeded'` 반영을 분리하지 않는다.
3. **현재 worker의 점유 토큰과 회복 대상 attempt의 원래 토큰을 구분**한다. 중단된 최신 attempt의 파일 회복 시 current run은 새 claim을 가질 수 있다. step의 원 token·output manifest를 검증하는 기존 계약과 UPDATE의 `step['claim_token']` 조건을 유지한다. step token을 무조건 current run token으로 바꾸거나 비교하여 정상 회복을 막지 않는다.
4. `runs/<run_id>/<step_id>/output.json` 경로, run/step/input/config/hash 일치, 최신 attempt 및 상태 조건, rowcount 검사를 유지한다. 새 attempt가 이미 생긴 이전 output의 채택은 거절한다.
5. 손상/누락 파일, 입력/자산 변경, 오래된 claim, 중지·만료·비활성 실행 계정은 성공 상태/결과 pointer를 남기지 않는다. 기존 오류 종료와 usage 기록은 Worker가 이어서 처리할 수 있어야 한다.

## 4 게시·발급의 상세 계약

- S1 finish는 기존 publish_v4 성공 산출물을 선택하고 `succeeded/partial_failed` 등 현재 조건에서만 result_ref/hash를 설정한다. lease 해제와 상태 갱신은 같은 body다.
- 애착 단독 실행의 succeeded/retry_wait/failed 판단과 마지막 step 결과 참조를 유지한다. 통합 AI 애착 단계와 독립 `attachment_v4`를 모두 회귀에 포함한다.
- `scoring_ai_v4.publish`가 트랜잭션 전에 생성하는 불변 결과 파일은 현재 순서대로 둔다. 같은 result_id가 이미 있으면 문서 일치를 검사하고 기존 참조를 돌려준다. 다르면 충돌로 거절한다.
- 시트·기본 결과·AI 기록 전용 계정 생성이 필요한 경우와 `ai.publish` 감사는 한 transaction에 남긴다. 실제 actor는 현재 retry 기록을 따르며 AI 기록 전용 계정을 실제 요청자로 바꾸지 않는다.
- 리포트는 트랜잭션 전 자산 검증과 body 안 `check_asset_stamps`, 입력/출력 stamps를 유지한다. publication pointer·실행 상태·`report.s1.issue`를 함께 확정하고 기존 실제 retry actor를 기록한다.
- 쓰기 실패 전에 이미 만들어진 불변 파일을 새 module이 임의 삭제하지 않는다. DB 채택 여부와 파일 존재는 다를 수 있으며 기존 참조 검증/clean 정책을 따른다.
- 기존 발급 HTML/PDF/manifest bytes, 사용량·선택 키·재사용 출처를 다시 직렬화하거나 덮어쓰지 않는다. 최신 설정을 이전 실행 snapshot에 섞지 않는다.

## 5 시험과 관찰 결과

| ID | 상황 | 기대·시험 배치 |
| --- | --- | --- |
| AC-T15 | 중단 최신 attempt output 회복, 새 claim, 그 뒤 더 최신 attempt 존재 | 정상 회복은 재호출 없이 채택; 더 오래된 attempt는 거절, 원 토큰/불변 bytes 보존; `test_run_v4` |
| AC-T16 | 공통 검사 전후 claim·중지·lease·actor·revision 변경 | 쓰기 진입 전에 최신 상태로 거절, 새 소유자 결과에 영향 0; 다섯 구간의 fixture·기존 actor/fallback 시험 |
| AC-T17 | 파일 hash/최종 stamp·리포트 자산 변경/누락, 다른 run/step output | DB 성공·게시 pointer 없음; 정상 동등 파일은 기존 회복 성공; `test_run_v4`·`test_report_runs_v4`·`test_gemini_key_fallback` |
| AC-T18 | 동일 AI result 재채택·상이한 문서 충돌·AI 계정 이름 충돌·감사 직전 오류 | 중복 시트/결과/감사 생성 없음, 실패 시 transaction 전체 rollback; `test_scoring_ai_v4`·`test_execution_actor_v4` |
| AC-T19 | S1 부분실패·애착 대기/성공·리포트 발급·retry actor | 종류별 상태와 pointer 유지, report.s1.issue/ai.publish의 실제 actor와 원자성 유지; 세 실행·게시 회귀 |

공통 context manager 직접 시험만으로 다섯 업무 연결을 검증한 것으로 보지 않는다. 각 실제 경로에서 하나 이상의 정상 동작과 stale/실패 결과를 확인한다. 늦은 파일 변경은 stamp 수집과 최종 검사 사이에 확정 순서로 주입한다. 실제 공급자 대신 기존 transport fixture를 사용한다.

```powershell
# backend/ — AC03의 신설 시험 포함
uv run --locked python -X utf8 -m unittest -v tests.test_owned_run_write tests.test_run_v4 tests.test_scoring_ai_v4 tests.test_attachment_ai_v4 tests.test_report_runs_v4 tests.test_execution_actor_v4 tests.test_gemini_key_fallback tests.test_gemini_acceptance tests.test_report_acceptance_v4 tests.test_shared_outputs_v4
# 저장소 루트
git diff --check
graft build
graft check
```

## 6 잔존 확인과 되돌림

Graft로 `claim_token`, `lease_expires_at`, `check_access`, `worker.stage`를 exhaustive 검색한다. 결과를 **AC03/04 전환한 정상 쓰기 / claim·heartbeat / 오류 종료 / 사용자 action / 업로드·전처리 별도 체계**로 분류한다. 단순히 검색 결과가 0이 되는 것을 목표로 삼지 않는다. 해당 표를 AC05에 인계한다.

독립 cold review에서는 공통 검사와 domain stamp 검사가 실제 같은 db 수명에 있는지, try/except 이동으로 commit 의미가 바뀌지 않았는지, 호출 순환과 dynamic caller 누락이 없는지 검토한다.

실패 시 AC04만 되돌리면 AC03의 Worker 공통화와 기존 나머지 검사를 함께 사용할 수 있다. AC03까지 되돌릴 경우 역순으로 적용한다. 이전 실행·발급 결과와 DB를 초기화하거나 점수를 재생성하지 않는다.

- [ ] AC-T15~T19·관련 회귀 통과와 다섯 쓰기 구간 증거
- [ ] 이전 attempt 회복·현재 claim 구분 및 게시 감사 원자성 확인
- [ ] 잔존 분류·공식 확인·독립 검토·수용 재검증 기록
- [ ] AC05에 코드 기준·불변 산출물 비교·후속 목록 인계

| 실행 항목 | 결과 |
| --- | --- |
| 선행 AC03/구현 commit·PR | 미실행 |
| 시험 명령·건수·시간·결과 | 미실행 |
| cold review·발견사항 조치 | 미실행 |
| 정상 쓰기/의도적 잔존 목록 | 미실행 |
