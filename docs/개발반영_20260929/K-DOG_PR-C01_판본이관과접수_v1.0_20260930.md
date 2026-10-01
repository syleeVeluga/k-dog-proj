# PR-C01 판본 이관과 접수

버전: v1.0 · 2026-09-30 · 상태: 완료(구현·검증·cold review·수용 수정·문서·푸시) · 선행: C00 · 추정: 2~3개발일

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20260930.md). 근거: 00 §2·§7, 01 동의, 기존 A01/A02 원본 무결성·편집 보호. 권장 제목: `feat: 신구 판본을 보존하는 세션과 접수 계약`.

## 문제와 결과

현재 `Session`에는 설문 판본만 있다. 기존 55항목 자료를 이관할 때도 영상과 세션을 유지하면서 설문 판본은 바꾸므로, 설문 판본으로 촬영 기준을 추정할 수 없다. 새 접수부터 현행 판본을 명시하고 구판·미확인 촬영 기록을 그대로 조회할 수 있게 한다.

## 변경 파일

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `backend/app/input_models_v3.py` | 신설 | 새 manifest/session·판본·빈칸 사유·동의 항목 계약. 기존 계약과 분리 |
| `backend/app/input_models.py` | 최소 확장 | 판본별 읽기/응답 연결; 기존 intake-2.0 의미 보존 |
| `backend/app/storage.py` | 변경 | 스키마별 조회·원본 검증 후 이관·SQLite migration·불변 revision |
| `backend/app/intake.py`, `api.py` | 변경 | 새 세션 기본판본·명시적 세션 조회·접수/목록 응답 판본 |
| `backend/app/maintenance.py` | 변경 | 새 manifest·동의·판본 참조 백업/복원과 삭제 보호 |
| `frontend/src/types.ts`, `ParticipantFields.tsx`, `Importer.tsx` | 변경 | 판본과 동의 표시·가져오기 계약 |
| `frontend/src/pages/Intake.tsx`, `CaseDetail.tsx` | 변경 | 새 세션/구판 안내·기존 준비 상태 보존 |
| `backend/tests/test_intake_api.py`, `test_settings.py` | 확장 | 정상/손상 이관·멱등·구판/미확인·복원·삭제 |
| `frontend/tests/intake.spec.ts`, `integrity.spec.ts`, `context.spec.ts` | 확장 | 세션 판본·409·동의 표시·참가자 맥락 |

## 구현 순서와 경계

1. 이관 전 DB의 manifest 해시·참가자/행사/세션/revision 참조를 검증한다. 이전 원본과 run snapshot은 보존하고 새 불변 입력만 추가한다. 손상된 참가자는 이관 실패로 남기되 다른 정상 참가자 목록은 사용할 수 있어야 한다.
2. 실제 근거가 있는 42항목 촬영은 구 절차로 태그한다. legacy 이관·근거 없는 세션은 미확인으로 구분한다. 답변 의미/번호로 촬영 판본을 추정하거나 영상 시각을 바꾸지 않는다.
3. 새 세션은 신판 촬영·설문 기준을 사용한다. 구판 촬영 대상에게 재설문이 필요하면 새 응답 판본과 세션/이력을 명시적으로 연결한다. 구판 10~14번 응답에서 1을 빼거나 역채점해 신판 값으로 바꾸지 않는다. 판본 간 문항 이관은 문장·조건이 확인된 명시적 매핑만 허용한다.
4. 01의 두 동의 항목과 기존 `consent_confirmed`의 관계를 Q11로 고정한다. 기존 true를 새 동의 두 개나 외부AI 동의로 확대하지 않는다. 제공되지 않은 동의는 미확인이다. 연락처·홍보 수집 필드를 임의 추가하지 않는다.
5. 현재 편집의 base revision/409·미저장 보호·삭제 상태 재확인을 유지한다. 필드별 판본을 조회 응답에도 포함하고 DB 메타데이터와 manifest가 불일치하면 정상 입력으로 채택하지 않는다.
6. 현재 `DogProfile.age_years`는 정수 년이고 `years_together`는 자유 문자열이다. 새 설문의 살/개월·년/개월 정보를 충분히 표현하지 못하므로 국내 비교에 필요한 ‘데려온 나이’를 자동 계산하지 않는다. 월 단위 저장 필요 여부와 ‘어릴 때’의 연령 경계는 Q10에 넘기고, 확인 전 비교 대상 집단은 미확인으로 둔다. 기존 값을 월 단위의 정확한 값으로 추정해 이관하지 않는다.

## 검증과 완료 조건

- v1 이관, v2 정상, legacy에서 v2로 이관된 세션, 미확인 촬영, 신판 세션을 별도 fixture로 검증한다. 재시작 이관은 한 번만 적용되고 이전 파일/해시가 유지된다. 기존 v1/v2 계약과 조회 회귀를 보존한다.
- 해시/식별자 불일치, 지원하지 않는 판본, 참조 누락을 검증하며 원본을 임의 복구하지 않는다. ‘촬영 판본 미확인’은 지원하지 않는 판본 문자열과 구분해 보존한다. 이전 응답·시각을 신판 의미로 보여주지 않는다.
- 동의 미확인/거절/확인 및 변경 이력, CSV/Excel 접수 템플릿·preview·commit이 같은 의미를 사용한다.
- 백업/복원 뒤 판본·이전 revision·동의가 보존된다. 삭제 기록을 복원에 재적용하고 삭제 요청된 자료의 수정·조회·후속 실행을 차단한다.
- 새 접수와 기존 목록·검색·선택 세션 맥락, 편집 충돌 e2e가 통과한다.

## 추가 확인과 인계

Q11의 실제 동의 문구·외부 AI 범위는 운영 전에 확정해야 한다. Q10에는 월 단위 나이·함께 산 기간의 표현 한계와 비교 집단 구분 조건을 전달한다. C02는 응답 판본별 계산, C03은 촬영 판본별 순서를 사용한다. 앱·worker의 일괄 활성화와 구판 run 삭제는 이 PR 범위가 아니다.


## 구현 및 검증 기록 — 2026-10-01

- [x] intake-3.0 envelope/session과 판본별 읽기, 입력 revision별 이전 ref/hash 보존. SQLite user_version=7, 정상 v1→v2→v3와 v2→v3 이관은 한 번만 적용한다. 원응답·파일·시각·run snapshot은 변경하지 않는다.
- [x] 촬영 기준은 확인된 v2 구간 근거가 있는 세션에만 구판 태그를 적용한다. legacy와 근거 없는 세션은 미확인이다. 신규 기본은 신판이며 구판 회귀 도구의 `intake_spec="20260913"`는 명시적으로 구판을 선택한다.
- [x] 새 분석·피드백/낯선 요원 접촉 동의를 미확인·거절·확인으로 각각 기록한다. 기존 동의 true는 확대하지 않는다. 생략한 옛 API 클라이언트의 편집은 새 동의를 지우지 않으며 이전/이후 동의와 입력 파일 이력을 보존한다.
- [x] CSV/XLSX 접수의 두 선택 열 `consent_analysis_feedback`, `consent_stranger_contact`와 preview/commit 의미를 통일했다. 구판 13열 접수 파일은 그대로 허용하고 새 열 생략은 미확인이다.
- [x] 목록·상세의 판본/동의 표시, 기존 409·미저장·권한 보호 유지. 선택 회차의 설문 카탈로그를 별도 조회하여 구판 원응답을 보존한다.
- [x] 독립 cold review: 아래3건 수용·수정, reviewer 재확인에서 미해결 발견 없음.
- [x] 최종 백엔드150개, 신판 접수 추가시험6개 포함, 프론트 build와 e2e17개 통과. `--spec all --check` 및 `git diff --check` 통과.
- [x] 브랜치 `veluga/pr-c01-intake-v3` 푸시·[PR #27](https://github.com/syleeVeluga/k-dog-proj/pull/27) 생성. 구현 커밋 `80b6420`, base C00(#26). 병합은 별도 상태다.

| 리뷰 발견 | 판단과 반영 | 검증 |
| --- | --- | --- |
| 구판 설문 import에 새 전역 카탈로그 적용, 구판 원응답 화면 숨김 | 수용. C02 연결 전 v2 preview/commit의 카탈로그를 명시하고 선택 세션 판본으로 UI 카탈로그 조회 | 신판 기본 API에서 구판 CSV preview/commit, 기존 원응답 e2e |
| 이관된 확정 v2 구간을 초안으로 편집하면 판본 계약 실패 | 수용. 판본 근거는 이전 확정 기록으로 유지하고 현재 초안 상태와 분리 | 구판 이관 뒤 초안 재편집 200, 촬영 판본 유지 |
| 실패한 v2 의미 검증을 건너뛰고 정상 200으로 제공 | 수용. 지원 판본·28문항·중복 세션·영상 참조를 v2 읽기에서도 검증하고 실패를 사례별409로 격리 | 손상 fixture4종 원본 불변·정상 사례 목록 유지, 동의 DB 손상409 |

`input_models.py`의 구판 의미는 수정하지 않고 새 envelope가 읽기/응답을 담당한다. `maintenance.py`는 기존 재귀 ref/hash 처리가 새 prior_inputs를 이미 보존하므로 코드 변경 없이 백업/복원·삭제 회귀로 확인했다. 삭제 ledger 재적용 시 해당 사례와 이전 입력도 폐기한다. 기존 전처리 참조 수에는 보존된 이전 manifest 한 개가 추가됨을 시험에 반영했다. 기존 `scripts/rehearsal.py`는 C13의 현행 통합 리허설로 교체하기 전까지 명시적 구판 fixture이다.

신판 설문 입력/집계는 C02, 신판 촬영 순서/예외와 전처리는 C03/C04에서 연결한다. C01 단계의 신판 설문 집계는 명시409, 원응답 뷰는 연결 대기 안내를 제공한다. Q10의 비교 대상 자격과 Q11의 운영 동의 문구/외부 AI 범위는 미확인으로 유지한다. 실제 참가자 자료·provider 실증은 수행하지 않았다.

의존성 온라인 확인일 2026-10-01. 설치/lock 변경 없이 기존 버전을 유지했다. Python3.14/Pydantic2와 Node>=22.12의 기존 제약에 맞으며, 무관한 프레임워크 업그레이드는 이관 PR에서 분리한다.

| 의존성 | 최신 안정 / 선택 | 공식 확인과 유지 이유 |
| --- | --- | --- |
| FastAPI | 0.142.2 / 0.141.1 | [PyPI](https://pypi.org/project/fastapi/), [release notes](https://fastapi.tiangolo.com/release-notes/), [response model](https://fastapi.tiangolo.com/tutorial/response-model/). 최신은 OpenTelemetry 기능/시작 수정 포함. Python>=3.10·Pydantic>=2.9 호환 확인, 이번 변경은 기존 응답 union API만 사용 |
| Pydantic | 2.13.5 / 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [validators](https://docs.pydantic.dev/latest/concepts/validators/). strict 판본 계약/JSON 검증 API 유지 |
| openpyxl | 3.1.5 / 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/), [changes](https://openpyxl.readthedocs.io/en/stable/changes.html). 기존 XLSX 읽기 API 유지 |
| React / ReactDOM | 19.3.0 / 19.2.8 | [npm React](https://www.npmjs.com/package/react), [npm ReactDOM](https://www.npmjs.com/package/react-dom), [19.3](https://react.dev/blog/2026/09/09/react-19-3), [select](https://react.dev/reference/react-dom/components/select). DOM peer와 React 버전 일치, 기존 폼 API 사용 |
| Vite | 8.3.1 / 8.2.2 | [npm](https://www.npmjs.com/package/vite), [Vite8](https://vite.dev/blog/announcing-vite8). Node ^20.19 또는 >=22.12 호환, 빌드 도구 업그레이드 범위 제외 |
| TypeScript | 7.0.2 / 7.0.2 | [npm](https://www.npmjs.com/package/typescript), [공식 문서](https://www.typescriptlang.org/docs/). 기존 타입 검사만 사용 |
| Playwright | 1.63.0 / 1.63.0 | [npm](https://www.npmjs.com/package/@playwright/test), [release notes](https://playwright.dev/docs/release-notes). Node>=20 호환, 기존 locator/test API 유지 |

코드 메모리 MCP는 도구 목록에 없음을 재확인하여 직접 탐색으로 대체했다. UI 검증 스크린샷: [데스크톱](검증자료/C01_접수상세_데스크톱.png), [360px](검증자료/C01_접수상세_360px.png). 합성 참가자만 사용했고 시각 확인에서도 겹침·가로 넘침이 없다.
