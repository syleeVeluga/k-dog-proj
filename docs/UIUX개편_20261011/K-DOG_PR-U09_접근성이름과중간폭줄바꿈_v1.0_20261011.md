# PR-U09 접근성 이름과 중간 폭 줄바꿈

버전: v1.0 · 2026-10-11 · 상태: 구현·검증 완료 · 선행: U07, U08(PR #71 위에 쌓음)

상위: [UI·UX 개편 계획](K-DOG_UIUX개편계획_v1.0_20261011.md) §7·§8. 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치: `veluga/u09-aria-label-and-count-wrap` · PR 제목: `fix: 접근성 이름의 개발 코드 S1 제거와 중간 폭 집계 문구 줄바꿈`

## 문제와 결과

[U07](K-DOG_PR-U07_문구기준과통합검증_v1.0_20261011.md) §계획과 다른 점 ①은 접근 가능한 이름(aria-label)의 `S1` 표기를 시험이 의존한다는 이유로 남겨 두었다. 화면 읽기 프로그램은 이 이름을 그대로 읽으므로 「S1 촬영 기록」처럼 개발 코드가 들린다. 또 [U01](K-DOG_PR-U01_LNB셸과메뉴구조_v1.0_20261011.md) 리뷰 5번은 768–1023px에서 머리글 집계(`.count`) 문구가 56px 고정 폭에 갇혀 「구간 확정 / 0명」이 두 줄로 쪼개진다고 기록했다.

이 PR 이후:

- `frontend/src`의 aria-label·iframe title에 단독 `S1`이 없다. 같은 요소의 대체 문구(「S1 설정 조회 중…」 등)와 오류 기본 문구도 함께 고쳤다.
- 문구 점검(`copy-guard.spec.ts`)이 화면 텍스트뿐 아니라 `main` 안 aria-label·title 값의 단독 `S1`도 잡는다(카나리 포함).
- 681–1023px에서 집계 숫자·간격을 줄이고 문구를 한 줄로 유지한다.

## 범위와 결정

- API 경로(`/settings-s1` 등), 저장 값, CSS 클래스(`basic-s1`, `scoring-s1`)는 바꾸지 않는다.
- 이름 바꾸기: 「S1 AI 실행」→「AI 실행」, `S1 실행 {id}`→`실행 {id}`, 「공개한 S1 AI 기본 결과」→「공개한 AI 기본 결과」, 「S1 AI 설정」→「AI 설정」, 「설정할 S1 항목군」→「설정할 항목군」, 「S1 항목군 프롬프트」→「항목군 프롬프트」, 「보존 S1 설정」→「보존 AI 설정」, 「S1 기본 결과」→「기본 결과 계산」(같은 화면의 「기본 결과 선택」·「공개한 AI 기본 결과」와 겹치지 않게), 「S1 자체 집단 비교」·「S1 의견과 최종 결과」·「S1 의견 편집」·「S1 보존 최종본」·「S1 다중 카메라 전처리」·「S1 촬영 기록」·「S1 리포트 실행」·「S1 관찰 리포트 미리보기」·「S1 연구 내보내기」·「S1 평가 배정」·「내 S1 채점 시트」·「S1 영상 수신 보관함」은 `S1`만 뺐다.
- AI 설정 화면의 보이는 버튼 「S1 설정 초안 저장」·「선택한 S1 설정 활성화」와 제목 「S1 관찰 원자료 AI 설정」, 촬영 기록 저장 알림 「S1 촬영 기록을 …」은 aria-label이 아니고 이번 범위(접근성 이름·같은 요소의 대체 문구) 밖이라 그대로 두었다. 문구 점검이 이 화면들을 열지 않아 잡히지 않는다(후속 후보).

## 파일별 변경

| 파일 | 변경 | 내용 |
| --- | --- | --- |
| `frontend/src/AiRunsV4.tsx`, `AiSettingsV4.tsx`, `BasicResultsV4.tsx`, `ComparisonSettings.tsx`, `FinalResultsV4.tsx`, `PreprocessingPanelV4.tsx`, `RecordingPanelV4.tsx`, `ReportRunsV4.tsx`, `ResearchExportsV4.tsx`, `ScoreSheetsV4.tsx`, `UploadInbox.tsx` | 수정 | aria-label·title·대체 문구의 `S1` 제거 |
| `frontend/src/style.css` | 수정 | 보관함 선택자를 새 이름으로, `@media (min-width: 681px) and (max-width: 1023px)` 집계 블록 추가 |
| `frontend/tests/copy-guard.spec.ts` | 수정 | aria-label·title 점검과 카나리 |
| `frontend/tests/layout.spec.ts` | 수정 | 800·1000px에서 접수·설문·촬영 머리글 집계 문구가 한 줄이고 머리글이 화면 안에 있음 |
| 이름에 의존하던 e2e 16개 파일 | 수정 | 새 이름으로 선택 |

## 구현 및 검증 기록

상태: 구현·전체 검증 완료 (2026-10-11).

- [x] 구현·변경 파일 및 commit/PR 기록 — 위 표. backend는 바꾸지 않았다.
- [x] 라이브러리/도구 — 새 의존성 없음(U01 기록과 같음).
- [x] 시험
  - 수정 전 측정: 800px 촬영 화면 「구간 확정 / 0명」이 두 줄. 수정 후 800·1000px 모두 한 줄(새 layout 시험이 `toBe(1)`로 확인, 스크린샷 시험 산출물).
  - `npm run build` 통과, **전체 e2e 107개 통과**, `git diff --check`, `graft build` → `graft check` OK. backend는 변경이 없어 실행하지 않았다.
- 계획과 다른 점: 없음. 남은 후속은 위 「범위와 결정」의 보이는 `S1` 버튼·제목 문구.
