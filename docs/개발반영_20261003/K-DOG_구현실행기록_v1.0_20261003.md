# K-DOG S1 구현 실행 기록

버전: v1.0 · 2026-10-03 · 착수 기준: `39a4ef9` · 상태: 진행 중

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 사용자 지시에 따라 S00~S15 구현과 자동 검증을 완료하고, 실제 영상·장비·공급자 실측은 [후속 대장](K-DOG_실측및확인후속대장_v1.0_20261003.md)으로 분리한다. 정책 미확정은 승인으로 간주하지 않는다.

## 실행 방법

각 단계는 구현 → 해당 자동 시험 → 원문과 대조하는 독립 cold review → 발견사항 수용/보류 사유 → 수정·재검증 → 단계별 commit 순서로 진행한다. 구현 담당과 리뷰 담당을 분리한다. 병렬 작업은 담당 파일을 나누고 공통 파일은 통합 담당이 수정한다. 참가자 원본·응답·키는 commit과 시험 fixture에서 제외한다.

S00 원본 추출·계약 담당, S01 초기화·복구 담당, 통합 접수/API/UI 담당을 분리했다. 독립 검토자가 인수 기준과 실측·정책 대기를 분류했다. `graft check`는 착수 때 동기화 상태를 확인했고 이후 코드 변경마다 그래프를 갱신한다.

## 단계 상태

| 단계 | 구현·검증 상태 | 독립 리뷰 | commit |
| --- | --- | --- | --- |
| S00 | 원본 SRC02/SRC03 해시 일치, 8개 산출물 재생성 확인, 계약/매핑 시험 30개 통과 | 발견 5건 수정·재검증 완료 | `7077368` |
| S01 | 초기화·접수·API/UI 구현, 접수 5개·초기화 16개 및 브라우저 1개 통과, 운영 초기화는 통합 전환 시 적용 | 초기화 3건·인증 순서 1건 수정·재검증 완료 | `d2e561e` |
| S02 | Forms30/API4/설문11/백업·권한13=58개와 브라우저2개 통과 | 삭제·복원·원본 참조·시트/회차 연결 발견사항 수정·재검증 완료 | `18aca50` |
| S03 | uploads23/API5/기존 회귀45, 3브라우저 동시시험1개 통과 | 출처/권한/취소/삭제복원·브라우저 발견사항 수정·재검증 완료 | `9f307a3` |
| S04 | 촬영16/API8/기존영상등록11=35개 및 브라우저2개 통과, 기존업로드23개 회귀 통과 | 관찰 손실·논리창 저장·판본 표시·업로드 경로·모바일 발견사항 수정 | `717af9e` |
| S05 | 전처리13/API1/촬영API9, 브라우저2 및 build 통과 | hash/재사용/수명주기·이전회차 조회 수정·재검증 | `5fd346d` |
| S06 | 시트16/Excel gate2/API2 및 브라우저1·build 통과. 실제 Excel import 비활성 | 원자료 재검증·보존본 API 수정·재검증 완료 | `4de388e` |
| S07 | 계산22/판정14/계약15/API1, 브라우저1 및 build 통과 | 실제batch 연결·명시반대코드·초안/조회/안전기지 표시 수정 | `ed81287` |
| S08 | 정규화12/공급자4/실행15/설정6/API2, 기존Worker14/계량4, 브라우저3+기존1/build 통과 | source fencing·계량·정리 상태·clip 없는 관찰창 수정 | `c249c13` |
| S09 | 의견10/최종12/명시해석공개7/API2, 시트16/판정14/AI1 회귀, 브라우저2+추가표시1/build 통과 | 타인 해석 노출·신규파일 검증·UI 비동기 대상 구분 수정 | `fdfc4b3` |
| S10 | 내용12/장면13/검증·서비스11=36개 통과 | 미정 유형 서술·걷기 문장 수치·완료 환경/성향 의견 수정 | 이 기록을 포함하는 S10 commit |
| S11~S12 | HTML/PDF·실행 병렬 구현, 서버PDF6쪽 시각검수·자동5개 통과 | 인쇄 CSS·발급 조건 원문 대조 진행 중 | 미기록 |
| S13~S15 | 대기 | 대기 | 미기록 |
| S16 | 실측 후속, 준비 코드와 실제 결과를 분리 | 대기 | 미기록 |
| S17 | 승인 gate 구현 예정, D06 확인 전 외부값 차단 | 대기 | 미기록 |

## 의존성 확인

확인일: 2026-10-03. 공식 PyPI JSON/프로젝트, npm registry, 공식 API/릴리스 문서를 확인했다. 기존 잠금 버전의 API만 사용하고 관련 없는 프레임워크 업그레이드를 섞지 않는다. 새 패키지는 도입하지 않았다. Python 3.14와 Node 24.13.0을 사용한다.

| 패키지 | 최신 안정판 | 선택(기존 잠금) | 근거·호환성과 선택 이유 |
| --- | --- | --- | --- |
| Pydantic | 2.13.5 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [BaseModel API](https://docs.pydantic.dev/latest/api/base_model/). Python ≥3.9, 3.14 지원, model_validate/model_validate_json/model_validator 사용 |
| FastAPI | 0.142.2 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/), [릴리스](https://fastapi.tiangolo.com/release-notes/). Python ≥3.10. 기존 요청·응답 모델/의존성 API 유지, S1과 무관한 프레임워크 변경 제외 |
| Uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/). Python ≥3.10. 기존 서버 실행 환경 잠금 유지 |
| openpyxl | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/), [문서](https://openpyxl.readthedocs.io/en/stable/). Python ≥3.8, 읽기 전용 Excel 추출 |
| ReportLab | 5.0.1 | 5.0.1 | [PyPI](https://pypi.org/project/reportlab/). Python ≥3.9,<4. 실제 S11 사용 전 렌더 API 추가 확인 |
| Pillow | 12.3.0 | 12.3.0 | [PyPI](https://pypi.org/project/pillow/). Python ≥3.10. 실제 이미지 처리 전 API 추가 확인 |
| HTTPX | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/), [transport API](https://www.python-httpx.org/advanced/transports/). Python ≥3.8. 기존 TestClient 잠금 사용 |
| React / react-dom | 19.3.0 | 19.2.8 | [npm](https://www.npmjs.com/package/react), [공식 버전](https://react.dev/versions). 같은 버전의 renderer/React 유지, 새19.3 기능 미사용 |
| @types/react / @types/react-dom | 19.3.0 | 19.2.18 / 19.2.7 | [타입 registry](https://registry.npmjs.org/@types/react/latest), [DOM 타입](https://registry.npmjs.org/@types/react-dom/latest). 기존 React19.2 타입 잠금 유지 |
| Vite | 8.3.2 | 8.2.2 | [registry](https://registry.npmjs.org/vite/latest), [공식 안내](https://vite.dev/guide/). Node20.19+/22.12+ 계열, 현재 Node24 호환, 기존 빌드 설정 유지 |
| TypeScript | 7.0.2 | 7.0.2 | [registry](https://registry.npmjs.org/typescript/latest), [공식 문서](https://www.typescriptlang.org/docs/). Node≥16.20, 현재 Node24 호환 |
| Playwright | 1.63.0 | 1.63.0 | [registry](https://registry.npmjs.org/@playwright/test/latest), [릴리스](https://playwright.dev/docs/release-notes). Node≥20, 현재 Node24 호환 |

## 실제 실행 근거

- S01 `uv run --locked python -X utf8 -m unittest tests.test_intake_v4 tests.test_reset_s1 -v`: 합성 21개 통과(접수 5·초기화 16). S1 기본 접수, 원점수 없음, 원영상 hash·설문0/null·새 입력 이력 보존, 구판 실행 차단, 명시 초기화 필요, 로그인/권한 뒤 준비 상태 확인 및 보안 응답 헤더를 검증했다.
- 전체 backend 회귀 266개 중 265개 통과 후, 실패한 1개 런처 시험의 구판 fixture를 명시 초기화하도록 수정하여 해당 시험이 통과했다. 이후 접수/초기화 21개를 추가 실행하여 통과했다. 구판 시험은 판본을 명시하고 제품 기본 실행은 S1만 사용한다. 실제 런처/worker 동시 기동과 초기화 전 구판 큐 점유 차단을 모두 subprocess로 확인했다.
- `npm run build` 및 `KDOG_TEST_INTAKE_SPEC=20261002 npx playwright test tests/intake-v4.spec.ts` 통과. 새 접수·빈 점수·구판 실행 차단 화면을 확인했다.
- 실제 운영 루트는 읽기 전용으로 확인했다. 원본 intake-1.0 30문항 자료가 있어 정확한 원파일 bytes/hash를 source-only 참조로 남기고 새 S1 점수의 부모 이력과 분리했다. 동일 형태의 합성 자료로 초기화/새 백업 복원을 검증했다. 실제 초기화 적용은 통합 전환 시 실행한다.
- 실제 운영 데이터 초기화, 실제 공급자 호출, 고객 발송, 배포는 아직 수행하지 않았다.
- 전체 backend·브라우저 검증과 cold review 조치 기록은 단계 완료 시 추가한다. 이 기록은 전체 완료 선언이 아니다.
- S02(2026-10-04): `uv run --locked python -X utf8 -m unittest tests.test_forms_import_v4 tests.test_forms_api_v4 tests.test_survey_v4 tests.test_settings -v` 58개 통과. `npm run build` 통과. `KDOG_TEST_INTAKE_SPEC=20261002`의 `tests/importer-v4.spec.ts`, `tests/survey-v4.spec.ts` 각각 통과했다. 브라우저에서 원라벨 오류 후 수정·동명이인 신규2명·중복 확정 방지·원응답0·기존 회차의 전후값·revision409·최신 연결 재시도·배치 변경 대상 초기화와 S1 설문 결측/역채점 표시를 검증했다. 상세 발견사항과 인계는 S02 계획의 구현 기록을 따른다.
