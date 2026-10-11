# PR-U08 교수 리포트 열람과 열람 기록

버전: v1.0 · 2026-10-11 · 상태: 구현·검증 완료 · 선행: U06(Q03 철회 기록), U07 · 기준: main `d6dd58a`

상위: [UI·UX 개편 계획](K-DOG_UIUX개편계획_v1.0_20261011.md) §5 Q03·§6. 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치: `veluga/u08-professor-report-access` · PR 제목: `feat: 교수 리포트 발급·열람 허용과 리포트 열람 기록`

## 문제와 결과

U06에서 교수/검토자(`reviewer`)에게 리포트 「조회만」 여는 시도는 철회됐다. 리포트 경로가 `opinions_v4.context` → `sheets_v4.manager()`(운영자·관리자 전용)와 `report_runs_v4._actor`(운영자·관리자 전용)를 거쳐 교수의 모든 요청이 403이 됐기 때문이다 ([U06 결정 기록](K-DOG_PR-U06_분석단계진행현황과교수화면_v1.0_20261011.md)).

이 PR 이후:

- 교수(활성 `reviewer` 계정)는 운영자와 같은 **리포트 발급 메뉴** 기능을 쓴다: 발급 이력 목록, 발급본 열기·HTML/PDF/manifest 저장·인쇄, 리포트 화면에 필요한 최종 결과 조회와 본인 제출 시트로 하는 최종 해석 명시 공개, 리포트 생성·중지·재시도, 리포트 화면의 고정 자체 비교·외부 비교 선택.
- 리포트 실행마다 **누가 언제 생성·발급·중지·재시도·열람했는지**를 「열람·수정 기록」 접기로 보여 준다. 열람(HTML·PDF 본문 내려받기·새 창·미리보기)은 `report.s1.open`으로 새로 기록한다.
- 운영자 전용 권한은 넓히지 않는다: 평가자 배정·공개 허용(grant)·재개방, 최종 결과 작성, 의견 작성, 접수 쓰기, 집단 비교 구성(후보·생성), 비교 조건·연구 내보내기 메뉴, 직원 계정·백업은 그대로다.

## 결정 기록

- 2026-10-11 사용자 결정(원문): 「권한은 체계는 불필요 그냥 누가 열거나 수정했는지 기록정도만 있어도 문제 없음」
- 해석: 교수용 별도 공개 절차·권한 체계를 만들지 않는다. 교수에게 운영자와 같은 리포트 메뉴 기능을 열고, 누가 열고 바꿨는지 기록과 화면 표시만 더한다.
- `sheets_v4.manager`를 바꾸지 않는다(배정·공개·재개방 등 운영 권한까지 열리므로). 대신 리포트 범위 읽기 검사 `opinions_v4.report_reader`를 새로 두고 `context(..., read=True)`로 읽기 경로에만 쓴다.
- (cold review 후 2026-10-11 추가 결정 「바로 열람, 채점 중엔 차단」) **발급본 열람(목록·HTML/PDF/manifest·중지·재시도)**: 활성 교수는 본인 시트·공개(grant)·해석 공개 절차 없이 바로 연다(`report_runs_v4._source_access(issued_open=True)` → `opinions_v4.pinned_basic`로 고정 판본 무결성만 확인, `selected_basic`의 본인/공개 시트 분기와 `disclosures_v4.require`는 교수에게 생략). 단 그 교수에게 같은 참가자·회차의 **미제출 독립(`independent`·`draft`·활성) 시트**가 있으면 403 「독립 채점을 제출하기 전에는 리포트를 열 수 없습니다」. 동의·고정 pin·hash 검사와 기록은 그대로. 운영자·관리자의 열람 규칙과 채점 시트·최종 결과의 독립성 규칙은 바꾸지 않는다.
- **리포트 생성**은 기존 규칙을 유지한다: 생성은 최종 결과 조회(`final_results_v4.view`)·프로필 작성·`selected_basic`을 거치므로 교수도 운영자처럼 본인 원자료이거나 본인 제출 시트로 공개한 최종 해석으로만 만든다(생성 경로까지 완화하면 최종 결과 조회 규칙을 바꾸게 되어 범위 밖).
- 열람 기록(`report.s1.open`): HTML·PDF는 항상, manifest(발급 요약)는 명시적으로 열거나 저장할 때(`purpose=open|save`: 「발급 요약·HTML·PDF 열기」 첫 조회·「출처 manifest 저장」)만 남긴다. 화면 갱신·인쇄 전 재조회는 기록하지 않는다(기록 폭증 방지).

## 코드 확인 (변경 전)

`graft callers`로 확인한 호출 관계:

- `report_runs_v4._actor` ← `_case`(목록·조회·생성·다운로드 공통), `check_access`(Worker가 발급자 `requested_by`의 현재 역할 재확인).
- `opinions_v4.context` ← `selected_basic`, `view`, `metadata`, `save`, `action`, `basic_candidates`, `basic_candidate`; 그리고 `final_results_v4.assemble/list_results/view`, `disclosures_v4.reveal`, `attachment_runs_v4`.
- `sheets_v4.manager` ← `sheets_v4.assign/grant/revise(재개방)`, `run_v4.enqueue/action`, `validation_data_v4._account`, `opinions_v4.context`.
- 리포트 생성·조회 중 추가 역할 검사: `comparisons_v4._account`(운영자·관리자)가 `view`(→ `for_report`)·`list_snapshots`·`public_sources`·`external_for_report`와 `external_comparisons_v4._entries/for_output/create/view/list_snapshots/public_sources`에서 쓰인다. `uploads._linked_source`(linked_reader)와 `preprocess_v4.verified_batch`(읽기)·`sheets_v4.list_sheets`는 이미 `reviewer`를 허용한다.
- 감사 기록: `report.s1.create`(enqueue)·`report.s1.issue`(Worker finish, 발급자 이름)·`report.s1.stop`/`report.s1.retry`(action)는 이미 `store.audit`로 `changes`에 남는다. 열람 기록만 없었다.

## 파일별 변경

| 파일 | 변경 | 내용 |
| --- | --- | --- |
| `backend/app/opinions_v4.py` | 수정 | `REPORT_ROLES`·`report_reader`·`pinned_basic`(고정 판본 무결성만, `selected_basic`에서 분리) 신설, `context(..., read=False)`; `selected_basic`은 `read=True`. 의견 쓰기·조회는 계속 `manager` |
| `backend/app/final_results_v4.py` | 수정 | `list_results`·`view`는 `read=True`(작성 `assemble`은 운영자 유지) |
| `backend/app/disclosures_v4.py` | 수정 | `reveal`은 `read=True`(본인 제출 시트 소유·제출 상태 검사는 그대로) |
| `backend/app/report_runs_v4.py` | 수정 | `_actor`가 `REPORT_ROLES` 허용, 교수 발급본 열람·중지·재시도는 `issued_open`(공개 절차 생략, `_scoring_block`으로 채점 중 차단), `download(purpose=)`로 manifest 명시 열람 기록, `download(..., inline=)`이 HTML·PDF 열람을 `report.s1.open`으로 기록, `access_log`·`ReportAccessV4` 신설 |
| `backend/app/comparisons_v4.py` | 수정 | `_account(reader=True)`: 스냅숏 목록·조회·출처 목록·외부 게이트만 교수 허용. 후보·생성·연구 확인·활성화는 그대로 |
| `backend/app/external_comparisons_v4.py` | 수정 | 리포트 화면의 외부 비교 선택(목록·조회·생성·출력 확인)에 `reader=True`. 근거 업로드는 관리자 유지 |
| `backend/app/api.py` | 수정 | `GET .../report-runs-s1/{run_id}/access` 추가, 파일 다운로드에 `inline` 전달, 리포트 화면이 쓰는 비교 조회(`/comparisons-s1/cohorts` 목록·조회, `sources`, `external-snapshots` 목록·조회·생성)를 `writer` → `reader`(후보·집단 생성·연구 확인·활성화·근거 업로드는 그대로) |
| `frontend/src/navigation.ts` | 수정 | `리포트 발급` 메뉴 역할에 `reviewer` 추가(비교 조건·연구 내보내기는 운영자) |
| `frontend/src/pages/Report.tsx` | 수정 | 발급 화면(`issue`)은 교수에게도 표시 |
| `frontend/src/Prerequisites.tsx` | 수정 | 리포트 선행 조건 「분석·피드백 동의 확인」에 교수용 안내 문구(빈 문구 수정) |
| `frontend/src/ReportRunsV4.tsx`, `reportTypesV4.ts` | 수정 | `manager` → 리포트 사용자(운영자·관리자·교수), 실행별 「열람·수정 기록」 접기(펼칠 때·열람/저장/미리보기 로드 뒤 다시 조회), manifest `purpose=open/save`, 교수용 「채점 중 차단」 안내 |
| `backend/tests/test_report_runs_v4.py` | 수정 | 운영자 발급 → 시트 없는 교수가 바로 열람(manifest open·HTML·PDF 기록, 갱신 재조회 미기록), 교수의 중지·재시도가 교수 이름으로 기록, 미제출 독립 시트가 있는 교수 403, 교수의 배정 403. 역할 변경 차단 시험은 `developer`로 |
| `backend/tests/test_comparisons_v4.py`, `test_comparisons_api_v4.py` | 수정 | 교수는 스냅숏 목록 허용(함수·API), 후보 조회는 거절 |
| `frontend/tests/report-v4.spec.ts` | 수정 | 공개 시험을 교수 흐름으로: 교수가 본인 제출 시트로 최종 해석 공개 → 리포트 생성 → 「열람·수정 기록」에 `reviewer · 생성 요청`, 교수의 배정 요청 403 |
| `frontend/tests/scenario-professor.spec.ts`, `navigation.spec.ts`, `analysis-progress-v4.spec.ts`, `copy-guard.spec.ts` | 수정 | 교수 메뉴에 `리포트 발급` 추가, 교수의 리포트 화면 진입, 교수 메뉴 문구 점검에 리포트 발급 포함 |

## 검증과 완료 조건

- backend 전체 시험, `npm run build`, 전체 e2e(PowerShell), `git diff --check`, `graft build` → `graft check`.
- 교수로 리포트를 만들고 열면 `changes`에 `report.s1.create`·`report.s1.issue`·`report.s1.open`(html/pdf)이 교수 이름으로 남고 화면 기록에 보인다.
- 교수는 여전히 평가자 배정·비교 조건·연구 내보내기를 할 수 없다.

## 체크리스트

- [x] 사용자 결정 원문과 해석 기록, 계획 문서 Q03·PR 목록 갱신
- [x] `graft callers`로 `_actor`·`opinions_v4.context`·`sheets_v4.manager` 호출 확인
- [x] 리포트 범위 읽기 검사 분리, 운영 권한 비확대
- [x] 열람 기록 추가와 화면 표시
- [x] backend·e2e 시험 추가·갱신
- [x] 전체 검증 결과 기록

## 실행 기록

- 2026-10-11 구현. 새 의존성 없음(라이브러리 확인 대상 없음).
- 결과: 아래 「검증 결과」 참고.

### 검증 결과

- backend 전체 시험: 690개, api 권한 수정 후 재실행에서 `test_comparisons_api_v4`의 「교수 집단 목록 403」 단언 1건만 실패(의도된 변경) → 목록 200·후보 403으로 고쳐 해당 모듈 재실행 통과. 나머지 689개 통과(skip 2). `--spec 20261002 --check` 통과.
- `npm run build` 통과.
- e2e 전체(PowerShell, `npx playwright test`): 105개 통과(4.8m). 첫 실행에서 2건 실패 → 수정 후 전부 통과:
  1. `report-v4` 교수 흐름: 리포트 화면의 `/comparisons-s1/cohorts` 요청이 API 의존성 `writer`(운영자·관리자)에서 403. 함수 수준만 고치고 엔드포인트 의존성을 놓친 것 → 리포트 화면용 비교 조회 엔드포인트를 `reader`로.
  2. `scenario-professor`: 교수가 독립 채점에서 연 P1이 리포트 메뉴에서도 선택 유지되어 「P1 리포트 열기」 버튼이 없어 시간 초과 → 시험을 선택 유지 기준으로 고치고, 교수에게 빈 칸으로 보이던 동의 안내 문구를 채움.
- `git diff --check` 통과, `graft build` → `graft check` OK.

### 남은 사항

- 교수는 발급본은 바로 열지만, 리포트 **생성**은 운영자와 같은 공개 조건을 따른다(본인 시트가 없는 참가자는 최종본을 고를 수 없음). 운영자가 발급하고 교수는 열람하는 흐름이 기본이다.
- (cold review 3) 참가자 삭제·비교 철회 정리(`purge_comparisons`·`purge_external`·삭제)는 해당 리포트 실행의 `changes` 기록(열람 기록 포함)도 지운다. 삭제 요구사항에 따른 것으로 유지한다.
- (cold review 6) 교수는 리포트 화면에서 외부 비교 스냅숏을 **생성**할 수 있다(쓰기 권한). 리포트 입력 고정용이며 연구 확인·활성화·근거 업로드는 운영자·관리자 그대로다.
- (cold review 7) 교수도 실행 목록과 「기술 정보」(단계 시간·호출 수·비용)를 본다. 사용자 결정(기록만)에 따라 그대로 둔다.
- 선행 조건 체크리스트의 「최종 결과 확정」 항목은 교수에게 여전히 보이지 않는다(U06: 교수 진행 요약에 최종·리포트 진행을 주지 않음). 필요하면 후속으로 다룬다.
- 열람 기록은 운영자 작업 기록 `changes`에 쌓이며 별도 보존 기간·내보내기는 두지 않았다.

### cold review 반영 (2026-10-11)

독립 리뷰어가 PR #71(`052fa18`)을 검토했고, 사용자가 정책을 「바로 열람, 채점 중엔 차단」으로 결정했다.

| # | 심각도 | 내용 | 판단 | 반영 |
| --- | --- | --- | --- | --- |
| 1 | 높음 | 교수는 본인 시트·공개 이력이 없으면 운영자가 발급한 리포트를 열 수 없어 결정 취지(기록만)와 어긋남 | 수용(사용자 결정) | 발급본 열람·중지·재시도는 교수에게 공개 절차 생략, 미제출 독립 시트가 있으면 403. 생성은 기존 규칙 유지(결정 기록 참고) |
| 2 | 중 | manifest 열기·저장이 기록되지 않음 | 수용 | `purpose=open/save`일 때만 기록, 갱신 재조회는 미기록 |
| 3 | 중 | 참가자 삭제·비교 철회 정리 때 열람 기록도 지워짐 | 문서만 | 삭제 요구사항에 따라 유지, 남은 사항에 기록 |
| 4 | 중 | 시험이 「운영자가 교수로 역할 변경」 형태라 실제 흐름과 다름 | 수용 | 운영자 발급 → 시트 없는 교수 열람·기록, 교수 중지·재시도 기록, 채점 중 교수 403, manifest 기록 시험 |
| 5 | 중 | 문서 설명이 최종 동작과 다름 | 수용 | 결정 기록·파일별 변경·남은 사항 갱신 |
| 6 | 낮음 | 교수가 외부 비교 스냅숏을 생성할 수 있음(쓰기) | 문서만 | 수용, 남은 사항에 쓰기 권한으로 명시 |
| 7 | 낮음 | 교수에게 실행 목록·비용 기술 정보가 보임 | 문서만 | 「기록만」 결정에 따라 유지, 남은 사항에 기록 |
| 8 | 낮음 | 열람 뒤 「열람·수정 기록」이 갱신되지 않음 | 수용 | 열기·저장·미리보기 로드 뒤 다시 조회 |
| 9 | 낮음 | 교수가 채점 중 차단을 알 수 없음 | 수용 | 리포트 화면에 교수용 안내 문구 |

재검증: backend 전체 690개 통과(skip 2), `npm run build` 통과, e2e 전체 105개 통과(PowerShell), `git diff --check`·`graft build` → `graft check` OK.

### 2026-10-11 main 병합 충돌 해결

- 사용자 지시에 따라 PR #71 → #73 순서로 병합한다. U08에 `origin/main`의 `ba0874f`를 병합했다.
- 유일한 수동 충돌은 `ReportRunsV4.tsx` 미리보기 iframe이다. main의 제목 「관찰 리포트 미리보기」와 U08의 `onLoad` 열람 기록 갱신을 함께 보존했다. 자동 병합된 시험은 main의 UUID 숨김·설문 집계 확인과 U08의 교수 리포트·기록 확인을 함께 유지한다.
- 병합 diff 추가 cold review: 화면 제목·미리보기 로드·manifest 명시 열기/저장·반복 조회 미기록·교수 생성/열람 경계 및 API 의존성을 재검토했다. 기존 독립 리뷰의 수용 수정이 보존되며 추가 수정 사항은 없다. 이번 추가 검토는 병합 담당자의 재검토로, 기존 독립 리뷰와 구분한다.
- 관련 backend 회귀: `uv run --locked python -X utf8 -m unittest tests.test_report_runs_v4 tests.test_comparisons_v4 tests.test_comparisons_api_v4 -v` 46개 통과(88.561초). 이번 병합으로 backend 코드는 바뀌지 않아 이전 전체 690개 검증에 관련 회귀를 추가했다.
- `npm run build` 통과. 기존 번들 크기 경고는 유지되며 이번 변경 범위에서 분할하지 않는다.
- 전체 브라우저 회귀 `npm run test:e2e -- --reporter=dot`: 105개 통과(5.3분). `git diff --check`·`git diff --cached --check` 통과, 충돌 인덱스 항목 없음. 브랜치 변경으로 stale이던 Graft는 `graft build` 후 `graft check` OK.
- 2026-10-11 공식 npm 레지스트리 최신 안정 버전 확인: React 19.3.0, Vite 8.3.4, Playwright 1.64.0, TypeScript 7.0.2. 선택은 기존 lock의 React 19.2.8, Vite 8.2.2, Playwright 1.63.0, TypeScript 7.0.2다. 브랜치 통합 회귀를 기존 환경에서 검증하기 위해 관련 없는 의존성 갱신은 하지 않았다. Node 24.13.0은 확인된 각 엔진 조건을 만족한다.
  출처: [React registry](https://registry.npmjs.org/react/latest), [Vite registry](https://registry.npmjs.org/vite/latest), [Playwright registry](https://registry.npmjs.org/@playwright/test/latest), [TypeScript registry](https://registry.npmjs.org/typescript/latest), [Vite 실행 조건](https://vite.dev/guide/), [Playwright 시험 CLI](https://playwright.dev/docs/test-cli).
