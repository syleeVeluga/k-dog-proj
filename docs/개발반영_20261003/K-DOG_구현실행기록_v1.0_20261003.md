# K-DOG S1 구현 실행 기록

버전: v1.0 · 2026-10-03 · 착수 기준: `39a4ef9` · 상태: S00~S17 실측 외 구현·자동 검증·독립 검토 완료 · 완료 확인: 2026-10-04

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 사용자 지시에 따라 S00~S17의 실측 외 구현과 자동 검증을 완료하고, 실제 영상·장비·공급자 실측과 연구 확인은 [후속 대장](K-DOG_실측및확인후속대장_v1.0_20261003.md)으로 분리한다. 정책 미확정은 승인으로 간주하지 않는다.

## 실행 방법

각 단계는 구현 → 해당 자동 시험 → 원문과 대조하는 독립 cold review → 발견사항 수용/보류 사유 → 수정·재검증 → 단계별 commit 순서로 진행한다. 구현 담당과 리뷰 담당을 분리한다. 병렬 작업은 담당 파일을 나누고 공통 파일은 통합 담당이 수정한다. 참가자 원본·응답·키는 commit과 시험 fixture에서 제외한다.

S00 원본 추출·계약 담당, S01 초기화·복구 담당, 통합 접수/API/UI 담당을 분리했다. 독립 검토자가 인수 기준과 실측·정책 대기를 분류했다. `graft check`는 착수 때 동기화 상태를 확인했고 이후 코드 변경마다 그래프를 갱신한다.

## 단계 상태

| 단계 | 구현·검증 상태 | 독립 리뷰 | commit |
| --- | --- | --- | --- |
| S00 | 원본 SRC02/SRC03 해시 일치, 8개 산출물 재생성 확인, 계약/매핑 시험 30개 통과 | 발견 5건 수정·재검증 완료 | `7077368` |
| S01 | 초기화·접수·API/UI 구현, 접수 5개·초기화 16개 및 브라우저 1개 통과. 실제 로컬 초기화·원입력 보존·사후 복원은 S15에서 적용·검증 | 초기화 3건·인증 순서 1건 수정·재검증 완료 | `d2e561e` |
| S02 | Forms30/API4/설문11/백업·권한13=58개와 브라우저2개 통과 | 삭제·복원·원본 참조·시트/회차 연결 발견사항 수정·재검증 완료 | `18aca50` |
| S03 | uploads23/API5/기존 회귀45, 3브라우저 동시시험1개 통과 | 출처/권한/취소/삭제복원·브라우저 발견사항 수정·재검증 완료 | `9f307a3` |
| S04 | 촬영16/API8/기존영상등록11=35개 및 브라우저2개 통과, 기존업로드23개 회귀 통과 | 관찰 손실·논리창 저장·판본 표시·업로드 경로·모바일 발견사항 수정 | `717af9e` |
| S05 | 전처리13/API1/촬영API9, 브라우저2 및 build 통과 | hash/재사용/수명주기·이전회차 조회 수정·재검증 | `5fd346d` |
| S06 | 시트16/Excel gate2/API2 및 브라우저1·build 통과. 실제 Excel import 비활성 | 원자료 재검증·보존본 API 수정·재검증 완료 | `4de388e` |
| S07 | 계산22/판정14/계약15/API1, 브라우저1 및 build 통과 | 실제batch 연결·명시반대코드·초안/조회/안전기지 표시 수정 | `ed81287` |
| S08 | 정규화12/공급자4/실행15/설정6/API2, 기존Worker14/계량4, 브라우저3+기존1/build 통과 | source fencing·계량·정리 상태·clip 없는 관찰창 수정 | `c249c13` |
| S09 | 의견10/최종12/명시해석공개7/API2, 시트16/판정14/AI1 회귀, 브라우저2+추가표시1/build 통과 | 타인 해석 노출·신규파일 검증·UI 비동기 대상 구분 수정 | `fdfc4b3` |
| S10 | 내용12/장면13/검증·서비스11=36개 통과 | 미정 유형 서술·걷기 문장 수치·완료 환경/성향 의견 수정 | `e9af2b3` |
| S11 | 렌더5/브라우저2, 정상 서버·브라우저PDF6쪽, 긴12/10쪽 시각·텍스트 검수 통과 | PDF 색·척도 의미·인쇄 CSS 수정, G02 발급 조건 원문 대조 | `09658f8` |
| S12 | 실행20/API1/브라우저3/build 통과, 명시 생성·게시·이력 메뉴 완료 | 독립20개 재실행, 발급 가능 상태·다운로드·인쇄 focus 수정 | `94c378c` |
| S13 | 집단20/API·백업2/브라우저2, S12 접점5/build 통과 | 독립 검토·회차 동기화 수정 완료 | `c1913ce` |
| S14 | 검수10/연구11/API2 및 브라우저3/build 통과, 명시 참고 등록·고정 연구 export 완료 | 과거 식별값·동일 원본 삭제 폐쇄·중복 셀·후보 구분 수정, 독립21개 재실행 통과 | `299b0b7` |
| S15 | S1 종단 리허설·재시작·새 결과 보호·기존 운영 자료 초기화 검증. backend685·브라우저41·현재 Windows 새 폴더 ZIP 설치 검증 완료 | 구판 우회·삭제 복원·CLI와 문서 수정, 최종 packaging cold 통과 | `c1eeccb` |
| S16 | 실제 입력·환경·시간·비교 pair를 검증하는 읽기 전용 집계 도구와 25개 시험 완료. 실제 영상 실측은 대기 | offset 부호·고정 export 대조 수정·재검증 | `0eb5565` |
| S17 | 확인 근거·승인/활성 판본·대상 고정 snapshot→보고서/export 연결, 신규 backend16·기존리포트25·브라우저1 통과. 실제 D06은 미승인 | 철회 경합·관리자 초안 충돌·PDF 고아 페이지 수정, 전6쪽/모바일 시각 검수 | `47bf105` |

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
- S01 착수 때 실제 운영 루트를 읽기 전용으로 확인했다. 원본 intake-1.0 30문항 자료의 정확한 bytes/hash를 source-only 참조로 남기고 새 S1 점수의 부모 이력과 분리했다. 이후 S15에서 실제 초기화를 적용했다(아래 기록).
- 실제 공급자 호출·고객 발송·현장 배포는 수행하지 않았다. 실제 로컬 데이터 초기화는 S15 범위로 완료했다.
- 각 단계의 검증과 cold review 조치는 아래 및 개별 단계에 기록했다. 최종 완료 범위와 실측·승인 제외는 마지막 절을 따른다.
- S02(2026-10-04): `uv run --locked python -X utf8 -m unittest tests.test_forms_import_v4 tests.test_forms_api_v4 tests.test_survey_v4 tests.test_settings -v` 58개 통과. `npm run build` 통과. `KDOG_TEST_INTAKE_SPEC=20261002`의 `tests/importer-v4.spec.ts`, `tests/survey-v4.spec.ts` 각각 통과했다. 브라우저에서 원라벨 오류 후 수정·동명이인 신규2명·중복 확정 방지·원응답0·기존 회차의 전후값·revision409·최신 연결 재시도·배치 변경 대상 초기화와 S1 설문 결측/역채점 표시를 검증했다. 상세 발견사항과 인계는 S02 계획의 구현 기록을 따른다.
- S14(2026-10-04): `uv run --locked python -X utf8 -m unittest tests.test_validation_data_v4 tests.test_exports_v4 tests.test_research_api_v4 tests.test_acceptance_v4 -v`는 검수9·연구11·실제 HTTP2·추가 인수5의 27개가 통과(31.435초)했다. 이후 동의 미확인/철회 참고 대응 허용·삭제 대상 제외 후보 시험1개가 별도 통과(0.656초)했다. 원본 XLSX bytes/XML/캐시 보존, 현재 S1 점수 불변, 정확한 source/revision/hash와 독립 분모, −2/0/null, CSV 수식 주입 방지·XLSX 잘림 거절, 권한·늦은 삭제·백업/복원 폐쇄를 합성 자료로 검증했다.
- S14 독립 cold review는 과거 이름/ID 누락 비식별화, 동일 XLSX 무대응 복제의 삭제·복원 후 재노출, 중복 시트/셀의 값 덮어쓰기를 재현했다. 3건 모두 수용해 수정했으며 reviewer가 검수9·연구11·참가자ID 변경 뒤 삭제/반복 복원1의 21개를 독립 재실행해 통과(36.258초)하고 잔여 actionable finding 없음을 확인했다. UI cold에서 발견한 동의 상태별 참고 후보 구분도 별도 수정·회귀했다.
- S14 화면은 `frontend/tests/exports-v4.spec.ts` 3개 통과(22.8초), `npm run build` 56 modules 통과, 360px 가로 넘침 없음과 이미지2개 시각 검토를 완료했다. 실제 고객 XLSX의 독립 정답 승인·실제 공급자 정확도/시간/비용은 측정하지 않았다. G01/G04 정식 Excel 입력 승인과 G03 실제 사람 참조 확인은 [S14 계획](K-DOG_PR-S14_검수자료와연구내보내기_v1.0_20261003.md)의 후속 경계를 유지한다.

- S15 실제 로컬 전환: 보호된 사전 백업152파일과 원 DB를 보존한 뒤 승인된 초기화를 적용했다. 원입력2·영상참조6의 hash, 참가자2·계정2를 유지했고 구판 run9/step111을 제거했다. 초기화 반복 complete, 새 점수/기본결과0, 원격 정리 대기0, 사후 백업14파일/새 폴더 복원13참조, 초기화 전 백업의409거절을 확인했다. 개인정보·파일 내용·운영 폴더의 세부 증거는 commit하지 않았다.
- S15 전체 회귀에서 발견한 시험6건은 삭제 tombstone의 안정 case_id를 포함한 새 계약과 합성 fixture ID를 정정했다. 제품 보호를 약화하지 않고 관련36개(61.450초)가 통과했다. 최종 packaging/rehearsal 독립 cold에서는 추가 actionable finding이 없었다. 제품 version만0.3.0으로 일치시켰으며 의존성 변경0, `uv lock --check --offline` 통과다.
- S16은 읽기 전용 benchmark 도구·schema/template·고정 실행/설정/영상/시간/품질 대응·필수3조건의 미측정 사유를 구현했다. 25개 준비/연결 시험을 통과했고 실제 영상·외부 AI 실측은0건이다. 자세한 재개 명령과 E/P 경계는 S16 계획과 후속 대장을 따른다.
- S17은 합성 승인 상태에 한해 실제 HTTP·HTML/PDF·CSV/XLSX와 철회·삭제/복원을 검증했다. 신규16개(38.254초), 기존 report lifecycle/render25개(79.624초), 독립 비교/render35개(37.594초)가 통과했다(중복 범위를 단순 합산해 전체 수로 쓰지 않음). 두 출처 actual renderer6쪽/중복 안내1회 회귀와 root의 모든 PDF 페이지·모바일 이미지5개 시각 검토를 완료했다. 실제 운영 연구 승인·기술 활성화는 수행하지 않았다.
- S17 브라우저1개(41.1초)는 관리자 초안 판본 경합409·명시 새 작성, 근거 업로드/6확인/활성화, 정확한 최종 입력 snapshot과 응답 유실 재시도, 실제 report Worker와 연구ZIP, 철회 후 제공 차단을 검증했다. 관리자/리포트/export 선택360px 가로 넘침 없음, 발급HTML6섹션·인쇄 클리핑 없음·외부 네트워크 요청0을 확인했다.
- 원본12개 bytes/hash는 독립 담당이 모두 재확인했다. S1 검사 명령은 그중 SRC02 DOCX/SRC03 XLSX를 바탕으로8개 자산을 재생성·대조한다. 역사 v3의6개 자산 검사는 별도 명시spec로 통과했다. 미수령G01/G04는 검증된 원본 수에 넣지 않으며 실제 Excel 점수 import는 계속 비활성이다.

- 최종 브라우저 전체 `npm run test:e2e`: **41개 통과, 3.7분, skip0**. 9개 초기 실패를 제품 목록 격리1건과 시험 전제/타이밍 문제로 분리하여 수정하고, 선행 자료가 남은 조합 재검증 뒤 전체 실행에 통과했다. 제품 보호를 약화하거나 시험을 제외하지 않았다. build57 modules·모바일/인쇄 시각 검수·문서 상대링크302개·graft/공백 검사도 통과했다.
- backend 전체679개(1083.446초) 통과 후, 통합에서 재현한 목록 실패격리6개를 포함해 최종 전체685개(780.886초)가 모두 통과했다. 패키지 문서 allowlist의 확장된 기존 시험1개도 별도로 통과했다.

## 2026-10-04 최종 완료 확인

- **완료 범위:** S00~S17의 확정된 구현, 자동·합성 종단 검증, 독립 cold review와 수용 결함 수정, UI/PDF 시각 검수, 설치물 생성과 현재 Windows에서의 새 설치·복구 검증이다. 단계별 commit을 `veluga/s1-integrated-release`에 통합했다. 실제 영상/공급자/물리3PC/깨끗한 OS 실측과 미수령·미승인 정책은 후속 대장을 따른다.
- **최종 전체:** backend `uv run --locked python -X utf8 -m unittest discover -s tests -v` **685개/780.886초/OK**, frontend `npm run test:e2e` **41개/3.7분/skip0**, `npm run build` 통과(57 modules). 기존 Vite 큰 청크 안내 외 실패는 없다. 마지막 코드 변경 뒤 전체를 재검증했으며 문서 변경 때문에 같은 전체 시험을 반복하지 않는다.
- **원본·출력·저장 보호:** 원본12개 hash 일치, S1추출8개 및 역사v3추출6개 대조, 실제 로컬 초기화/백업/복원, 삭제·철회·입력 변경 후 제공 차단, 서버와 브라우저 PDF 전 페이지와 모바일 화면을 확인했다. 실제 AI 호출·연구 승인·고객 발송은 수행하지 않았다.
- **설치물:** 0.3.0 Windows ZIP를 만들고 실제 `install.ps1`, 새 venv, 한글·공백 경로, 로그인→S1 접수→재시작, supervisor 강제 종료/잠금 해제, 기존 환경변수 격리, 손상 ZIP의 설치 전 거절을 검증했다. 이는 현재 Windows 호스트의 독립 폴더 설치이며 새 OS나 두 번째 PC 검증은 아니다. ZIP의 source commit은 `release.json`, 최종 bytes/hash는 동봉 `.sha256`와 아래 배포물 확정 기록을 따른다.
- **독립 패키지 감사:** 최초 설치물의 payload176개/파일별 hash/ZIP sidecar/CRC/경로/중복, 필수 S1 자산, 운영 Markdown30개와 합성 PNG2개, 문서·이미지 링크237개 누락0을 확인했다. 고객 원본·키·런타임·시험은 포함하지 않았다. README 연결 문서 누락 P2를 보완했고, 마지막 DEVELOPMENT의 개발 문서 제외 설명 P3도 실제 포함 범위에 맞췄다.
- **실측 재개:** [후속 대장](K-DOG_실측및확인후속대장_v1.0_20261003.md)의 E01~E10/P01~P12에 필요한 샘플·장비·확인 자료, 실행 방법, 합격 근거를 남겼다. G01/G04 미수령 Excel import와 D06 외부 비교 실제 활성화 등은 승인/자료 없이 켜지지 않는다. 승인되지 않은 기준이나 실제 품질 수치를 만들지 않았다.

## 최종 배포물·PR 확정

- 통합 [PR #40](https://github.com/syleeVeluga/k-dog-proj/pull/40): `veluga/s1-integrated-release` → `main`, draft. S00~S17 단계별 commit을 하나의 검토 가능한 통합 변경으로 제출했다. 현장 배포·자동 병합·고객 발송은 수행하지 않았다.
- 전달 ZIP: `releases/k-dog-v0.3.0-s1-windows-x64-aedab57.zip` (로컬 산출물, 저장소 제외), **2,034,330 bytes**, payload176파일 + `release.json`.
- source commit: `aedab57c8be12cd524d366c9b07cacc82682ed37`, `dirty=false`, 앱0.3.0 / spec20261002. 최종 문서·P3 정정까지 포함한 깨끗한 commit에서 생성했다.
- SHA-256: `ae3d786ddde7df4db6ce1f9ab14631854da8e1bf37fc0893dfc7336c24ec7083`. 같은 이름의 `.zip.sha256`을 함께 전달한다.
- 위 **최종 ZIP 자체**로 `scripts/verify_release.py`를 다시 실행해 exit0을 확인했다. 새 한글·공백 경로와 venv, 실제 설치, 손상 거절, 환경 격리, 로그인/접수/재시작, supervisor 종료 및 S1 필수 자산 모두 통과했다. 외부 AI 호출0이다. 이전 `4cc42b6` ZIP의 검증 결과로 대체하지 않았다.
- 최종 문서 상대링크308개 누락0, `git diff main...HEAD --check` 통과, graft wiring graph3494노드 동기화 확인. 이 절은 ZIP 검증 후 저장소에 남기는 확정 기록이며 ZIP 안 문서는 위 source commit 시점의 스냅샷이다. 이후 변경은 이 확정 기록뿐이며 runtime은 최종 전체 시험 대상과 동일하다.
- 최종 ZIP 독립 재감사도 통과했다. payload176개 hash/sidecar/source commit/CRC/중복/미기재 항목을 확인했고, 이전 ZIP 대비 변경11개는 문서뿐이며 코드·빌드·필수 자산 bytes는 동일하다. DEVELOPMENT 포함/제외 설명 수정도 실제 전달본에 반영됐고 잔여 actionable finding은 없다.


## 2026-10-04 최종 통합 cold review와 퇴역 실행 제거

[통합 Cold Review](K-DOG_통합ColdReview_v1.0_20261004.md)에 CR01~CR08의 수용/거절·보류 사유와 검증을 기록했다. 수용 건만 적용한 제품 코드 commit은 `940cf738c805bce18483cd4276ce91a405691066`이다. 구판 API/Worker/provider/partial import/설정·채점·전처리·리포트/화면을 제거하고 S1 권한 helper의 구판 의존을 끊었다. 원입력 읽기·초기화·동의/삭제·공통 인프라와 현재28문항 설문·역사 추출 fixture는 유지한다. S1 산식/판정 정책 변경은 없다.

- 전체 backend574개/586.821초/OK/exit0/skip0, 전체 브라우저41개/3.6분/exit0/skip0, build52 modules 통과. 제거 전685개의 구판 실행 시험과 이번 수를 구별한다. 중간 fixture·구판URL 기대 수정 및 build와 E2E의 dist 경합 후 최종 전체를 다시 실행했고 실패를 통과로 합산하지 않았다.
- 원본12개 크기/hash 일치, S1추출8개 대조 통과. 사용자의 기존 역사 원본15개 삭제는 commit에 포함하거나 복구하지 않았다. 기존 Git 원본이 있는 별도 작업 트리에서 역사 source/CLI 검증을 포함한 전체 시험을 실행했다.
- 깨끗한 트리의 ZIP `releases/k-dog-v0.3.0-s1-windows-x64-940cf73.zip`,146 payload파일, SHA-256 `b835290bf104a13a0f7e4d9b85165e58d3331104cccecfad9620d8c2c9379e8b`. file hash/CRC·보호 원본/퇴역 실행 미포함과 현재 Windows의 실제 새 경로/venv 설치·손상 거절·환경변수 격리·접수/재시작·supervisor 종료 통과. 이후 이 리뷰 문서 갱신은 ZIP source와 구별한다.
- 2026-10-04 공식 최신 안정판·기존 잠금/호환성 재확인, 새 의존성0·잠금 변경0. 세부 표는 통합 리뷰를 따른다. graft wiring 동기화와 변경 공백·활성 문서 상대 링크 검사 통과.
- 실제 공급자 호출/현장 배포/고객 발송0. 실측·미수령G01/G04·D/G 확인은 후속 대장 경계를 유지한다. 병합 대상은 [PR #40](https://github.com/syleeVeluga/k-dog-proj/pull/40)이며 이번 사용자의 명시 병합 지시를 따른다.


## 2026-10-05 UI·UX 개선 및 독립 cold review

[UI·UX 개선 Cold Review](K-DOG_UIUX개선ColdReview_v1.0_20261005.md)에 모바일 알림·참가자 맥락·촬영 구역/저장 도구의 수정, 합성 화면, 공식 버전 확인과 리뷰 수용 판단을 기록했다. 구현 `2114c9f`: build52 modules, 관련 브라우저9개/52.8초 및 전체45개/4.0분 통과. 신규 빈 촬영 화면360px 높이10,112→3,372px, 독립9화면×4너비에서 가로 넘침0·pageerror0.

독립 Codex CLI0.160.0 review는 actionable regression0, build 및 브라우저7개 통과이며 촬영2개는 리뷰 sandbox FFmpeg 제한으로 미검증이다. 초기 CLI0.145.0 모델 미지원 실패는 리뷰 근거에서 제외했다. 새 수용 수정 요구는 없으며 기존3개 개선을 유지한다. S1 산식/정책/계약·실제 운영자료·D/G 확인 상태는 변경하지 않는다. 사용자가 로컬·원격 병합까지 승인했으며 PR과 완료 SHA는 상세 리뷰의 PR 링크 및 작업 완료 응답을 따른다.
