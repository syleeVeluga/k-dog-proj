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
- 독립성·공개 규칙은 그대로다: `opinions_v4.selected_basic`의 본인 시트/공개 시트(`viewer_sheet_id`·grant) 검사와 `disclosures_v4.require`는 이미 운영자에게도 적용되며 바꾸지 않는다. 따라서 교수는 본인 원자료로 만든 결과이거나 본인 제출 시트로 공개 이력을 남긴 최종 해석만 리포트로 열 수 있다(운영자와 같은 조건).
- 열람 기록은 HTML·PDF 본문에만 남긴다. manifest(발급 요약)는 화면이 상태 갱신마다 다시 읽으므로 기록하지 않는다(기록 폭증 방지). 화면의 「발급 요약·HTML·PDF 열기」는 미리보기 HTML을 읽으므로 열람 1건이 남는다.

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
| `backend/app/opinions_v4.py` | 수정 | `REPORT_ROLES`·`report_reader` 신설, `context(..., read=False)`; `selected_basic`은 `read=True`. 의견 쓰기·조회는 계속 `manager` |
| `backend/app/final_results_v4.py` | 수정 | `list_results`·`view`는 `read=True`(작성 `assemble`은 운영자 유지) |
| `backend/app/disclosures_v4.py` | 수정 | `reveal`은 `read=True`(본인 제출 시트 소유·제출 상태 검사는 그대로) |
| `backend/app/report_runs_v4.py` | 수정 | `_actor`가 `REPORT_ROLES` 허용, `download(..., inline=)`이 HTML·PDF 열람을 `report.s1.open`으로 기록, `access_log`·`ReportAccessV4` 신설 |
| `backend/app/comparisons_v4.py` | 수정 | `_account(reader=True)`: 스냅숏 목록·조회·출처 목록·외부 게이트만 교수 허용. 후보·생성·연구 확인·활성화는 그대로 |
| `backend/app/external_comparisons_v4.py` | 수정 | 리포트 화면의 외부 비교 선택(목록·조회·생성·출력 확인)에 `reader=True`. 근거 업로드는 관리자 유지 |
| `backend/app/api.py` | 수정 | `GET .../report-runs-s1/{run_id}/access` 추가, 파일 다운로드에 `inline` 전달, 리포트 화면이 쓰는 비교 조회(`/comparisons-s1/cohorts` 목록·조회, `sources`, `external-snapshots` 목록·조회·생성)를 `writer` → `reader`(후보·집단 생성·연구 확인·활성화·근거 업로드는 그대로) |
| `frontend/src/navigation.ts` | 수정 | `리포트 발급` 메뉴 역할에 `reviewer` 추가(비교 조건·연구 내보내기는 운영자) |
| `frontend/src/pages/Report.tsx` | 수정 | 발급 화면(`issue`)은 교수에게도 표시 |
| `frontend/src/Prerequisites.tsx` | 수정 | 리포트 선행 조건 「분석·피드백 동의 확인」에 교수용 안내 문구(빈 문구 수정) |
| `frontend/src/ReportRunsV4.tsx`, `reportTypesV4.ts` | 수정 | `manager` → 리포트 사용자(운영자·관리자·교수), 실행별 「열람·수정 기록」 접기(펼칠 때 조회) |
| `backend/tests/test_report_runs_v4.py` | 수정 | 교수가 생성·발급·열람, 열람 기록, 다른 교수는 공개 없이 403, 교수의 배정 403. 역할 변경 차단 시험은 `developer`로 |
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

- 교수는 운영자처럼 `selected_basic`의 공개 조건을 따른다. 다른 평가자의 원자료로 만든 최종 결과는 운영자의 공개 허용(grant)과 본인 제출 시트가 있어야 열린다. 교수 본인 시트가 없는 참가자는 리포트 화면에서 최종본을 고를 수 없다(운영자와 같은 규칙, 사용자 결정에 따라 별도 절차 없음).
- 선행 조건 체크리스트의 「최종 결과 확정」 항목은 교수에게 여전히 보이지 않는다(U06: 교수 진행 요약에 최종·리포트 진행을 주지 않음). 필요하면 후속으로 다룬다.
- 열람 기록은 운영자 작업 기록 `changes`에 쌓이며 별도 보존 기간·내보내기는 두지 않았다.
