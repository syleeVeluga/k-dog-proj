# K-DOG 업무 권한 단순화 구현 실행 기록

버전: v1.0 · 2026-10-11 · 구현 시작 기준: `main / 0dd9ad8`

2026-10-11 `/goal` 지시에 따라 AR01~AR07 구현을 시작했다. PR별 구현 → 검증 → 독립 cold review → 수용 건만 수정 → 문서 갱신 → 병합 순서다. AR01~AR06은 중간 운영 배포하지 않는다. 실제 평가 자료 초기화·삭제나 유료 공급자 호출은 실행하지 않는다.

## 1 단계별 완료 체크

| 단계 | 구현 | 검증 | 독립 cold review | 수용 수정·재검증 | 문서 | 병합 |
| --- | --- | --- | --- | --- | --- | --- |
| AR01 | [x] | [x] | [x] | [x] | [x] | 대기 |
| AR02 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AR03 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AR04 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AR05 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AR06 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AR07 | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

PR 최종 head·merge SHA는 PR 메타데이터로 확인하고 병합 후 다음 단계에서 표와 개별 계획에 기록한다. 계획 검증 대장의 v1.0/v1.1 기록은 당시 문서 검증 이력으로 유지한다.

## 2 AR01 구현과 검증

브랜치: `veluga/ar01-common-business-access`. 요구사항: AR-R01·AR-R02·AR-R08·AR-R12의 계정 공통화 범위.

- API reader/writer/administrator와 영상·업로드·촬영·Forms·전처리·분석·채점·비교 내부의 업무 역할 제한을 제거했다. 요청 actor의 활성 계정·세션·CSRF/host와 hash·판본 검사는 유지한다.
- 웹 신규 일반 계정은 `operator`로 저장한다. 역할 선택 UI를 제거하고 기존 reviewer/admin의 role/password hash는 활성 상태 저장과 앱 재시작 후에도 보존한다. 모든 계정이 일반 업무 계정을 생성·활성 관리하며 개발자 생성/승격/변경과 현재 로그인 계정의 비활성화는 거절한다.
- 개발자도 공통 메뉴를 사용하며 `#/developer/settings`에서 공급자 키·AI 설정을 관리한다. 일반 계정의 설정 API·직접 경로는 보호한다. 기존 bootstrap/발행/provision 형식과 lockfile은 유지한다.
- 기존 계정·채점·실행 change의 실제 actor를 검증했다. 진행 집계·담당·최종/리포트 상태와 단계 필터도 공통화했고 `my_sheet`는 개인 출처로 유지한다.

아래 시험은 임시 폴더의 합성 입력만 사용했다. 명령은 해당 backend/frontend 디렉터리에서 실행했다.

| 명령 | 결과 |
| --- | --- |
| `uv run --locked python -X utf8 -m unittest tests.test_business_access_v4 tests.test_intake_api tests.test_intake_v4 tests.test_settings tests.test_settings_v4 tests.test_issued_release -v` | 55개, 53.550초 통과 |
| `uv run --locked python -X utf8 -m unittest tests.test_business_access_v4 tests.test_progress_v4 -v` | 수용 수정 후 16개, 11.047초 통과 |
| `npm run build` | 통과; 기존 500kB chunk 안내 있음 |
| `npm run test:e2e -- navigation.spec.ts settings.spec.ts business-access-v4.spec.ts` | 최종 10개, 14.8초 통과; 계정 생성/로그인·설정 보호·직접 경로·미저장 입력·360/390/768/1440px 메뉴 검증 |
| 내부 권한 영향 회귀 11개 모듈 | 최초 152개에서 옛 권한 기대 14건 수정, 재실행 151개 통과/후보 수 기대 1건 수정. 수정한 comparisons는 최종 추가 회귀에 포함한다 |
| `uv run --locked python -X utf8 -m unittest tests.test_ai_api_v4 tests.test_recording_api_v4 tests.test_forms_presets_v4 tests.test_forms_template_v4 tests.test_comparisons_v4 tests.test_progress_v4 -v` | 최종 54개, 47.599초 통과. 앞선 후보 수 기대 1건과 교수 영상 등록·preset 이름 충돌 기대도 이 재실행에서 해결 확인 |
| `git diff --check` | 통과 |

AI 회귀는 교수 계정 요청 → 다른 업무 계정 stop/retry → fake provider 42항목군 Worker 완료를 검증한다. 실제 유료 호출은 없다. 요청 ID의 actor 귀속·preset 이름 중복·stale revision의 409는 유지하며 일반 역할에 의한 거절과 구별한다. 실제 운영 DB의 S1 초기화는 하지 않았다.

![공통 업무 계정 — 합성 계정](images/ar01-common-accounts.png)

소유·배정·공개 허가/노출 조건은 AR03, 동의·삭제/clean·restore는 AR04, 리포트 특수 교수 접근과 공유 산출물은 AR05에서 제거한다. AR01만으로 통합 전환·운영 배포 완료를 표시하지 않는다.

## 3 AR01 독립 cold review와 수용 판단

`ar01_cold_review`가 계획과 실제 diff/호출 관계를 읽기 전용 검토했다. 발견 1건(P2)을 수용했고 보류/거절 발견은 없다.

| 발견 | 판단·반영 | 재검토 |
| --- | --- | --- |
| 공통 프런트 진행 표시와 reviewer 서버 null 집계가 불일치하여 잘못된 '미배정'/미완료 안내 | 수용. 서버 진행 요약·화면 단계 필터 공통화, 계정별 동일 요약 회귀 | P2 해결 확인. 독립 `tests.test_progress_v4` 11개·diff check 통과, 새 actionable 0건 |

개발자 승격·기존 계정/hash·만료/비활성 인증·내부 업무 접근·실제 actor에 추가 actionable은 없었다. 후속 PR의 소유·동의·리포트 제한을 AR01 결함으로 혼동하지 않았다.

## 4 의존성 확인 — 2026-10-11

공식 PyPI JSON/npm registry 최신 stable tag와 공식 릴리스/API를 온라인 확인했다. 기존 잠금 환경의 정책 변경이며 새 의존성을 도입하지 않는다. 발행/provision 호환과 AR07 통합 검증을 위해 기존 선택판을 유지하고 무관한 업그레이드를 섞지 않는다. Python 3.14와 프로젝트 Node `>=22.12.0` 조건에서 시험·빌드를 실행했고 React/ReactDOM·types 대응판과 lockfile을 유지했다.

| 라이브러리 | 최신 안정판 | 선택판 |
| --- | --- | --- |
| FastAPI / Pydantic / Uvicorn | 0.143.0 / 2.14.0 / 0.54.0 | 0.141.1 / 2.13.5 / 0.52.4 |
| HTTPX / openpyxl / ReportLab / Pillow / cryptography | 0.28.1 / 3.1.5 / 5.0.1 / 12.3.0 / 50.0.2 | 동일 |
| pypdf | 6.20.0 | 6.19.0 |
| React / ReactDOM | 19.3.0 / 19.3.0 | 19.2.8 / 19.2.8 |
| @types/react / @types/react-dom | 19.3.0 / 19.3.0 | 19.2.18 / 19.2.7 |
| TypeScript / Vite / Playwright | 7.0.2 / 8.3.4 / 1.64.0 | 7.0.2 / 8.2.2 / 1.63.0 |

공식 registry: [FastAPI](https://pypi.org/project/fastapi/)·[Pydantic](https://pypi.org/project/pydantic/)·[Uvicorn](https://pypi.org/project/uvicorn/)·[HTTPX](https://pypi.org/project/httpx/)·[openpyxl](https://pypi.org/project/openpyxl/)·[ReportLab](https://pypi.org/project/reportlab/)·[Pillow](https://pypi.org/project/pillow/)·[cryptography](https://pypi.org/project/cryptography/)·[pypdf](https://pypi.org/project/pypdf/), [React](https://registry.npmjs.org/react/latest)·[ReactDOM](https://registry.npmjs.org/react-dom/latest)·[types/react](https://registry.npmjs.org/@types/react/latest)·[types/react-dom](https://registry.npmjs.org/@types/react-dom/latest)·[TypeScript](https://registry.npmjs.org/typescript/latest)·[Vite](https://registry.npmjs.org/vite/latest)·[Playwright](https://www.npmjs.com/package/@playwright/test?activeTab=versions).

릴리스/API: [FastAPI release](https://fastapi.tiangolo.com/release-notes/)·[Depends](https://fastapi.tiangolo.com/tutorial/dependencies/), [Pydantic changelog](https://docs.pydantic.dev/latest/changelog/)·[models](https://docs.pydantic.dev/latest/concepts/models/), [React versions](https://react.dev/versions)·[useEffect](https://react.dev/reference/react/useEffect), [Playwright release](https://playwright.dev/docs/release-notes)·[assertions](https://playwright.dev/docs/test-assertions).

FastAPI 최신판의 breaking-change 항목은 이번 정책 PR에서 자동 교체하지 않았다. 기존 Starlette TestClient의 HTTPX deprecation 안내는 시험 실패가 아니며 HTTPX2 도입을 범위에 추가하지 않았다.
