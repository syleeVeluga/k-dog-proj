# PR-U01 LNB 셸과 메뉴 구조

버전: v1.0 · 2026-10-11 · 상태: 구현 완료 · 선행: 없음 · 기준: main `24411c9`

상위: [UI·UX 개편 계획](K-DOG_UIUX개편계획_v1.0_20261011.md) §4. 공통 절차는 [S1 계획 §7](../archive/개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치: `veluga/u01-lnb-shell` · PR 제목: `feat: 좌측 LNB와 상위·하위 메뉴 구조`

## 문제와 결과

상단 가로 메뉴 8~10개가 같은 수준으로 나열되어 현장 진행·분석·관리의 순서가 보이지 않고, 휴대폰에서 두 줄로 접힌다. 현재 화면은 `App.tsx`의 `page` 상태에만 있어 새로고침하면 접수로 돌아간다 (F01).

이 PR 이후:

- 1024px 이상에서 좌측 고정 LNB에 「현장 운영 / 분석·평가 / 자료 관리」 그룹과 하위 메뉴가 보인다.
- 현재 위치가 `#/recording/inbox` 같은 hash로 남아 새로고침·뒤로가기·링크 공유 후에도 같은 화면이 열린다.
- 767px 이하에서는 상단 「메뉴」 버튼으로 서랍을 연다.
- **각 화면의 내용과 동작은 바꾸지 않는다.** 하위 메뉴가 필요한 화면(촬영, 리포트)은 이 PR에서 기존 구역을 하위 경로로 나눠 보여주기만 하고, 구역 안의 개선은 U05·U06에서 한다.

## 범위와 결정

- 메뉴 정의를 `menu` 배열에서 그룹·하위 항목을 가진 트리로 바꾼다. 역할별 노출 규칙은 현행과 같다.
- hash 처리는 새 라우터 없이 `hashchange`와 `history`만 쓴다. 알 수 없는 hash나 권한 없는 경로는 역할의 첫 메뉴로 보내고 hash를 고친다.
- 메뉴 이동, `hashchange`, 브라우저 뒤로가기 모두 `mayLeave()`를 거친다. 취소하면 hash를 원래대로 되돌린다.
- 「자료 가져오기」는 「현장 운영 › 일괄 등록 (CSV·Excel)」로 옮긴다. 접수 화면 안의 「Forms 참가자·설문 함께 등록」 접기 구역은 일괄 등록 메뉴로 가는 링크 버튼으로 바꾼다 (중복 노출 제거).
- 「연구 내보내기」는 이 PR에서 위치를 옮기지 않는다 (U06).
- LNB는 `<nav aria-label="주 메뉴">`를 유지하고, 상위 그룹은 `<h2>`가 아닌 시각적 그룹 제목 + `role="group"`과 `aria-labelledby`로 묶는다. 현재 항목은 `aria-current="page"`.
- 모바일 서랍: 열 때 첫 메뉴로 포커스, Esc·바깥 클릭·메뉴 선택 시 닫고 「메뉴」 버튼으로 포커스 복귀. 열린 동안 본문 스크롤 잠금.
- 선택 참가자 맥락 바와 하단 알림 위치(2026-10-05 개선)는 본문 열 안에서 유지한다.

## 파일별 변경

| 파일 | 변경 | 내용 |
| --- | --- | --- |
| `frontend/src/App.tsx` | 수정 | 메뉴 트리, hash ↔ 화면 동기화, LNB/서랍 배치, 접수 안 Forms 구역 → 링크 |
| `frontend/src/Lnb.tsx` | 신설 | LNB와 모바일 서랍 컴포넌트 (역할별 필터, 현재 항목, 키보드 접근) |
| `frontend/src/navigation.ts` | 신설 | 메뉴 트리 정의, hash 파싱·생성, 역할별 기본 경로 |
| `frontend/src/pages/Recording.tsx` | 수정 | `inbox`/`record` 하위 경로에 따라 수신 보관함과 촬영 기록을 나눠 표시 (내용 변경 없음) |
| `frontend/src/pages/Report.tsx` | 수정 | `comparison` 하위 경로에서 비교 조건을 접기 없이 표시 |
| `frontend/src/pages/Intake.tsx` | 수정 | Forms 접기 구역 제거, 「일괄 등록으로 이동」 버튼 |
| `frontend/src/style.css` | 수정 | 2열 레이아웃, LNB, 서랍, 반응형 구간 |
| `frontend/tests/layout.spec.ts` 외 메뉴 의존 spec | 수정 | 「자료 가져오기」 → 「일괄 등록」 이름 변경 반영, 하위 메뉴 이동 경로 |
| `frontend/tests/navigation.spec.ts` | 신설 | hash 유지·새로고침·뒤로가기, 권한 없는 hash 차단, 미저장 입력 시 이동 취소, 역할별 메뉴, 360·768·1440px 서랍/LNB, 가로 넘침 0 |

## 검증과 완료 조건

- `npm run build`, 신설 `navigation.spec.ts`, `layout`·`context`·`notifications`·`guidance`·`settings` 회귀와 메뉴 이름이 바뀐 spec 통과.
- 운영자·교수/검토자·관리자로 모든 메뉴를 열어 기존 화면 텍스트가 그대로 나오는지 합성 서버에서 확인하고 스크린샷을 남긴다.
- 개발자 계정은 LNB 없이 기존 화면 그대로.
- backend 변경 없음.

## 구현 및 검증 기록

상태: 구현·검증·cold review 반영 완료 후 PR #62로 main에 병합 (2026-10-11, merge `caa68f0`). 계획 문서 PR #61도 이 병합으로 함께 들어갔다.

- [x] 구현·변경 파일 및 commit/PR 기록
  - 브랜치 `veluga/u01-lnb-shell`, commit `d0f35be`(구현)와 cold review 수용 수정 commit. PR은 계획 문서 PR #61과 함께 올린다 (#61 단독 병합은 자동 모드 분류기가 거부해 U01 PR에 계획 문서 커밋이 포함된다).
  - 신설: `frontend/src/navigation.ts`(메뉴 트리·hash 파싱), `frontend/src/Lnb.tsx`(LNB·서랍), `frontend/tests/navigation.spec.ts`, `frontend/tests/menu.ts`(시험용 메뉴 열기 도우미: 767px 이하는 「메뉴」 서랍을 먼저 연다).
  - 수정: `App.tsx`(hash↔화면 동기화, history 위치 보존, 서랍 상태), `pages/Recording.tsx`(`inbox`/`record` 분리), `pages/Report.tsx`(`issue`/`comparison` 분리, 비교 조건 접기 제거), `pages/Intake.tsx`·`pages/Survey.tsx`(Forms 접기 구역 → 「일괄 등록으로 이동」 링크), `SurveyView.tsx`(주석 문구), `style.css`, 메뉴 이름에 의존하던 e2e 19개 파일.
  - 계획과 다른 점: ① `Survey.tsx`의 Forms 구역도 링크로 바꿨다 (접수와 같은 중복 노출 제거, 계획 표에는 없던 파일). ② 촬영 `inbox` 화면의 제목을 「영상 수신·연결」로 하고 `record` 화면은 기존 「촬영」을 유지했다. ③ 서랍의 포커스 가두기는 `header`·`main`에 `inert`를 걸어 구현했다.
- [x] 라이브러리/도구 최신·선택 버전·확인일·근거 기록
  - 확인일 2026-10-11, npm registry(`npm view <pkg> dist-tags.latest`): react·react-dom 19.3.0, vite 8.3.4, typescript 7.0.2, @playwright/test 1.64.0, @types/react 19.3.0.
  - 선택: 새 패키지를 도입하지 않고 기존 잠금 버전(react 19.2.8, vite 8.2.2, typescript 7.0.2, @playwright/test 1.63.0)을 유지했다. 이유: 이 PR의 범위가 화면 구조이며, 관련 없는 일괄 업그레이드를 하지 않는 프로젝트 지침. 최신판으로의 올림은 별도 PR 후보로 남긴다.
- [x] 시험 결과와 화면 확인 기록
  - `npm run build` 통과. `navigation`(신설 12개)·`layout`(4개) 통과. 전체 e2e는 아래 「전체 e2e」 항목.
  - backend 변경 없음.
  - 화면 확인(합성 서버, 운영자): [1440px LNB](images/u01-lnb-1440-20261011.png), [820px LNB](images/u01-lnb-820-20261011.png), [390px 서랍](images/u01-drawer-390-20261011.png). 교수/검토자·관리자·개발자 메뉴 구성은 `navigation.spec.ts`가 역할별 메뉴 이름 목록으로 확인한다.
  - 시험 수정 중 발견한 사실: 접수 화면의 「참가자 등록」 접기는 목록 로드 전에는 열려 있다가 참가자가 있으면 닫힌다(`open={!cases.length}`). 목록 로드 완료를 기다리지 않는 시험은 경합한다. 시험이 로드 완료 후 상태를 확인하도록 고쳤고 화면 동작은 바꾸지 않았다.
- [x] cold review 발견사항과 수용/보류/거절·수정·재검증 기록
  - 독립 서브에이전트가 `d0f35be` diff를 검토했고, 일부는 실제 실행으로 재현했다.

  | 번호 | 심각도 | 내용 | 판단 | 조치 |
  | --- | --- | --- | --- | --- |
  | 1 | 중 | 취소한 뒤로가기가 `replaceState`로 기록 항목을 덮어써 history가 손상됨 | 수용 | `history.state.idx`로 기록 위치를 추적하고 취소 시 `history.go(차이)`로 원래 항목으로 복귀. 취소 후 다시 뒤로 가면 이전 항목이 열리는 시험 추가 |
  | 2 | 중 | 서랍이 열린 채 세션 만료·재로그인하면 서랍이 다시 열린 상태로 나타남 | 수용 | 사용자 변경 시 서랍 상태를 초기화. 시험 추가 |
  | 3 | 중 | 이동을 취소해도 서랍이 닫힘 | 수용 | `mayLeave()` 통과 후에만 서랍을 닫음. 시험 추가 |
  | 4 | 낮음~중 | `aria-controls="lnb"`가 가리키는 `id`가 없음 | 수용 | `<nav id="lnb">`. 시험에서 확인 |
  | 5 | 낮음~중 | 768~1023px에서 `.count` 블록이 좁아져 줄바꿈 | 보류 | 계획의 구간 정의에서 나온 외관 문제이며 가로 넘침은 없음. U07 문구·반응형 점검에서 처리 |
  | 6 | 낮음 | 화면 전환 시 live region·`document.title` 알림 없음 | 보류 | 계획 범위 밖. U07에서 접근성 점검 항목으로 검토 |
  | 7 | 낮음 | 뷰포트가 줄어드는 순간 한 렌더의 서랍 모달 상태 | 거절 | 포커스가 한 번 body로 가는 정도의 일시 현상이며 실사용 경로가 아님 |
  | 8 | 낮음 | 1440px에서 헤더와 셸 정렬 어긋남 | 수용 | 셸 최대 폭과 헤더 좌우 여백을 맞춤 (CSS 한 줄씩) |
  | 9 | 낮음 | 767~768 소수 폭의 경계 불일치 | 거절 | 실결함 아님 (소수 폭 확대 배율에서만 가능) |

  - 시험 공백 지적(수동 hash 편집·앞으로가기 취소, 서랍 취소 후 상태, 세션 만료 재로그인, 취소 뒤 history 무결성) 중 1~3에 해당하는 것은 시험을 추가했다. 수동 hash 편집과 앞으로가기 취소는 같은 핸들러 경로이므로 별도 시험을 두지 않는다.
  - 재검증: `navigation`·`layout` 12개 통과.
- [x] 전체 e2e (cold review 수정 후): 55개 통과 (3.7분, 합성 서버, 외부 호출 없음). `git diff --check`, `graft build` → `graft check` OK, 문서 상대 링크 확인.
