# K-DOG 설문 확인 표와 촬영 이력 정리

버전: v1.0 · 2026-10-24 · S1.1

## 승인 범위

사용자는 촬영 회차의 반복 선택 제거, 회차 안내·전처리 바로가기 제거, 재촬영과 이력의 분리, 설문 원응답의 표 표시를 모두 적용하고 리뷰 → 이슈 수정 → 병합 → 로컬 배포하도록 승인했다. 추가로 제거 기능의 소스·DB 등 잔여 항목 정리를 요청했다.

기준은 `main / c4936de`, 작업 브랜치는 `veluga/survey-session-clarity-20261024`다. [현재 위치와 참가자 작업 탭](K-DOG_현재위치와참가자탭_v1.0_20261024.md)의 상단 회차 선택·부가 안내를 이번 결정으로 대체한다. S1 원응답·채점 규칙, 실제 공급자·현장 인수의 대기 상태는 변경하지 않는다.

## 동작과 제거 범위

- 상단에는 참가자와 현재 촬영 회차를 표시한다. 저장 대상 선택창, 회차 안내·바로가기 버튼, 설명, 전처리 상태 보기 버튼을 JSX에서 삭제했다. 전용 React 상태, 펼침 로직, CSS와 이전 설문 격자 CSS도 삭제했다. 숨김 처리나 별도 구판 실행 경로를 남기지 않는다.
- 한 회차만 있으면 이력을 표시하지 않는다. 여러 회차일 때만 접힌 「촬영 이력」을 제공하며, 회차별 영상 수와 현재 작업 중 표시 또는 「N차 촬영 열기」 버튼을 보여 준다. 이력을 열거나 참가자 작업 탭을 이동하는 것만으로 저장 요청을 보내지 않는다.
- 이전 회차를 명시적으로 열면 이후 작업도 그 회차로 이어진다. 기존 회차 변경 API의 판본 충돌 검사를 유지하고, 미저장 입력 취소 시 화면·입력을 보존한다. 성공한 전환 뒤에만 이전 편집 상태를 해제한다.
- 촬영 기록의 「재촬영 등록」에서 「새 촬영 회차 만들기」를 실행한다. 생성한 회차를 명시적으로 열어 이전 실행의 회차 고정 상태에 머무르지 않게 한다. 기존 자료는 보존하고 새 회차로 복사하지 않는다. 같은 영상의 분석 재실행은 분석 단계에서 처리한다.
- 설문은 A~E 구분을 유지하고 번호 / 설문 문항 / 응답 / 미응답 사유의 네 열로 표시한다. 전체 28문항의 응답·미응답·해당 없음 개수를 위에 표시한다. 0 응답, 미응답, 해당 없음은 구분한다. 미응답 사유가 없으면 「사유 미입력」, 응답한 문항의 사유는 `—`로 표시한다. 원문·척도·계산은 변경하지 않는다.
- 데스크톱에서는 질문 열을 가장 넓게 두고 행 구분선을 표시한다. 680px 이하에서는 문항 하나를 카드 한 개로 표시하고 질문 아래 응답·사유를 배치한다.

### DB·API 확인

제거한 안내·바로가기·선택창 UI만을 위한 DB 필드나 테이블은 없다. 회차 펼침은 React 메모리 상태였다. `cases.selected_session_id`, manifest의 sessions와 `/api/cases/{case_id}/sessions`는 재촬영·촬영 이력에 계속 사용된다. graft 호출 추적으로 영상 등록, 설문 저장, 촬영 입력, 일괄 등록, 전처리, 분석, 비교가 `selected_session` 검증을 공유함을 확인했다. 따라서 이 공용 자료 구조와 API는 제거 대상이 아니며 DB 마이그레이션이나 기존 자료 삭제는 하지 않는다. 운영 DB에 테스트 자료도 추가하지 않는다.

## 리뷰와 이슈 처리

구현과 분리한 수동 cold review 패스로 변경 diff, 호출 관계, 입력 보존, 새 회차 전환, 응답 의미, 반응형 배치, 제거 코드 잔존을 검토했다. 별도 에이전트나 제3자 리뷰를 수행한 것으로 기록하지 않는다.

| 발견 사항 | 판정·처리 |
| --- | --- |
| 분석에서 특정 회차를 고정해 연 경우 새 회차 생성 후 단순 목록 갱신만으로는 화면이 새 회차로 이동하지 않을 수 있음 | 수용: 생성 결과를 명시적으로 열고 갱신 |
| 회차 이동을 허용한 뒤 기존 편집 상태가 다음 작업에 남을 수 있음 | 수용: 성공한 회차 열기 이후 편집 상태 해제. 취소·실패 시 보존 |
| 회차 변경 이전에 시작한 자동 조회가 늦게 도착해 새 회차·판본을 이전 값으로 덮을 수 있음 | 수용: 명시 조회·갱신 세대를 기록해 그 이전의 자동·초기 조회 응답을 무시. 오래된 응답을 지연시킨 회귀로 수정 전 회차 되돌림을 재현 |
| 원응답 격자·회차 부가 안내 CSS와 상태가 남을 수 있음 | 수용: 전용 상태·JSX·스타일 삭제 및 소스·시험 참조 확인 |
| 기존 회귀가 이전 문구·드롭다운·격자 선택자에 의존 | 수용: 새 표·촬영 이력 동선으로 변경. 같은 회차 판본 갱신 시험은 다른 직원의 API 변경과 폴링으로 재현 |
| 모바일 크기 전환 직후 가로 넘침 검사 1회 실패, 진단 후 재실행은 통과 | 수용: 동일한 넘침 기준을 유지하되 반응형 배치 반영을 기다리는 assertion 사용 |
| 촬영 회차 DB 필드와 API까지 삭제 | 거절: 영상·설문·분석의 공용 참조와 재촬영 보존에 필요하며 제거 UI 전용 저장 항목이 아님 |

## 검증

합성 데이터 전용 브라우저 서버 `127.0.0.1:8765`에서 검증한다. 로컬 운영 서버는 `127.0.0.1:8000`이다.

- `npm run build`: 통과. 기존 500 kB 초과 번들 안내만 남는다.
- 초기 관련 회귀 55건 중 53건 통과. 이전 미응답 사유 문구를 기대한 시험 1건과 모바일 크기 전환 직후 검사 1건을 보완했다.
- 후속 4건 중 기존 실패 2건과 표 검증은 통과했다. 신규 이력 시험의 합성 설문을 API의 전체 28문항 계약에 맞추고, 입력 후 텍스트 영역은 접근성 역할로 확인하도록 보완했다.
- 두 번째 관련 회귀는 56건 중 55건 통과. 신규 이력 시험에서 판본 충돌이 나타나 자동 갱신 경합을 조사했다. 반복 진단에서는 참가자 ID 중복으로 발생한 시험 fixture 충돌을 분리하고 반복 번호별 ID를 사용하도록 고쳤다. 지연된 자동 조회를 강제로 전달하는 회귀를 추가하여 수정 전 빌드에서 1차 촬영이 2차로 되돌아가는 실패를 확인했다.
- 수정 후 `npm run test:e2e -- tests/session-history.spec.ts --repeat-each=3`: 3회 모두 통과(20.0초). 회차 되돌림 방지, 재촬영 시 새 회차 열기, 기존 설문 보존, 미저장 입력 취소·허용을 확인했다.
- 최종 관련 회귀 **56건 모두 통과(3.5분)**: `npm run test:e2e -- tests/session-history.spec.ts tests/survey-v4.spec.ts tests/guidance.spec.ts tests/context.spec.ts tests/layout.spec.ts tests/location-navigation.spec.ts tests/intake.spec.ts tests/recording-v4.spec.ts tests/analysis-status-v4.spec.ts tests/preprocess-executions-v4.spec.ts tests/comparisons-v4.spec.ts`.
- `git diff --check`, 문서 상대 링크, 제거한 UI 코드·스타일의 잔존 검색 통과. `graft build` 후 `graft check`의 wiring graph 동기화 확인. backend 코드는 변경하지 않았으며 backend 전체 시험이나 실제 공급자 검증을 수행한 것으로 간주하지 않는다.

화면 증거는 합성 참가자만 사용했다. [데스크톱 설문 표](../screenshots/survey-session-20261024/survey-table-desktop.png), [모바일 설문](../screenshots/survey-session-20261024/survey-table-mobile.png), [모바일 촬영 이력](../screenshots/survey-session-20261024/session-history-mobile.png)을 시각 검토했다.

## 의존성 확인

2026-10-24 공식 npm registry의 최신 버전·선택 버전 engines/peer를 확인하고 [React 상태 API](https://react.dev/reference/react/useState), [Playwright Locator API](https://playwright.dev/docs/api/class-locator)를 확인했다. 의존성 설치·업그레이드는 없으며 검증된 기존 lockfile 조합을 유지한다.

| 도구 | 최신 안정판 | 선택 버전 | 확인 출처 |
| --- | --- | --- | --- |
| React / React DOM | 19.3.1 | 19.2.8 | [React registry](https://registry.npmjs.org/react/latest), [React DOM registry](https://registry.npmjs.org/react-dom/latest); DOM peer `^19.2.8` 충족 |
| Vite | 8.3.5 | 8.2.2 | [registry](https://registry.npmjs.org/vite/latest); Node `^20.19.0 또는 >=22.12.0` |
| TypeScript | 7.0.2 | 7.0.2 | [registry](https://registry.npmjs.org/typescript/latest); Node `>=16.20.0` |
| Playwright Test | 1.64.1 | 1.63.0 | [registry](https://registry.npmjs.org/@playwright%2Ftest/latest); Node `>=20`, 기존 설치 브라우저와 조합 유지 |

## 배포

GitHub `syleeVeluga/k-dog-proj`의 main에 병합 후 로컬 서버의 health, HTML, JS, CSS가 최종 빌드와 일치하는지 확인한다. 외부 서비스 배포·ZIP 발행은 이번 범위에 포함하지 않는다.
