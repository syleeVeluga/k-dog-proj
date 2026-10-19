# PR-AC02 실행 추적 통합

버전: v1.0 · 2026-10-20 · 상태: **구현·국소 검증·독립 검토 완료** · 기준: `bdc526f` · 직접 선행: 없음 · 권장 순서: AC01 다음

브랜치 제안: `veluga/ac02-execution-tracking` · 제목 제안: `refactor: share AI and preprocessing execution tracking`

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 요구 AC-R03~R05·R11·R12.

## 1 문제와 완료 결과

AI 분석과 전처리 화면이 각각 pending 요청·선택 실행·응답 순서·제어 세대·poll 타이머·재진입 복구를 구현한다. 사용자가 알아야 할 동작은 기존대로 유지하면서 시간 규칙을 하나의 module에서 관리한다. 두 화면은 실행 내용과 표시를 담당하고 서로 다른 요청/조회 응답을 각 adapter에서 해석한다.

완료 조건은 **두 화면이 실제로 같은 module을 사용**하고, 응답 유실이나 문맥 전환에서 중복 실행·오래된 상태 적용이 없다는 것이다. 타이머만 추출하고 pending·제어 응답 순서가 그대로 중복되면 완료가 아니다.

## 2 파일별 변경 계획

| 파일 | 작업 |
| --- | --- |
| `frontend/src/useExecutionTracking.ts` (신설 예정) | pending·선택 식별자 보존, poll/제어 세대, 요청 수명·visibility·정리의 implementation. 내부 순수 동작도 우선 같은 파일에 둠 |
| [AiRunsV4.tsx](../../../frontend/src/AiRunsV4.tsx#L15) | 기존 15~100행 추적 책임을 새 module에 연결; readiness·전처리 준비·AI 목록·명시 제어 해석은 AI adapter |
| [PreprocessingPanelV4.tsx](../../../frontend/src/PreprocessingPanelV4.tsx#L28) | 기존 28~108·120~147행 추적 책임을 연결; 지정 실행/공유 최신 결과·카메라/오디오 설정·재사용 판정은 전처리 adapter |
| [analysis-status-v4.spec.ts](../../../frontend/tests/analysis-status-v4.spec.ts), [preprocess-executions-v4.spec.ts](../../../frontend/tests/preprocess-executions-v4.spec.ts) | 실제 두 화면을 통한 회복·지연·계정/입력판 변경·타이머 정리 회귀 유지/보완 |
| `frontend/tests/execution-tracking.spec.ts` (필요 시 신설) | 위 종단 시험에서 분리해야 할 공통 상태 전이 사례만 추가; module 내부 ref 값을 시험하지 않음 |
| [ScoreSheetsV4.tsx](../../../frontend/src/ScoreSheetsV4.tsx#L52), [pages/Preprocessing.tsx](../../../frontend/src/pages/Preprocessing.tsx#L22) | 기본은 변경 없음. 기존 key의 재생성 효과가 새 module과 일치하는지 확인 |

`ReportRunsV4.tsx`·`PreprocessExecutionsV4.tsx` 목록의 상태 관리·서버 실행 계약은 범위 밖이다. 리포트는 pending 복구 형태가 다르므로 같은 PR에 억지로 편입하지 않는다. 공통 HTTP module `api.ts`와 접근 만료 판정 `accessLost`를 재사용한다.

## 3 interface 설계 방향

새 module의 interface는 **문맥, 저장 위치, 업무 adapter**를 받고 **현재 추적 상태와 새로고침/명시 요청/선택 동작**을 제공한다. 구체적인 TypeScript 타입은 두 호출자의 실제 입력으로 도출하되 다음 책임 배치를 만족해야 한다.

| 공통 module이 소유 | 각 업무 adapter/화면이 소유 |
| --- | --- |
| 한 문맥에서 유효한 poll·제어 세대, 늦은 응답 배제 | AI/전처리의 요청·응답 DTO와 URL |
| pending 원요청과 선택 식별자의 수명·sessionStorage 반영 시점 | 각 저장 payload의 현재 key/직렬화 형식 읽기·쓰기 |
| 명시 요청 전 pending 내구 저장, 응답 유실 후 조회 복구 순서 | 접수 조회 결과의 found/not found 및 accepted 실행 식별자 해석 |
| 단일 예약 타이머, background 중복 방지, visibility·unmount 정리 | 업무 상태별 poll 지속 여부, 준비/재사용/버튼 가능 여부 |
| 제어 응답 수용 시 이전 poll 무효화 | 화면에 반영할 목록·상세·부분 성공·오류 메시지 |
| 문맥 소멸 후 state·storage 변경 차단 | 저장/완료 후 기존 상위 refresh와 사용자 안내 |

업무 adapter는 기존 HTTP를 사용하고 시험은 현재 Playwright route fixture로 응답을 제어한다. 새 네트워크 라이브러리나 server-state framework, 가상 실행 상태 enum을 도입하지 않는다. `onBeforeX/onAfterX` callback을 늘려 기존 순서를 다시 화면에 노출하는 설계는 피한다. 시작·제어·조회에서 발생한 결과를 module이 수용할 수 있게 adapter의 결과만 정규화한다.

선택 조회가 여러 요청을 병렬 수행하는 경우, AI의 `Promise.allSettled` 부분 결과 보존과 전처리의 공유 준비 상태/지정 실행 구분은 각 adapter에 남긴다. 하나의 요청 성공을 전체 연결 성공으로 바꾸지 않는다. 전체 접근 상실 여부도 adapter가 현재 요청별 의미에 따라 판정하며, 공통 module이 개별 응답의 `accessLost`만으로 전체 정리를 실행하지 않는다. 전처리는 공유 준비 상태 조회가 403/404여도 지정 실행 상세가 성공하면 그 상세를 보존하고, 연결 실패·실행 차단·기존 오류 안내를 유지한다. 지정 상세의 접근 실패는 현재 catch 경로에 따라 정리한다.

## 4 문맥·복구 계약

| 사건 | 유지할 동작 |
| --- | --- |
| username/case/session 변경 | 이전 async 결과·저장 쓰기·예약 타이머를 무효화하고 새 문맥을 초기화 |
| 전처리 지정 execution_id 변경 | 기존 React key 재생성과 동일하게 추적 대상을 전환; 현재 입력 결과와 혼동 금지 |
| 같은 회차 input_revision 변경 | 이전 제어/조회 응답을 새 readiness에 적용하지 않음. 원래 pending 요청의 expected_revision을 새 값으로 고쳐 재전송하지 않음 |
| 새 실행 버튼 | 기존 요청 DTO·request_id 생성 후 pending을 저장하고 한 번 POST; 자동 재POST 없음 |
| POST 응답 유실/5xx | 같은 request_id로 접수 조회. 아직 미발견이면 pending 보존·재조회; 새 UUID나 새 POST로 복구하지 않음 |
| 명시적인 4xx 거절 | 각 화면의 현재 rejected 처리 유지. 전처리에서 이미 확인된 실행이 있으면 그 추적을 지우지 않음 |
| 제어 응답 뒤 오래된 running 조회 도착 | 제어 응답 수용이 이전 조회를 무효화해 중지/완료를 running으로 되돌리지 않음 |
| transient 조회 실패 | 각 화면의 마지막 유효 표시와 재연결 안내 유지; background 조회가 명시 제어를 잠그지 않음 |
| adapter가 판정한 전체 접근 상실 | 현재 데이터·pending·선택과 해당 저장 정보를 기존 정책대로 정리. 공유 준비 상태만 실패한 부분 결과와 구분하며, 늦은 응답으로 복원 금지 |
| 완료·메뉴 이탈·로그아웃 | 현재 상태에 따라 poll 중단, 타이머/visibility listener 정리, 늦은 finally가 새 요청 busy를 해제하지 않음 |

저장 key `kdog-ai:<username>:<case>:<session>`와 `kdog-preprocess:<username>:<case>:<session>:<execution 또는 current>`, 기존 payload 이름을 유지한다. 이미 열어 둔 브라우저의 값은 현재 방식으로 읽고 손상 JSON의 기존 fallback을 유지한다. 데이터 이관·만료 정책을 추가하지 않는다.

AI의 명시 재시도/중지/연장과 전처리의 새 생성·명시 재사용은 업무 동작이 다르다. 공통 module은 명시 요청 수명과 응답의 유효성만 다루며 재사용 선택·상한·조건을 결정하지 않는다.

## 5 구현 순서

1. 기존 두 화면의 시험을 기준 실행한다. 각 저장 key, request 복구, poll 종료·실패의 차이를 위 표에 맞춰 기록한다.
2. module을 만들고 AI 연결로 시간 규칙을 옮긴 뒤 같은 PR에서 전처리 adapter도 연결한다. 한 adapter만 있는 중간 설계를 완료 상태로 병합하지 않는다.
3. 두 화면에서 공통화된 ref·타이머·listener·storage 변경 순서를 제거한다. 업무 결과 해석·기존 오류 문구·상위 refresh는 유지한다.
4. 아래 경쟁/복구 시험을 통과시키고 기존 parent key·revision effect와 중복 초기화가 없는지 검토한다.
5. module의 interface가 늘어난 callback 목록으로 옛 구현을 재현하지 않는지 cold review와 deletion test로 확인한다.

## 6 시험과 명령

| ID | 상황 | 기대·소유 시험 |
| --- | --- | --- |
| AC-T06 | 같은 회차 revision 변경, 계정/대상/지정 실행 변경 중 늦은 POST/GET/finally | 옛 응답·오류·busy·storage 쓰기가 새 문맥에 영향 없음; 두 기존 spec |
| AC-T07 | POST 서버 접수 후 응답 유실, 일시 미발견, 화면 재진입 | 같은 요청 조회로 복원, 자동 재POST/UUID 재발급 0; 두 기존 spec |
| AC-T08 | 느린 poll 후 중지/완료 응답, background 실패/수동 갱신/visibility 겹침 | 최신 명시 응답 우선, 예약 타이머 하나, 종료 후 안정된 조회 횟수; 두 기존 spec |
| AC-T09 | 기존 sessionStorage 복원, 손상 값, 4xx, accessLost | 기존 복구·거절·정리 의미 유지, 다른 사용자 key 오염 0; 두 기존 spec |
| AC-T10 | AI readiness 실패/목록 성공, 전처리 공유 403/404 포함 실패/지정 상세 성공, 지정 상세 접근 실패, 재사용 | 공유 조회만 실패하면 지정 상세 보존·실행 차단·오류 안내, 지정 상세 접근 실패는 기존 정리. 각 화면의 부분 결과·차단·오류 의미 유지; `analysis-status-v4`·`preprocess-executions-v4`·`preprocess-v4` |

지연은 명시적으로 해제하는 Promise·route fixture를 사용한다. poll 간격이 지났다는 사실만으로 상태 검증을 통과시키지 않는다. 완료 뒤 조회 횟수 안정과 메뉴 이탈 뒤 타이머 정리를 확인한다.

```powershell
# frontend/
npm run test:e2e -- analysis-status-v4.spec.ts analysis-progress-v4.spec.ts preprocess-executions-v4.spec.ts preprocess-v4.spec.ts context.spec.ts business-access-v4.spec.ts gemini-key-fallback.spec.ts
npm run build
# 저장소 루트
git diff --check
graft check
```

새 spec을 만들면 명령에 실제 파일명을 추가한다. 필요 없는 독립 hook 시험 라이브러리는 설치하지 않는다. 기존 두 화면의 E2E는 통합 연결을 검증하므로 공통 module 시험이 생겨도 전부 삭제하지 않는다.

## 7 위험·되돌림·완료 기록

가장 큰 위험은 서로 다른 업무 결과를 하나의 상태로 뭉개거나, revision 변경과 사용자 문맥 변경을 같은 초기화로 처리하는 것이다. adapter별 불변조건과 AC-T06~T10을 모두 통과해야 한다. 실패 시 두 화면과 새 module을 같은 PR 단위로 되돌리며 저장 key/payload는 그대로 읽을 수 있어야 한다.

- [x] 두 실제 adapter 연결, pending/순서/타이머 공통 책임 확인
- [x] AC-T06~T10·관련 회귀·build와 390/1440 화면 확인
- [x] 계정/대상/회차 key 및 원 request_id·expected_revision 보존
- [x] 공식 버전 확인·cold review·수용 재검증·증거 기록

| 실행 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | `f58b21e` → `0f8445e` + 저장 예외 수정 `3b75014`·T09 시험 보강 `0e01185`; `veluga/ac02-execution-tracking`. AC01 `d9a5e7a` 및 캡처 보강 `f949d55` 위에 적용 |
| 시험 명령·건수·시간·결과 | 변경 전 §6 관련 26 passed / 2.9분. 변경 후 33 passed / 2.9분, 전처리 같은 회차 revision 추가 1 passed / 9.7초, 저장 실패/CSV 최종 국소 2 passed / 17.8초. 손상 JSON/명시409/조회 접수 보존 추가 3 passed / 21.5초. build 통과(기존 chunk 경고); 최종 390/1440 증거는 AC05 전체 E2E에 포함 |
| cold review·발견사항 조치 | 독립 검토 수용 4건: 조회 중 새 선택 보존, 새 전처리에 이전 상세 표시 방지, 접근 상실 후 늦은 POST 복원 차단, pending 저장 실패의 busy 정리. 각각 제어된 회귀 추가. 수정 후 reviewer actionable 잔여 0건 |
| 실제 module interface·계획 대비 차이 | `useExecutionTracking(context, revision, initial, adapter)` → 추적 상태·reload/request/select. 기존 key/payload 보존. query·accept·failure의 업무 결과 해석은 두 adapter. storage mutation·세대·단일 timer·정리는 hook. 기존 accessLost/늦은 POST race도 명시 AC-T09를 만족하도록 함께 수정하고 추출 회귀와 구별 |

2026-10-20 공식 확인: React/DOM 최신 19.3.1·선택 19.2.8, TypeScript 7.0.2, Vite 최신 8.3.4·선택 8.2.2, Playwright 최신 1.64.1·선택 1.63.0. 기존 Node 24.13.0·peer/engine 호환과 lock 유지. [React effect](https://react.dev/reference/react/useEffect), [Vite 지원](https://vite.dev/releases), [TypeScript](https://www.typescriptlang.org/download/), [Playwright](https://playwright.dev/docs/release-notes)와 공식 registry를 확인했다. AC05에서 통합 기록·390/1440 캡처를 연결한다.

최종 통합 근거·공식 버전·실측 한계는 [제품 실행 기록](K-DOG_아키텍처개선실행기록_v1.0_20261020.md)을 따른다.

2026-10-20 사용자 요청의 [PR별 추가 독립 cold review](K-DOG_아키텍처개선PR별ColdReview_v1.0_20261020.md) 결과와 후속 판단을 연결한다.
