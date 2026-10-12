# PR-U09 접근성 이름과 중간 폭 줄바꿈

버전: v1.0 · 2026-10-11 · 상태: 구현·검증 완료 · 선행: U07, U08(PR #71 위에 쌓음)

상위: [UI·UX 개편 계획](K-DOG_UIUX개편계획_v1.0_20261011.md) §7·§8. 공통 절차는 [S1 계획 §7](../archive/개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치: `veluga/u09-aria-label-and-count-wrap` · PR 제목: `fix: 접근성 이름의 개발 코드 S1 제거와 중간 폭 집계 문구 줄바꿈`

## 문제와 결과

[U07](K-DOG_PR-U07_문구기준과통합검증_v1.0_20261011.md) §계획과 다른 점 ①은 접근 가능한 이름(aria-label)의 `S1` 표기를 시험이 의존한다는 이유로 남겨 두었다. 화면 읽기 프로그램은 이 이름을 그대로 읽으므로 「S1 촬영 기록」처럼 개발 코드가 들린다. 또 [U01](K-DOG_PR-U01_LNB셸과메뉴구조_v1.0_20261011.md) 리뷰 5번은 768–1023px(이 PR은 681–1023px로 처리)에서 머리글 집계(`.count`) 문구가 56px 고정 폭에 갇혀 「구간 확정 / 0명」이 두 줄로 쪼개진다고 기록했다.

이 PR 이후:

- `frontend/src`의 aria-label·iframe title에 단독 `S1`이 없다. 같은 요소의 대체 문구(「S1 설정 조회 중…」 등)와 오류 기본 문구도 함께 고쳤다.
- 문구 점검(`copy-guard.spec.ts`)이 화면 텍스트뿐 아니라 `main` 안 aria-label·title 값의 단독 `S1`도 잡는다(카나리 포함).
- 681–1023px에서 집계 숫자·간격을 줄이고 문구를 한 줄로 유지한다.

## 범위와 결정

- API 경로(`/settings-s1` 등), 저장 값, CSS 클래스(`basic-s1`, `scoring-s1`)는 바꾸지 않는다.
- 이름 바꾸기: 「S1 AI 실행」→「AI 실행」, `S1 실행 {run_id}`→`AI 실행 기록 {run_id 앞 8자}`, `리포트 실행 {run_id}`→`리포트 실행 기록 {run_id 앞 8자}`(cold review #5: 원시 UUID를 읽지 않게), 「공개한 S1 AI 기본 결과」→「공개한 AI 기본 결과」, 「S1 AI 설정」→「AI 설정」, 「설정할 S1 항목군」→「설정할 항목군」, 「S1 항목군 프롬프트」→「항목군 프롬프트」, 「보존 S1 설정」→「보존 AI 설정」, 「S1 기본 결과」→「기본 결과 계산」(같은 화면의 「기본 결과 선택」·「공개한 AI 기본 결과」와 겹치지 않게), 「S1 자체 집단 비교」·「S1 의견과 최종 결과」·「S1 의견 편집」·「S1 보존 최종본」·「S1 다중 카메라 전처리」·「S1 촬영 기록」·「S1 리포트 실행」·「S1 관찰 리포트 미리보기」·「S1 연구 내보내기」·「S1 평가 배정」·「내 S1 채점 시트」·「S1 영상 수신 보관함」은 `S1`만 뺐다.
- cold review #4로 보이는 `S1`도 고쳤다: 제목 「S1 관찰 원자료 AI 설정」→「관찰 원자료 AI 설정」, 버튼 「S1 설정 초안 저장」→「설정 초안 저장」·「선택한 S1 설정 활성화」→「선택한 설정 활성화」, 알림 「S1 초안을 저장했습니다…」→「설정 초안을 저장했습니다…」·「S1 관찰 원자료 설정을 활성화…」→「관찰 원자료 설정을 활성화…」, 촬영 기록 알림 「S1 촬영 기록을 확정/초안 저장했습니다」→「촬영 기록을 …」. `types.ts`의 판본 표기 「S1.1 · 10월 2일」과 코드 주석은 그대로 둔다.
- 집계 블록은 681–1023px에 적용한다. 681–767px(서랍 메뉴 구간)도 일부러 포함한다. 680px 이하는 기존 세로 배치 규칙을 그대로 쓴다.
- 문구 점검의 접근성 이름 검사는 `main` 안 aria-label·title만 본다. 패턴 `\bS1(?![-\w])`은 `S1.1`도 일부러 잡는다.

## 파일별 변경

| 파일 | 변경 | 내용 |
| --- | --- | --- |
| `frontend/src/AiRunsV4.tsx`, `AiSettingsV4.tsx`, `BasicResultsV4.tsx`, `ComparisonSettings.tsx`, `FinalResultsV4.tsx`, `PreprocessingPanelV4.tsx`, `RecordingPanelV4.tsx`, `ReportRunsV4.tsx`, `ResearchExportsV4.tsx`, `ScoreSheetsV4.tsx`, `UploadInbox.tsx` | 수정 | aria-label·title·대체 문구의 `S1` 제거 |
| `frontend/src/style.css` | 수정 | 보관함 선택자를 새 이름으로, `@media (min-width: 681px) and (max-width: 1023px)` 집계 블록 추가 |
| `frontend/tests/copy-guard.spec.ts` | 수정 | aria-label·title 점검과 카나리 |
| `frontend/tests/layout.spec.ts` | 수정 | 690·800·1000·1023px에서 접수·설문·촬영 머리글 집계 문구가 한 줄, 머리글이 화면 안, 문서 가로 넘침 없음(`scrollWidth <= innerWidth`) |
| 이름에 의존하던 e2e 16개 파일(`report-v4.spec.ts`는 합성 실행 ID 앞 8자가 겹치지 않게 `issued-synthetic-run`·`previous-synthetic-run`으로 바꿈) | 수정 | 새 이름으로 선택 |

## 구현 및 검증 기록

상태: 구현·전체 검증·cold review 반영 완료 (2026-10-11).

- [x] 구현·변경 파일 및 commit/PR 기록 — 위 표, PR #73. backend는 바꾸지 않았다.
- [x] 라이브러리/도구 — 새 의존성 없음(U01 기록과 같음).
- [x] 시험
  - 수정 전 측정: 800px 촬영 화면 「구간 확정 / 0명」이 두 줄. 수정 후 690·800·1000·1023px 모두 한 줄(새 layout 시험이 `toBe(1)`로 확인, 스크린샷은 시험 산출물).
  - 1차: `npm run build` 통과, 전체 e2e 107개 통과. cold review 반영 후: `npm run build` 통과, **전체 e2e 109개 통과**(layout 폭 2개 추가), `git diff --check`, `graft build` → `graft check` OK. backend는 변경이 없어 실행하지 않았다.
  - 반영 중 1회 실패: 실행 기록 이름을 ID 앞 8자로 줄이자 합성 ID 「synthetic-issued-run」·「synthetic-previous-run」이 같은 이름이 되어 strict mode 위반. 실제 ID는 UUID라 겹칠 가능성이 낮아 합성 ID만 바꿨다.
- [x] cold review 발견사항과 판단·반영

  | # | 심각도 | 내용 | 판단 | 반영 |
  | --- | --- | --- | --- | --- |
  | 1 | 낮음 | `.count span`의 `white-space: nowrap`이 긴 문구에서 넘칠 수 있음 | 수용(기록만) | 집계 문구는 고정된 짧은 낱말이라 유지. 새 시험이 가로 넘침을 확인 |
  | 2 | 낮음 | 문서·계획·시험 주석의 폭 표기가 768–1023px와 681–1023px로 섞임 | 수용 | 681–1023px로 통일, 681–767px 포함을 명시 |
  | 3 | 낮음 | layout 시험이 경계 폭과 문서 가로 넘침을 보지 않음 | 수용 | 690·1023px 추가, `scrollWidth <= innerWidth` 단언 |
  | 4 | 낮음 | AI 설정 제목·버튼·알림과 촬영 기록 알림에 보이는 `S1` 잔존 | 수용 | 「범위와 결정」대로 수정, `scoring-ai-v4.spec.ts` 갱신 |
  | 5 | 낮음 | 실행 카드 aria-label이 원시 UUID 전체를 읽음 | 수용 | 「AI 실행 기록·리포트 실행 기록 + ID 앞 8자」로 줄임, 시험 갱신 |
  | 6 | 정보 | 접근성 이름 검사가 `S1.1`도 잡고 범위가 `main` aria-label·title뿐 | 기록만 | 의도된 동작으로 「범위와 결정」에 적음 |

- 계획과 다른 점: 없음. 남은 후속: AI 설정 화면 안내의 「S16」(`AiSettingsV4.tsx` 50행) 등 문구 점검이 열지 않는 화면의 개발 코드.

### 2026-10-11 U08 병합 후 main 통합

- 사용자 지정 순서에 따라 PR #71을 먼저 병합한 `origin/main / 7ee28f1`을 U09에 병합했다.
- 앱 코드는 자동 병합됐다. 수동 충돌은 `report-v4.spec.ts`의 합성 실행 ID 한 줄이다. 최신 발급 ID는 main의 `'a1'.repeat(16)`을 유지하고 이전 발급 ID는 `'b2'.repeat(16)`으로 했다. main의 실제 UUID 형태 숨김 시험과 U09의 앞 8자리 실행 카드 이름 구분 시험을 함께 보존한다. 앞선 「issued-synthetic-run / previous-synthetic-run」은 당시 검증 이력이며 이번 통합 fixture로 대체한다.
- 추가 cold review는 병합 담당자의 재검토다. 기존 cold review 수용 수정과 함께, 자동 병합된 메뉴·문구·CSS 선택자·리포트 열람 기록 갱신을 확인했다. 접근성 이름/title에 단독 `S1`이 남지 않음을 Graft 전체 검색으로 확인했고, API/저장 값/backend의 main 대비 변경은 없다. 추가 제품 수정 사항은 발견하지 않았다.
- `npm run build` 통과. 라이브러리 최신 안정 버전·선택 버전·Node 호환 확인은 같은 실행 환경에서 수행한 [U08 main 병합 기록](K-DOG_PR-U08_교수리포트열람과열람기록_v1.0_20261011.md#2026-10-11-main-병합-충돌-해결)을 따른다. 의존성은 갱신하지 않았다.
- 전체 브라우저 회귀 `npm run test:e2e -- --reporter=dot`: 109개 통과(5.3분). 690·800·1000·1023px 집계·가로 넘침, 접근성 이름 점검, UUID 숨김 및 리포트·교수 흐름을 포함한다. `git diff --check`·`git diff --cached --check`, `graft build` → `graft check` 통과, 미해결 충돌 없음. main 대비 backend 변경이 없어 U08에서 완료한 backend 회귀를 다시 실행하지 않았다.
