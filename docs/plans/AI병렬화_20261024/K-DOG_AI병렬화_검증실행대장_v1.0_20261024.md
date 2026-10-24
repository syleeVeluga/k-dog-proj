# K-DOG AI 병렬화 검증·실행 대장

버전: v1.0 · 2026-10-24 · 상태: PA01~PA05 구현·검증·cold review 완료, 후속 PR 진행

상위: [병렬화 계획](K-DOG_AI병렬화계획_v1.0_20261024.md)

## 1. 단계 상태

| PR | 구현 | 자동 검증 | cold review·조치 | 실제 공급자 | 운영 적용 | commit/실제 PR |
| --- | --- | --- | --- | --- | --- | --- |
| [PA01](K-DOG_PR-PA01_실행계약과측정_v1.0_20261024.md) | 완료 | 통과 | 2명 독립 검토, P2 2건 수정·재검토 완료 | 대상 아님 | 기본 1 유지 | [PR #150](https://github.com/syleeVeluga/k-dog-proj/pull/150) 병합 `2b4ffdb` |
| [PA02](K-DOG_PR-PA02_호출예약과공유제한_v1.0_20261024.md) | 완료 | 통과 | 2명 독립 검토, P1 2건 수정·재검토 완료 | PA06 | 직렬 유지 | [PR #151](https://github.com/syleeVeluga/k-dog-proj/pull/151) 병합 `173bd83` |
| [PA03](K-DOG_PR-PA03_항목군병렬실행_v1.0_20261024.md) | 완료 | 통과 | 2명 독립 검토, 추가 결함 없음 | PA06 | 기본 1, 명시 2~4 허용 | [PR #152](https://github.com/syleeVeluga/k-dog-proj/pull/152) 병합 `3275ce8` |
| [PA04](K-DOG_PR-PA04_운영설정과진행표시_v1.0_20261024.md) | 완료 | 통과 | 2명 독립 검토, P2 수정·재검토 완료 | PA06 | 개발자 명시 설정 | [PR #153](https://github.com/syleeVeluga/k-dog-proj/pull/153) 병합 `0abdaa0` |
| [PA05](K-DOG_PR-PA05_장애복구와통합인수_v1.0_20261024.md) | 완료 | backend 904개/skip 3, browser 181개 통과 | 2명 독립 검토, P2 인수 보강·UI 경쟁 수정 재검토 완료 | PA06 | 실측 후보 검증 완료 | `2155849`·`1ab44e5`·`e9a1529` |
| [PA06](K-DOG_PR-PA06_실측과운영적용_v1.0_20261024.md) | 미착수 | 미실행 | 미실행 | 미실행 | 미적용 | — |

## 2. PR별 실행 기록 양식

### PA05 실행 — 2026-10-24

- 기준 `0abdaa0`(PA04 실제 병합), 브랜치 `veluga/pa05-parallel-recovery-acceptance`. AP02~AP07·AP09 통합 인수. 프로세스 종료/복원·정리 소유·혼합 credential 결과·N=4 실제 handler의 최종/리포트/reuse/복원을 연결했다. 최종 종료/복원 시험 2개 42.192초와 리뷰 담당 독립 2개 16.517초 통과.
- `backend/`에서 `uv run --locked python -X utf8 -m unittest discover -s tests -v`: 904개 실행, 901개 통과·3개 명시 skip, 2344.100초. skip은 역사 원본 미확보 2개와 실제 macOS 로그인 Keychain 필요 1개다. 현 Windows의 backend 실패 0. 원본 S1 8개 자산 대조도 통과했고 G01/G04 계산 양식 미수령 대기는 유지한다.
- 최초 `frontend/`의 `npm run test:e2e`: 180개 중 178개 통과·2개 실패, 1022.391초. 접수 초기 로딩 동기화와 상세 열기의 progress 삭제 경쟁을 조사했다. 새 gate 시험은 제품 수정 전 1개 실패를 재현했다. 같은 입력/회차의 진행 요약만 보존하는 수정 및 응답 대기 후 관련 8개 23.8초, build 통과. 두 번째 전체는 180/181 통과·도우미 reload 뒤 generic 404 1개 실패(1004.587초)였다. URL/원인은 미확정이다. 루트 이동 후 메뉴를 여는 시험 준비 변경 뒤 관련 30개 2.0분 통과, trace를 남긴 세 번째 전체는 180/181 통과(944.475초), 판정 조회 지연 glob이 `?purpose=open`을 매칭하지 못한 시험 결함 1개였다. pathname 매칭과 실제 요청 진입 대기를 보강해 관련 14개 38.9초, 최종 전체 181개 894.177초 전부 통과했다. 최종 build도 통과했다. 고정 자료에 repeat-each를 적용한 진단의 중복 409는 인수 표본으로 삼지 않는다.
- 독립 subagent 2명의 복원/정리 P2를 수용 보강했고, 추가 App 경쟁 수정도 양쪽에서 재검토하여 실질 결함이 없었다. 정확한 발견과 인계는 Cold Review 기록을 따른다.
- 최초 ZIP `2155849`에 이어 UI 수정 포함 `e9a1529` 후보 75,276,069 bytes, SHA-256 `b2da86644b4674e3dcb2aec0ca132cfc657e939a2088716f1e36a5a93d10b8f2`를 별도 새 경로에 설치·검증했다. 내장 Python 3.14.8, 외부 도구 없는 PATH, 한글/공백 경로, 무결성·변조 거절, 로그인·업무·재시작·supervisor 종료·재설치·자료/계정 보존·개발자 설정 경계를 통과했다. 실제 다른 PC/새 OS 인수로 확대하지 않는다. 외부 생성형 AI 호출 0회인 설치 시험이다.
- N=4 합성 HTML/PDF 발급 및 전체 PDF 5쪽 PNG/HTML 1440·390px 시각 검수 완료. 출력 hash와 범위는 PA05 상세 기록 참조. 원본 participant 자료는 쓰지 않았다. 로그·배포물·합성 산출물은 저장소 밖 검증 폴더에 보존한다. 공식 PyPI 25개 최신/선택 버전은 이 문서의 배포 의존성 표에 기록했다.

### PA04 실행 — 2026-10-24

- 기준 `3275ce8`, 브랜치 `veluga/pa04-parallel-settings-progress`. 수정 파일: backend run view/domain/Worker 감사, frontend AiSettings/AiRuns/types, 관련 backend/e2e 및 합성 캡처. AP07과 AP09 표시 구현. 최초 시험에서 감사 actor FK 오류를 발견해 실제 실행/재시도 직원으로 수정했다.
- `backend/`에서 `uv run --locked python -X utf8 -m unittest tests.test_parallel_execution_v4.ParallelExecutionTests.test_stop_retry_waits_for_old_children_and_rejects_late_outputs tests.test_settings_v4 tests.test_ai_api_v4 tests.test_run_progress_v4 -q`: 17개 통과, 81.482초. stop/예약 경쟁 8개 4.666초 통과. 최종 program 실제 계수·수습 회귀 2개 1.954초 통과.
- `frontend/`의 `npm run build` 통과. `npm run test:e2e -- tests/analysis-status-v4.spec.ts tests/scoring-ai-v4.spec.ts tests/gemini-key-fallback.spec.ts`: 18개 통과, 2.4분. 기준 commit 별도 빌드의 기존 PC/모바일 캡처 시험 1개도 15.6초 통과. 전후 캡처와 병렬/설정 화면 7개를 PA04 문서에 연결하고 가독성·가로 넘침을 검수했다.
- 2026-10-24 npm 공식 registry 확인: 최신 React 19.3.1, Playwright 1.64.1, Vite 8.3.5, TypeScript 7.0.2. 선택은 기존 pin React/ReactDOM 19.2.8, Playwright 1.63.0, Vite 8.2.2, TypeScript 7.0.2를 유지했다. 이번 표시 변경에 관련 없는 업그레이드를 하지 않았으며 Node 24.22.1이 선택된 Vite `^20.19.0 || >=22.12.0`, Playwright `>=20`과 호환됨을 registry engines/peer 및 실제 build/e2e로 확인했다. [React registry](https://www.npmjs.com/package/react), [Playwright](https://www.npmjs.com/package/@playwright/test), [Vite](https://www.npmjs.com/package/vite), [TypeScript](https://www.npmjs.com/package/typescript). 패키지/lockfile 변경 없음.

### PA03 실행 — 2026-10-24

- 기준 `173bd83`, 브랜치 `veluga/pa03-bounded-score-execution`. 변경: `run_v4.py` 제한 실행기·장벽, `settings_v4.py` 미지원 해제, `worker.py` 늦은 usage 보존, `gemini_v4.py` 요청 계량, benchmark 증거 검증 및 관련 시험. AP02·AP04·AP05 구현. 기본 1과 전체 설정 hash/reuse 조건 유지.
- `backend/`에서 `uv run --locked python -X utf8 -m unittest tests.test_parallel_execution_v4 tests.test_parallel_reservation_v4 tests.test_benchmark_s1 tests.test_run_v4.RunV4Tests.test_restart_after_reservation_preserves_uncertain_attempt_and_call_budget tests.test_run_v4.RunV4Tests.test_restart_recovers_complete_artifact_without_a_second_call -q`: 41개 통과, 32.127초. `uv run --locked python -X utf8 -m unittest tests.test_gemini_v4 tests.test_settings_v4 -q`: 12개 통과, 3.522초.
- 실제 handler의 N=1/N=4 의미 비교 보강 후 `uv run --locked python -X utf8 -m unittest tests.test_parallel_execution_v4 -q`: 5개 통과, 86.329초. 최종 계량 보강 후 `uv run --locked python -X utf8 -m unittest tests.test_benchmark_s1 tests.test_gemini_v4 -q`: 32개 통과, 11.749초. 초기 회귀에서 강제 crash RuntimeError 전파 2건과 미지원 오류문구 기대 1건을 발견해 기존 crash 계약 유지·새 증거 오류문구로 수정했다.
- 독립 subagent 2명 cold review에서 실질 결함 없음. 한 리뷰는 실제 full S1 handler를 N=4로 강제하여 42개 합성 요청·86개 관찰·계산·게시·결과 연결 통과, 다른 리뷰는 관련 회귀 37개 93.167초와 최종 보강 2개 통과를 확인했다.
- 버전 확인은 PA01과 같은 2026-10-24 기록을 따른다. Python `concurrent.futures` 표준 API를 프로젝트 제약 3.14 환경에서 사용하며 신규 패키지/lockfile/DB 열 변경은 없다. 실제 공급자·성능·현장 인수는 PA06 대기다.

### PA02 실행 — 2026-10-24

- 기준 `2b4ffdb`(PA01 실제 병합), 브랜치 `veluga/pa02-call-reservation-limits`. 변경은 `worker.py`, `gemini_keys.py`, 새 `test_parallel_reservation_v4.py`와 문서다. AP02·AP03·AP06·AP09 기반 구현. 파일 소유와 cleanup credential은 요청별 기존 구현을 보존했다.
- `backend/`에서 `uv run --locked python -X utf8 -m unittest tests.test_parallel_reservation_v4 tests.test_run_v4 tests.test_gemini_key_fallback tests.test_gemini_v4 tests.test_owned_run_write -q`: 72개 통과, 249.894초. 당시 시험 모듈에 fixture TestCase를 직접 import해 기존 run 시험이 중복 발견된 것을 수정했다. 수치는 그 실제 실행 건수이며 독립 시험 수로 부풀리지 않는다.
- cold review 수용 수정 후 `uv run --locked python -X utf8 -m unittest tests.test_parallel_reservation_v4 -q`: 7개 통과, 3.611초. 마지막 예산 4자 경쟁·live 동일 branch·동시 recovery·설치 Worker 경계·공유 대기 중지·예약 직전 cooldown 경쟁·동시 fallback 결정을 확인했다. 독립 리뷰 재검토 추가 결함 없음.
- 최종 수정 뒤 `uv run --locked python -X utf8 -m unittest tests.test_run_v4 tests.test_gemini_key_fallback.GeminiFallbackTests tests.test_gemini_v4 tests.test_owned_run_write -q`: 43개 통과, 108.155초. 최초 fallback 시각이 동시 오류로 재설정되지 않는 assertion 보강 후 새 7개 4.603초 통과. 문서 상대 링크 47개와 `git diff --check` 통과.
- 버전/의존성: PA01과 동일 잠금 환경이며 2026-10-24 [Python threading](https://docs.python.org/3.14/library/threading.html), [Gemini 프로젝트별 rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)를 확인했다. 최신/선택 버전은 위 PA01 기록과 동일, 설치·패키지·lockfile 변경 없다. 계정 quota는 추정하지 않았으며 실제 키 접근·프로젝트 관계 확인은 PA06이다.

### PA01 실행 — 2026-10-24

- 기준 `0335f60`, 브랜치 `veluga/pa01-execution-contracts`. Graft 호출 관계를 확인하고 설정/실행 계약, S1 회차 계량, benchmark 및 관련 회귀만 수정했다. AP01 구현, 실행 순서 유지, 외부 공급자 호출 0회, 운영 활성 설정 변경 없음.
- 검증 환경: Windows, Python 3.14.2, Pydantic 2.13.5(backend 잠금 환경). `backend/`에서 `uv run --locked python -X utf8 -m unittest tests.test_settings_v4 tests.test_run_v4 tests.test_benchmark_s1 tests.test_report_runs_v4 -q`: 75개 통과, 178.589초(최초 회귀). cold review 수용 수정 후 `uv run --locked python -X utf8 -m unittest tests.test_settings_v4 tests.test_run_v4 tests.test_benchmark_s1 -q`: 54개 통과, 72.707초. `git diff --check` 통과.
- strict N, 과거 serializer/hash, 새 판본, 실행 불변성·reuse·중지/복구 기존 회귀, 실패 계량, 겹친 구간의 union/span, N별 반복·4카메라·혼합 입력 거절·부분 실패 제외를 확인했다. 상세 발견/조치는 [Cold Review](K-DOG_AI병렬화_ColdReview_v1.0_20261024.md#pa01-구현-cold-review--2026-10-24) 참조.
- 2026-10-24 버전 확인: Python 최신 안정 3.15.1([공식 릴리스](https://www.python.org/downloads/release/python-3151/)), Pydantic 최신 안정 2.14.1([PyPI](https://pypi.org/project/pydantic/), [변경점](https://docs.pydantic.dev/latest/changelog/)). 프로젝트 Python `>=3.14,<3.15`와 잠금 Pydantic 2.13.5를 유지했다. 이번 변경에 런타임/의존성 업그레이드는 불필요하며 [직렬화](https://docs.pydantic.dev/latest/concepts/serialization/) API와 strict 필드를 잠금 환경에서 검증했다. 신규 패키지·lockfile 변경 없음. Python 스레드 [공식 API](https://docs.python.org/3.14/library/concurrent.futures.html)는 PA03에서 적용한다.
- 새 실측 참조가 사용자 지정 Downloads에 존재하고 원본 폴더가 있는 것은 확인했다. 실제 처리·유료 실험·발급은 PA06에서 수행하며 현재 인수 실측 수치는 모두 대기다.

각 PR 착수 후 아래 항목을 해당 PR 기록에 추가한다. 미실행 항목을 통과로 채우지 않는다.

- 기준 commit/브랜치, 선행 PR 병합 확인, 실제 변경 파일 및 callers 영향
- 구현한 AP 요구사항과 구체적 동작
- 라이브러리/API 확인일, 최신 안정판·선택 버전·사유·공식 출처, 의존성 변경 여부
- 시험 환경·정확한 명령·건수·경과시간·실패·수정·재검증 결과
- 리뷰 발견사항별 수용/보류/거절 사유와 후속 책임 범위
- 실제 PR/commit, 기본값·활성 상태, 되돌리기 검증
- 남은 자료·실측·정책 경계

## 3. 실제 성능 기록 양식

대상: `PA06-20261024-B`(2026-10-24 사용자가 새로 지정한 자료). 실제 경로/목록은 저장소 밖 사용자 지정 Downloads의 `K-DOG_AI병렬화_실측대상_20261024.json` 참조. 이전 96분 사례를 대조군으로 재사용하지 않는다. 아래 표의 표본 수는 AI 구간 완료와 PDF 발급 완료를 각각 기록한다.

| 비교 조건 | 시작/유효 AI/발급 표본 수 | 코드/설정 hash | 실제 최대 동시성 | AI 벽시계 | PDF까지 벽시계 | 429/재시도 | 호출/토큰/확인 비용 | 과금 미확인 | 판단 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 직렬 N=1 | 0/0/0 | — | — | 미측정 | 미측정 | — | — | — | 대기 |
| 병렬 N=2 | 0/0/0 | — | — | 미측정 | 미측정 | — | — | — | 대기 |
| 병렬 N=3 | 0/0/0 | — | — | 미측정 | 미측정 | — | — | — | 대기 |
| 병렬 N=4 | 0/0/0 | — | — | 미측정 | 미측정 | — | — | — | 대기 |

원본/전처리 대응, 모델·prompt·FPS·추론 한도, cold/reuse, 네트워크/기기, 실행 순서와 실제 시각은 비식별 실측 요약에 연결한다. 참가자 원본과 상세 응답은 저장소 밖에서 보관한다. 기존 약 96분은 한 사례의 참고 관측이며 위 새 대조군의 측정값으로 채우지 않는다.

각 조건의 실패/부분 실패/중지 수·실패까지 시간·재시도 포함 벽시계·미발급 사유를 함께 기록한다. 성공 표본만 남겨 실패율을 숨기지 않는다. 비교 리포트는 누적/외부 비교 옵션을 끄고 반복 실측의 출처를 남긴다. 세부 기준은 PA06과 [Cold Review CR01~CR04](K-DOG_AI병렬화_ColdReview_v1.0_20261024.md)를 따른다.

### 지정 자료의 최종 리포트 완료 기록

| 항목 | 상태/근거 |
| --- | --- |
| 원본 경로·목록 확인 | 폴더 및 파일 11개 존재 확인, 상세는 외부 참조 |
| 원본 hash·영상/CSV·음성·설문·동기화 검증 | 미실행 |
| 입력 등록·전처리 | 미실행 |
| AI 분석·계산·애착·최종본 고정 | 미실행 |
| 전달용 run/final/report 연결 | 미선정 |
| HTML/PDF 발급·출력 hash 확인 | 미실행 |
| HTML 열람·PDF 전체 페이지 검수 | 미실행 |
| 원본 hash 재확인·사용량/fallback/정리 기록 | 미실행 |
| 전 과정 실행 보고서·실측 원장 전달 | 미작성 |

각 비교 run의 입력→AI→최종본→리포트 연결을 보존한다. 실제 발급되지 않은 결과에는 PDF 완료 시각을 기록하지 않는다. 전달용 최종 리포트의 발급·검수까지 끝나야 해당 완료 항목을 통과로 바꾼다.

## 4. 계획 문서 검토

2026-10-24 계획 검토 범위: 기준 코드와 실행/인수 대장 확인, 6개 PR 선행 관계, AP01~AP08 담당, 원자적 예약·후속 장벽·늦은 응답·정리·설정 hash 보존·단일 Worker 경계·실측 분리 여부. 문서 링크/파일 경로/공백 검증 결과는 실제 확인 후 아래에 기록한다.

- 코드 구현·시험·실제 공급자 병렬 호출: 미실행.
- 운영 설정·이미 발급한 최종본: 변경 없음.
- 문서 검증: 8개 파일의 상대 링크 36개가 모두 존재함을 확인했다. 신규 파일을 직접 검사하여 줄 끝 공백·문자 깨짐이 없음을 확인했고 `git diff --check`를 통과했다. 추적되지 않은 신규 파일은 이 명령의 대상이 아니므로 직접 검사 결과를 함께 기록한다.
- 경로 검토에서 PA01 초안의 존재하지 않는 `domain/settings_v4.py` 참조를 제거하고 실제 `backend/app/settings_v4.py`로 정리했다. PR 선행 관계는 PA01→PA06 단일 순서이며 AP01~AP08 모두 담당 PR가 있다.

### 2026-10-24 예비키 계획 보완

사용자가 예비키 설정 예정임을 확인하여 `gemini_keys.selection/select/fallback_reason/request_fallback`과 `Worker.fail`의 현재 동작을 대조했다. 기존 계획의 일반적인 전환·공유 대기 표현을 PA02의 FB01~FB11로 구체화하고 AP09를 추가했다. 오류별 전환/비전환, 예비키 자체 실패, 동시 실패와 진행 중 주키 성공, 예산 소진, 키 교체·복원, 별도 run 경계, 화면 표시와 실측 구분을 PA04~PA06에 연결했다. 구현·키 등록·외부 호출은 수행하지 않았다.

보완 후 상대 링크 39개 대상과 줄 끝 공백 검사를 통과했다. 신규 fallback anchor는 PA02의 해당 제목과 대조했다. AP09의 자동 장애 검증도 운영 적용 선행 조건에 포함했다.

### 2026-10-24 실측 대상·완료 범위 변경

사용자 지정 새 자료를 PA06-20261024-B로 연결하고 전처리부터 최종 HTML/PDF 발급·검수·전 과정 실행 보고서까지 필수 산출물로 명시했다. 기존 사례의 결측 조건을 복사하는 문구를 제거하고 새 자료에서 다시 검증하도록 수정했다. 이번 변경은 계획 수정과 파일 존재 확인이며 분석 실행이나 리포트 발급 완료가 아니다.

### 2026-10-24 Cold Review와 계획 병합

[Cold Review](K-DOG_AI병렬화_ColdReview_v1.0_20261024.md)에서 4건을 발견해 모두 수용했다. 4카메라/N별 실측 계약, 즉시 중지와 자식 수습 경계, 실패 포함 성능 판정, 실측 리포트 비교 옵션·출처를 계획에 반영했다. 앱 구현·의존성·운영 DB·기존 결과는 변경하지 않았다. 계획 문서 PR만 병합 대상으로 삼는다.

재검증: 문서 9개, staged/기존 추적 파일을 대상으로 하는 상대 링크 45개와 anchor 3개, PA01→PA06 선행 관계, AP01~AP09·FB01~FB11 연결을 통과했다. 외부 원본 매핑을 확인했고 참가자 이름/원본 경로/키는 staged 문서에 없었다. 신규 파일 직접 공백 검사와 `git diff --cached --check`를 통과했다. 실행 코드 변경이 없어 backend/e2e·공급자 호출은 수행하지 않았다.

## PA05 배포 의존성 확인 — 2026-10-24

공식 PyPI registry 25개를 실제 조회했다. 선택 버전은 기존 프로젝트/uv.lock의 pin이며 이번 병렬화의 API·배포 재현성을 유지하기 위해 관련 없는 업그레이드를 하지 않았다. 설치한 배포 후보의 Python 3.14.8에서 시작·실제 업무·재시작을 검증했다. 상세 registry 원장은 저장소 밖 검증 폴더에 보존한다.

| 패키지·공식 registry | 최신 안정판 | 선택 pin |
| --- | --- | --- |
| [annotated-doc](https://pypi.org/pypi/annotated-doc/json) | 0.0.5 | 0.0.5 |
| [annotated-types](https://pypi.org/pypi/annotated-types/json) | 0.8.0 | 0.8.0 |
| [anyio](https://pypi.org/pypi/anyio/json) | 4.15.1 | 4.15.1 |
| [certifi](https://pypi.org/pypi/certifi/json) | 2026.10.23 | 2026.7.22 |
| [cffi](https://pypi.org/pypi/cffi/json) | 2.1.1 | 2.1.1 |
| [charset-normalizer](https://pypi.org/pypi/charset-normalizer/json) | 3.5.2 | 3.5.1 |
| [click](https://pypi.org/pypi/click/json) | 8.5.0 | 8.5.0 |
| [cryptography](https://pypi.org/pypi/cryptography/json) | 50.0.2 | 50.0.2 |
| [et-xmlfile](https://pypi.org/pypi/et-xmlfile/json) | 2.0.0 | 2.0.0 |
| [fastapi](https://pypi.org/pypi/fastapi/json) | 0.162.0 | 0.141.1 |
| [h11](https://pypi.org/pypi/h11/json) | 0.16.0 | 0.16.0 |
| [httpcore](https://pypi.org/pypi/httpcore/json) | 1.0.9 | 1.0.9 |
| [httpx](https://pypi.org/pypi/httpx/json) | 0.28.1 | 0.28.1 |
| [idna](https://pypi.org/pypi/idna/json) | 3.20 | 3.19 |
| [openpyxl](https://pypi.org/pypi/openpyxl/json) | 3.1.5 | 3.1.5 |
| [pillow](https://pypi.org/pypi/pillow/json) | 13.0.0 | 12.3.0 |
| [pycparser](https://pypi.org/pypi/pycparser/json) | 3.12 | 3.0 |
| [pydantic](https://pypi.org/pypi/pydantic/json) | 2.14.1 | 2.13.5 |
| [pydantic-core](https://pypi.org/pypi/pydantic-core/json) | 2.50.1 | 2.46.5 |
| [pypdf](https://pypi.org/pypi/pypdf/json) | 6.21.2 | 6.19.0 |
| [reportlab](https://pypi.org/pypi/reportlab/json) | 5.1.0 | 5.0.1 |
| [starlette](https://pypi.org/pypi/starlette/json) | 1.9.0 | 1.6.0 |
| [typing-extensions](https://pypi.org/pypi/typing-extensions/json) | 4.16.0 | 4.16.0 |
| [typing-inspection](https://pypi.org/pypi/typing-inspection/json) | 0.4.4 | 0.4.4 |
| [uvicorn](https://pypi.org/pypi/uvicorn/json) | 0.54.0 | 0.52.4 |
