# PR-ES03 AI 분석 진행 요약과 상태 복구

버전: v1.0 · 2026-10-12 · 상태: 구현·검증·독립 cold review 수용 반영·재검토 완료 · 기준 commit: `1702f2b`
상위: [전체 계획](K-DOG_내실행과분석진행표시계획_v1.0_20261012.md) · 선행: [ES02 구현·검증·병합](K-DOG_PR-ES02_전처리내작업화면과자동갱신_v1.0_20261012.md)
권장 브랜치: `codex/es03-analysis-progress` · PR 제목: `fix: AI 분석의 현재 실행 진행과 조회 복구 표시`

## 1 문제와 결과

[AiRunsV4](../../../frontend/src/AiRunsV4.tsx#L14)의 상단 `AI 초안`은 실행 목록 전체의 이전 게시 결과를 먼저 검사한다. 새 실행이 queued/running이어도 완료로 보이고, 결과가 있는 partial_failed도 정상 완료로 요약된다. 상세 과정은 닫힌 기술 정보에만 있다. 조회 실패 때 다음 폴링을 예약하지 않고 준비 정보도 지워 서버 통신 오류를 설정/전처리 부족처럼 표시할 수 있다.

이 PR은 기존 AI 분석 시작 버튼을 `AI 분석 시작`으로 이해하기 쉽게 표시하고, 실행 생성과 실행 완료를 구분한다. 선택한 **하나의 run_id**의 상태·예정 단계·실제 진행을 기본 카드에 보여준다. 분석/계산/애착/게시 규칙과 실제 공급자 호출 계획은 변경하지 않는다.

## 2 서버 진행 요약

1. 기존 S1 실행 DTO에 `requested_by`, `created_at`, `retry_at | null`, 실행의 고정 계획에서 계산한 `progress`를 추가한다. `requested_by`는 불변 입력 snapshot의 최초 요청자이며 후속 재시도 행위자로 덮어쓰지 않는다. 후속 재시도는 기존 감사 기록으로 유지한다.
2. progress 단계는 `score_v4 / calculate_v4 / attachment_v4 / publish_v4`이며 화면 명칭은 `항목군 관찰 / 기본 계산 / 애착 판단 / 결과 게시`다. score 단계의 예정 key는 현재 활성 설정이 아니라 **해당 run의 고정 config**를 따른다.
3. 각 예정 key의 최신 유효 attempt 상태를 읽고 아직 생성되지 않은 step은 대기로 제공한다. 이전 attempt/abandoned/superseded를 중복 합산하지 않는다. 재사용 성공은 재사용으로 명시하며 실제 새 호출 수로 세지 않는다. 관찰 항목군 개수는 완료/실패/대기·실행 중을 구분해 표시하되 AI 내부 백분율/남은 시간을 만들지 않는다.
4. 현재 실행 단계는 **run.status=running, 유효 lease, 현재 run claim과 같은 claim의 running step**인 경우에만 표시한다. `steps.claim_token`과 run의 현재 claim을 서버에서 대조한다. 중지/재시도/새 점유 뒤 남은 이전 running attempt, queued/retry_wait 상태, 만료 lease를 현재 진행으로 표시하지 않는다. run=running인데 현재 점유를 확인할 수 없을 때 `실행 상태 확인 필요`와 단계 미확정/복구 안내를 제공하고 기존 attempt는 기술 이력으로 남긴다. 정상 queued/retry_wait는 각각 대기/자동 재시도 대기로 표시한다. 성공한 과거 attempt의 유효 결과는 기존 정책대로 보존한다. claim/lease token은 DTO에 노출하지 않는다. retry_wait는 실제 retry_at을 표시하고 시간이 지났다고 실행 중으로 추정하지 않는다.
5. 실행 updated_at은 기록 변경 시각이다. heartbeat/마지막 UI 상태 조회 시각으로 바꾸어 부르지 않는다. UI의 `마지막 확인`은 해당 상태 API 성공 시각이며 작업의 실제 단계 시각과 구분한다.
6. 상태 DTO에는 원자료 점수·판정·관찰 문장·provider 원문·프롬프트·output 경로를 추가하지 않는다. 기존 원자료의 명시 열람/출처 기록과 분리한다.
7. `GET /api/cases/{case_id}/sessions/{session_id}/runs-s1/by-request/{request_id}`를 신설해 인증 actor가 처음 생성한 해당 case/session/request_id의 접수 실행만 읽는다. 현재 선택 회차·활성 설정·재사용 선택이 바뀌어도 당시 접수 조회는 가능해야 하며 현재 입력의 재실행 검사를 적용하지 않는다. 응답은 `found`와 발견 시 run_id/기존 상태 DTO다. `found=false`는 ‘현재 조회에서 아직 찾지 못함’이며 요청이 영구 미접수라는 증거가 아니다. 조회 실패/처리중 요청과 확정 거절을 구분하고, 접수 확인을 위해 재POST하거나 새 실행을 자동 생성하지 않는다. 일반 공유 실행 조회/제어 권한은 유지한다.

근거: [고정 요청자/중복 판정](../../../backend/app/run_v4.py#L133), [실행 view](../../../backend/app/run_v4.py#L198), [계획 단계](../../../backend/app/scoring_ai_v4.py#L130), [종료 상태](../../../backend/app/run_v4.py#L231), [현재 점유](../../../backend/app/analysis.py#L82), [step의 claim](../../../backend/app/worker.py#L107), [DTO](../../../backend/app/domain/runs_v4.py#L118).

## 3 기본 카드와 상태 우선순위

```text
AI 분석
합성 대상 A · 1회차 · 내가 시작한 이번 실행
실행 중 · 항목군 관찰
항목군: 완료 N / 예정 M · 실패 K

항목군 관찰 [실행 중]
기본 계산   [대기]
애착 판단   [대기]
결과 게시   [대기]
시작: 서버 기록 시각 · 마지막 확인: 조회 성공 시각
[상태 새로고침] [중지]
```

- 클릭 직후 `분석 요청 중`을 표시한다. 생성 응답의 run_id를 선택하고 이후 그 실행을 추적한다. 생성 응답 유실 시 기존 pending request_id를 유지하고 위 읽기 전용 resolver로 접수 여부를 확인한다. 아직 찾지 못하면 `요청 접수 여부 확인 중`으로 재조회하며 재POST/새 실행을 자동 만들지 않는다. 확정 요청 거절 시 그 사유와 현재 조건을 다시 확인할 경로를 표시한다.
- 새로고침/재진입 시 계정·대상·회차에 연결한 선택 run_id를 다시 조회한다. 저장된 선택이 없으면 현재 계정이 처음 생성한 가장 최근 run을 기본 선택한다. 기존 공유 실행 기록은 별도로 유지하며 사용자가 명시 선택하면 해당 실행자를 표시한다. 선택 실행 없음/조회 중/통신 오류를 정상 준비 상태와 구분한다.
- 이전 성공 run의 존재로 현재 실행의 상단 상태를 덮지 않는다. 이전 결과가 있으면 `이전 분석 결과 있음`으로 별도 표시하고, 현재 실행의 완료 표시와 섞지 않는다.

| 서버 상태 | 기본 표시/행동 |
| --- | --- |
| queued | 분석 대기. 실제 접수된 AI run의 대기이며 전처리에는 없는 상태 |
| running | 분석 중 + 현재 실제 단계/항목군 요약 |
| retry_wait | 자동 재시도 대기 + 기록된 예정 시각/사유 |
| stopped | 중지됨. 과거 running step은 이력, 허용된 재시도 경로 표시 |
| succeeded | 분석 완료. 결과 게시 완료를 확인 |
| partial_failed | 일부 완료 · 확인 필요. 게시된 유효 원자료와 실패/보류 부분을 구분 |
| failed / settings_required | 분석 실패 / 설정 확인 필요. 사유와 실제 허용된 재시도/설정 경로 |

`중지 요청 중`은 클라이언트 제어 POST가 진행 중인 표시다. 현행 서버 action은 즉시 stopped로 전환하므로 별도 stop_requested 서버 상태/중지 대기 파이프라인을 추가하지 않는다. 중지 응답/조회 확인 뒤 stopped를 표시하며 응답 유실은 상태 조회로 확인한다.

이전 입력/설정 적합성 배지는 실행 상태와 별도로 표시한다. 일부 완료는 기존 정책대로 성공 항목군을 명시 재사용한 **새 실행** 경로를 제공하고, 같은 run retry로 바꾸지 않는다. failed/stopped/settings_required의 기존 고정 입력 재시도와 실제 사유/updated_at 충돌 검사는 유지한다.

## 4 조회·문맥·요청 복구

- 최초 로딩, POST 제출/제어 요청 중, 배경 상태 조회를 나눈다. 2초 배경 조회만으로 버튼/입력 영역이 깜빡이거나 반복 잠기지 않게 한다. 허용 상태와 요청 중 여부로 중복 제어를 막는다.
- active 상태의 2초 조회는 일시적 실패에도 계속 예약한다. 연결 실패 시 마지막 상태·마지막 확인 시각·연결 안내를 유지하고 간격을 제한해 자동 복구한다. 필요한 readiness/preprocess 조회 실패를 ‘설정 비활성/전처리 없음’으로 단정하지 않는다.
- 종료 후 정기 조회를 멈추고 탭 재노출/화면 복귀/수동 조회에서 최신 상태를 읽는다. 최신 정보 검증 전 실행 버튼은 조회 확인 상태로 둔다. 메뉴 조회는 자동 생성/재시도/공급자 호출을 하지 않는다.
- 경로·회차·입력판·계정이 바뀌면 이전 조회/POST/타이머의 응답을 적용하지 않는다. 로그아웃/계정 전환 때 선택 run/pending request/표시 데이터를 정리한다. 같은 path에서 입력판만 바뀌어도 이전 응답이 준비 상태를 덮지 않게 한다.
- 같은 run_id 안에서도 start/stop/retry 응답 적용과 그 뒤의 제어 결과를 확인하는 재조회는 generation/sequence를 갱신해 앞선 배경 조회를 무효화한다. 오래된 running 조회가 완료/중지 확인 뒤 도착해 상태를 되돌리지 않게 한다. 같은 run의 명시 retry로 queued가 된 경우는 새 제어 generation의 응답으로 적용하며 ‘종료는 영구 고정’ 같은 단순 우선순위로 막지 않는다.
- 단계 기록/현재 claim을 확인할 수 없으면 `단계 확인 중` 또는 위의 `실행 상태 확인 필요` 안내를 유지한다. `항목군 관찰 중`은 유효한 현재 claim의 score_v4 step이 확인된 공급자 응답 대기일 때만 표시한다. ‘업로드 30%/AI 추론 80%’처럼 확인할 수 없는 내부 진행을 만들지 않는다.
- 기술 정보는 접기 안에 유지하되 상태·단계·부분 완료 사유·조회 오류/복구·다음 행동은 밖에 둔다. 내부 failure code는 사용자 안내와 별도로 상세에서 보존한다.

## 5 변경 위치

| 파일 | 변경 |
| --- | --- |
| `backend/app/domain/runs_v4.py` | 실행/예정 단계 진행 요약 DTO |
| `backend/app/run_v4.py` | 고정 config와 최신 attempt 기반 view projection; 기존 상태/원자료/감사 보존 |
| `backend/app/api.py` | 현재 actor/case/session/request_id의 읽기 전용 접수 resolver와 API 시험 연결 |
| `backend/app/scoring_ai_v4.py` | 기존 계획 생성 함수를 재사용할 필요가 있는 호출만 연결; 채점/공급자 정책 변경 없음 |
| `frontend/src/aiTypesV4.ts`, `AiRunsV4.tsx` | DTO 타입, 선택 실행 카드·단계·상태 우선순위·요청/조회 복구 |
| `frontend/src/ScoreSheetsV4.tsx` | 실제 user 문맥을 AI 컴포넌트에 전달하는 최소 변경 |
| `backend/tests/test_run_progress_v4.py`, `test_ai_api_v4.py` | 단계 projection·attempt/claim/lease·부분 결과·중지/대기·접수 resolver·민감 결과 제외 |
| `frontend/tests/analysis-status-v4.spec.ts` | 신설: 시작~종료·요약 우선순위·실패 복구·계정/대상 전환 |
| 기존 AI API/run/frontend 회귀 | 중복 요청·고정 입력·중지/재시도·명시 재사용·공유 접근 유지 |

view/plan/current run 변경 전에 Graft callers로 API·Worker·테스트 호출 관계를 확인한다. 실제 worker lease/claim/예산·중지 요청·요청자 활성 상태 검사를 우회하지 않는다. 별도 background pipeline이나 UI 전용 AI 결과를 만들지 않는다.

## 6 인수 기준과 검증

- [x] ES-T13: queued→score→calculate→attachment→publish→succeeded 전이가 접기 밖에서 보인다. 새 요청중/서버 대기를 구별하고 예정 단계가 아직 없는 상황도 표시한다.
- [x] ES-T14: 과거 성공 + 현재 queued/running, partial_failed + result_available, stopped/failed + 과거 running attempt에서 현재 요약/행동이 정확하다. succeeded 없이 완료를 표시하지 않는다.
- [x] ES-T15: retry_wait/retry_at·재사용·다중 attempt·미생성/보류 단계가 개수를 중복 증가시키지 않는다. queued/중지/lease 만료/새 claim 전후에 이전 running step이 현재 단계가 되지 않으며 현재 claim·유효 lease의 step만 진행으로 표시한다. 일부 완료의 새 실행과 고정 입력 retry 경로가 다르다. 상태 DTO에 원자료/판정/원문/프롬프트/output 경로/claim token이 없다.
- [x] ES-T16: 느린 POST·응답유실·중복 클릭·503/네트워크 단절·복구·새로고침/탭 재진입에서 동일 요청은 실행 1건이며 자동 새 실행/공급자 호출이 없다. 응답 유실 뒤 설정 비활성화/선택 회차/재사용 선택이 바뀌어도 읽기 전용 resolver가 최초 접수를 찾는다. 일시적 미발견/조회 실패를 확정 미접수 또는 설정/전처리 부족으로 둔갑시키지 않는다.
- [x] ES-T17: 대상/회차/입력판/계정 전환 중 늦은 응답, 클라이언트 중지 요청중→서버 stopped, 제어 충돌, background poll 중 버튼 안정성, 로그아웃 후 타이머/선택 run 정리를 검증한다. 같은 run의 running 조회를 지연시킨 뒤 완료/중지를 확인하고 옛 조회를 반환해도 상태가 되돌아가지 않는다. 명시 retry 뒤 새 queued는 정상 반영된다. 공유 이력·다른 직원의 기존 허용된 실행 제어도 유지한다.
- [x] ES-T18: 1366/390px에서 단계·현재 상태·원인·다음 행동을 쉽게 읽고, 상태 변경만 적절히 낭독한다. 실제 종료 후 활성 정기 조회가 멈추고 중지/재시도 버튼 허용 상태가 서버와 일치한다.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest tests.test_run_v4 tests.test_ai_api_v4 tests.test_run_progress_v4 -v
# frontend/
npm run build
npm run test:e2e -- tests/analysis-status-v4.spec.ts tests/scoring-ai-v4.spec.ts tests/business-access-v4.spec.ts tests/context.spec.ts
# repository root
git diff --check
```

fake provider/제어된 응답과 임시 합성 저장소로 전이를 재현하고 상태 조회의 부작용 없음과 실제 외부 호출 0건을 기록한다. 위 체크/명령은 아직 실행하지 않았다. 마지막 PR에서는 앞선 ES01/ES02 인수와 변경 범위의 종단 화면 흐름을 함께 확인하며 실공급자 품질/시간 인수와 구분한다.

## 7 MP01 인계 — 2026-10-12 진행 순서 조정

[전체 계획 §4.1](K-DOG_내실행과분석진행표시계획_v1.0_20261012.md#41-mp-계획과-통합-진행-순서--2026-10-12-후속-결정)에 따라 ES01~03 구현·검증·수용 수정·병합 후 [MP01](../360통합MP4업로드_20261012/K-DOG_PR-MP01_외부처리MP4계약과보관_v1.0_20261012.md)을 시작한다. 실행 기록에 적용 commit, 실제 전처리 실행/접수 조회 API·DTO와 단계 이벤트 연결 방식, `_history`/guard 보호, 입력 변경 시 outdated와 과거 결과 조회, ES02 문맥/generation 보호, ES 회귀 시험 경로를 적어 인계한다. MP용 새 종류/metadata는 ES 단계에서 미리 구현하지 않는다. MP03에서 새 파일·metadata 정정·부분 가용성과 이 계약의 조합을 확인한다.

## 8 구현 실행 기록 — 2026-10-12

- 선행 ES02: [PR #88](https://github.com/syleeVeluga/k-dog-proj/pull/88), 구현 `8d8205c`, 원격/로컬 main 병합 `7d39c1e`. 이 commit에서 `veluga/es03-analysis-progress`를 시작했다.
- 실행 DTO에 원래 requested_by/created_at/retry_at, 고정 config의 예정 stage/key 진행 요약 및 현재 활성 설정 적합성을 추가했다. 최신 유효 attempt만 집계하며 현재 run claim·live lease와 일치하는 running step만 현재 단계로 표시한다. 이전 attempt/abandoned/superseded는 기술 이력에 남는다. 상태 조회에 output refs·claim/lease token·점수·프롬프트·provider 원문을 추가하지 않았다.
- actor/case/session/request_id의 읽기 전용 resolver를 추가했다. 현재 회차/입력/활성 설정과 실행 접수 조건이 바뀌어도 최초 actor의 접수 조회는 가능하며 found=false를 영구 미접수로 취급하지 않는다. 기존 공유 상태 조회/중지/재시도 권한을 유지한다.
- AI 분석 시작 직후 요청중, 응답 유실 시 pending request 보존·resolver 조회만 수행한다. 선택 run_id는 계정/대상/회차 세션 범위에 보존하고 기본 선택은 최초 requested_by가 현재 계정인 최신 실행이다. 이전 성공/부분 게시를 현재 실행 완료와 섞지 않고 예정4단계·실제 단계·조회 시각을 접기 밖에 표시한다.
- 반복 조회 오류에서 last state/readiness를 보존하고 자동 재조회한다. 최초/제어/배경 조회를 분리하고 제어 응답 generation으로 오래된 running 응답을 무효화한다. 중지 뒤 명시 retry의 queued 전이는 정상 반영한다. 로그아웃/문맥 변경의 늦은 생성 응답은 버린다.
- Backend 기존 run/API18개+최초 progress4개 합계22개 통과(74.084초). 설정/회차 변경 뒤 actor resolver API1개 통과(2.110초). 최종 progress5개 통과(1.777초), 원래 요청자는 후속 retry actor로 바뀌지 않음을 검증했다. fake provider와 합성 저장소만 사용했으며 실제 외부 AI 호출0건.
- Front build 통과. 신규 analysis-status6개+기존 진행4개/채점1개 합계11개 통과(55.4초). 기존 AI 설정/공통 실행/공유 시트3개+업무권한1개/회차context1개 합계5개 통과(24.1초). 제어된 응답으로 단계 전이·부분 게시·만료 점유·반복503·응답 유실/미발견·설정 변경·계정 전환·중지/재시도 generation을 검증했다.
- 합성 진행 화면 [1366px](evidence/ES03_analysis-progress-1366.png), [390px](evidence/ES03_analysis-progress-390.png)에서 단계·상태·제어 및 가로 넘침을 확인했다. 합성 UI/가짜 공급자 시험은 실영상/실공급자 품질·시간 인수를 대신하지 않는다.
- 의존성 검증은 같은 날 ES01/ES02의 공식 registry·release·API 확인을 재사용한다: FastAPI 최신0.143.0/선택0.141.1, Pydantic 최신2.14.1/선택2.13.5, React/react-dom 최신19.3.0/선택19.2.8, Playwright 최신1.64.0/선택1.63.0, Vite 최신8.3.4/선택8.2.2, TypeScript 최신/선택7.0.2. 기존 Python3.14/Node24.13 잠금 조합을 유지하고 관련 없는 업그레이드/새 패키지는 없다. 출처와 선택 이유는 [ES01 실행 기록](K-DOG_PR-ES01_전처리내실행조회와진행계약_v1.0_20261012.md#6-구현-실행-기록--2026-10-12), [ES02 실행 기록](K-DOG_PR-ES02_전처리내작업화면과자동갱신_v1.0_20261012.md#6-구현-실행-기록--2026-10-12)를 따른다.
- 독립 cold review·수용 판단·재검증·최종 병합 근거는 아래에 추가한다.

- 독립 cold review 수용2건: P1 새 요청 접수 미확인 중 이전 실행 제어가 pending ID를 지움 → 접수 확인 중 stop/retry 잠금; P2 동일회차 입력판 변경 뒤 중지 요청중 표시 고착 → 문맥 effect에서 control 초기화. 수정 전 reviewer가 합성 UI로 두 조건을 직접 재현했다. 수정/재현 시험 후 독립 재검토에서 모두 해결·잔존 actionable0건 확인. 보류/거절0건.
- 최종 build 및 analysis-status7개+기존AI/공통5개 합계12개 통과(1.0분). 서버 progress/API8개 통과(25.965초), 기술 attempt 이력은 기존 created_at/attempt 순서를 유지하며 projection은 attempt/rowid 최신을 별도로 선택한다.
- ES01~03 통합 회귀: backend 실제 실행 actor5개+전처리 실행조회11개, 합계16개 통과(45.105초). 브라우저 전처리 신규9개/기존2개+context1개, 합계12개 통과(1.3분). ES-T13~18 완료. 모든 조회/화면 시험은 합성·가짜 공급자이며 실공급자 호출0건이다.

### MP01 구현 인계

- ES01 실행 식별은 기존 batch_id이며 시작 actor와 case/session/batch/claim/request를 대조한다. `GET /api/preprocess-s1/executions`는 현재 actor, 필터 적용 후50개, rowid cursor, request_id 접수 조회를 지원한다. 지정 상세는 `/api/cases/{case_id}/sessions/{session_id}/preprocess-s1/executions/{execution_id}`다.
- 기존 `_history`는 started/completed/failed만 읽어 guard/idempotency 판단에 progress가 섞이지 않는다. 새 `preprocess_v4.progress`는 clips/windows/verify_save 또는 reuse_verify/verify_save 경계만 기록한다. 조회는 원장·입력·실제 열람 기록을 쓰지 않는다.
- 선택 전처리의 원본/input/result/clip hash를 검증하고 이전 성공/partial과 현재 input/rules outdated를 분리한다. ES02의 pinSession은 다른 직원의 새 현재회차에도 지정 실행을 유지한다. 명시 새 대상 선택은 pin을 해제한다. 세션 저장 키는 actor/case/session 및 explicit execution으로 분리된다.
- ES03 AI 진행은 고정 config의4단계/key와 최신 유효attempt를 projection하며 live run claim/lease가 맞는 running step만 현재단계다. 원래 requested_by와 실제 retry actor 이력은 구분한다. 읽기 전용 by-request resolver는 당시 actor/case/session/request에 한정하며 새 입력/활성설정으로 접수 검사를 다시 하지 않는다.
- ES02/03은 sequence/generation으로 문맥·POST/제어 확정 응답 이전의 늦은 조회를 버린다. 응답 유실은 pending ID resolver로만 확인하고 새 요청을 자동 생성하지 않는다. 종료·문맥 폐기·로그아웃에서 예약/세션 데이터를 정리한다.
- 회귀 경로: backend `test_preprocess_execution_v4`, `test_preprocess_v4`, `test_preprocess_api_v4`, `test_run_progress_v4`, `test_run_v4`, `test_ai_api_v4`, `test_execution_actor_v4`; frontend `preprocess-executions-v4`, `preprocess-v4`, `analysis-status-v4`, `analysis-progress-v4`, `scoring-ai-v4`, `context`, `business-access-v4`. MP는 이 계약에 새 출처/metadata만 연결하며 VM-ES-T01~04에서 조합 인수를 확인한다.
- 문서 QA: 계획 폴더의 로컬 상대 링크68개 존재 확인, git diff --check 통과. Graft wiring graph 갱신 후 check 동기화 OK. 실제 PR/commit은 아래에 추가한다.
- 적용 PR: [PR #89](https://github.com/syleeVeluga/k-dog-proj/pull/89), 구현 commit0a8b03e. 이 PR의 최종 head/원격 병합/merge commit은 GitHub PR 기록을 따른다. 코드 변경 뒤 수행한 최종 검증·독립 재검토 근거는 위 기록과 같다.
