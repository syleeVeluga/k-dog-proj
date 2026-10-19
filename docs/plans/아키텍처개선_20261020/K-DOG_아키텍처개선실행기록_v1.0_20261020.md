# K-DOG 아키텍처 개선 실행 기록

버전: v1.0 · 2026-10-20 · 기준: `main / f58b21e` · 상태: **AC01~AC05 구현·전체 검증 완료**

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 사용자 `/goal`은 AC01~AC05 전체 구현과 완료 검증이다. 최초 문서 PR #106의 계획 검증과 이번 제품 검증을 구분한다. 시작 작업트리에는 사용자 소유의 untracked `.agents/`와 `.claude/skills/improve-codebase-architecture/`가 있었으며 변경·커밋하지 않는다.

## 1 구현과 interface

| PR | 실제 적용 | 보존·검토 결과 |
| --- | --- | --- |
| AC01 | `segmentsCsv.applySegmentsCsvDraft(record, videos, text, filename, hash)` → 새 기록·요약 또는 기준 camera 부재 시 null | parser 유지. 미실시·누락·수동 사실·offset 순서·출처/hash 중복·기존 요약 의미를 순수 module이 소유. 화면은 원 bytes 읽기·strict UTF-8·hash·비동기 guard·change/save 소유 |
| AC02 | `useExecutionTracking(context, revision, initial, adapter)` → 추적 상태·reload/request/select | 두 실제 adapter 사용. pending 저장·선택 수명·조회/제어 세대·단일 타이머·visibility/unmount·늦은 결과 차단은 hook 소유. DTO/URL·기존 저장 payload·부분 성공·업무 poll 판정은 adapter 소유 |
| AC03 | `analysis.owned_write(store, row, *, conflict_detail)` → 같은 `(db, current)` | Store.connect의 BEGIN IMMEDIATE~commit/rollback/close 전체를 소유. Worker 예약·복구 실패·새 attempt·실패 기록 네 구간 전환. 예약 후 credential 실패는 body에서 보관하고 commit 뒤 raise |
| AC04 | adopt·S1 finish·애착 process 완료·AI publish·report finish 다섯 쓰기 전환 | source/output/asset stamp·최신 attempt·원 step token·기본 결과/시트/감사·발급 pointer/감사는 기존 같은 body에 유지 |
| AC05 | 전체 회귀·요구 추적·시각 증거·잔존 분류·문서/그래프 점검 | 아래 실제 실행 결과로 판정. 공급자·현장 인수와 구별 |

Deletion test: AC01 module을 제거하면 화면에 초안 규칙이 되돌아오고, AC02 hook을 제거하면 두 화면에 pending/응답 순서/타이머가 재분산된다. AC03/04를 제거하면 아홉 쓰기 구간에 트랜잭션·점유·계정 재검사가 돌아온다. SQL 순서를 이름만 바꾼 helper, 새 provider/router/repository, 상태 관리 의존성은 추가하지 않았다.

## 2 공식 버전·호환성 확인

확인일 **2026-10-20**. 공식 문서·릴리스·npm/PyPI registry를 직접 조회했다. 설치·manifest·lockfile 변경은 없다. 최신판 자동 전환을 하지 않은 이유는 기존 잠금 환경과 제품 계약을 보존하는 구조 개선이라는 이 작업의 명시 범위다.

| 대상 | 최신 안정 / 선택 | 확인 근거·호환성 |
| --- | --- | --- |
| Python | 3.15.0; 3.14 계열 3.14.8 / 기존 실행 3.14.2 | [공식 배포](https://www.python.org/downloads/). 프로젝트 `>=3.14,<3.15` 유지; 런타임 교체는 범위 밖. 표준 [contextlib](https://docs.python.org/3.14/library/contextlib.html)·[sqlite3](https://docs.python.org/3.14/library/sqlite3.html)의 예외 전파·transaction/close 계약 확인 |
| Node.js | Current 26.12.0; 24 LTS 24.22.0 / 실행 24.13.0 | [공식 release registry](https://nodejs.org/dist/index.json). 프로젝트 Node 24 환경과 npm engine 조건 유지, 런타임 교체 없음 |
| FFmpeg / ffprobe | 9.0.2; 8.1 계열 8.1.3 / 실행 8.1.1 gyan full build | [공식 다운로드/릴리스](https://ffmpeg.org/download.html), [CLI 문서](https://ffmpeg.org/ffmpeg.html). 기존 합성 lavfi·libx264·probe 경로 유지; 배포용 별도 최소 build를 새로 발행하지 않음 |
| React / React DOM | 19.3.1 / 19.2.8 | [공식 버전](https://react.dev/versions), [React registry](https://registry.npmjs.org/react/latest), [DOM 선택판](https://registry.npmjs.org/react-dom/19.2.8). DOM peer `react ^19.2.8` 충족. [effect cleanup](https://react.dev/reference/react/useEffect) 사용, 19.3 새 interface 불사용 |
| TypeScript | 7.0.2 / 7.0.2 | [공식 배포 안내](https://www.typescriptlang.org/download/), [registry](https://registry.npmjs.org/typescript/latest). Node >=16.20; 실제 Node 24.13.0 충족. 기존 compiler/options 유지 |
| Vite | 8.3.4 / 8.2.2 | [릴리스·지원 범위](https://vite.dev/releases), [선택판 registry](https://registry.npmjs.org/vite/8.2.2), [공식 실행 안내](https://vite.dev/guide/). Node `^20.19 || >=22.12` 충족. 8.2는 중요 수정 지원 대상, plugin·optional peer 신규 도입 없음 |
| Playwright test | 1.64.1 / 1.63.0 | [릴리스](https://playwright.dev/docs/release-notes), [선택판 registry](https://registry.npmjs.org/@playwright%2Ftest/1.63.0), [assertion interface](https://playwright.dev/docs/test-assertions). Node >=20 충족; 기존 Chromium·route/Promise fixture 유지 |
| React 타입 | 19.3.0 / React 19.2.18·DOM 19.2.7 | [React registry](https://registry.npmjs.org/@types%2Freact/latest), [DOM registry](https://registry.npmjs.org/@types%2Freact-dom/latest). 기존 React 19.2 타입 조합 유지 |
| FastAPI | 0.148.0 / 0.141.1 | [공식 릴리스](https://fastapi.tiangolo.com/release-notes/), [registry](https://pypi.org/pypi/fastapi/json). Python >=3.10. 최신판의 omitted default 검증 변경을 이번 추출에 섞지 않음; 기존 HTTPException 사용 유지 |
| Pydantic | 2.14.1 / 2.13.5 | [공식 변경 이력](https://pydantic.dev/docs/validation/latest/get-started/changelog/), [registry](https://pypi.org/pypi/pydantic/json). Python >=3.10. domain 모델·validator·직렬화 변경 없음 |
| 시험·기존 실행 의존성 | httpx 0.28.1/0.28.1, uvicorn 0.54.0/0.52.4, openpyxl 3.1.5/3.1.5, reportlab 5.0.1/5.0.1, Pillow 13.0.0/12.3.0, cryptography 50.0.2/50.0.2, pypdf 6.21.1/6.19.0 | [httpx](https://pypi.org/pypi/httpx/json)·[uvicorn](https://pypi.org/pypi/uvicorn/json)·[openpyxl](https://pypi.org/pypi/openpyxl/json)·[reportlab](https://pypi.org/pypi/reportlab/json)·[Pillow](https://pypi.org/pypi/pillow/json)·[cryptography](https://pypi.org/pypi/cryptography/json)·[pypdf](https://pypi.org/pypi/pypdf/json) 공식 registry의 최신판·Requires-Python 확인. 기존 잠금판의 사용 방식 유지; 이 PR에서 해당 interface를 수정하지 않음. 전체 회귀로 기존 환경 확인 |

원본 registry는 확인 시점의 값이며 이후 `/latest` 응답은 달라질 수 있다. 최신판을 설치하거나 호환성 시험한 것으로 표시하지 않는다. build의 기존 500kB chunk 안내는 성능 경고이며 통과와 별도 기록한다.

## 3 시험 실행

| 실행 | 실제 결과 |
| --- | --- |
| 변경 전 프런트 build | 통과; 기존 chunk 경고 |
| 변경 전 AC01: `npm run test:e2e -- segments-csv.spec.ts recording-v4.spec.ts recording-split-v4.spec.ts` | 16 passed / 52.3초 |
| 변경 전 AC02: 계획의 관련 7 spec | 26 passed / 2.9분 |
| 변경 전 backend: run/fallback/actor/attachment/report 5모듈 | 74 tests / 309.026초 / OK |
| 변경 후 AC01 최종 | §6 세 spec 18 passed / 39.4초; 지연 read/hash·새 CSV·기준 영상·해제·UTF-8·수동 입력·기존 저장/확정 포함 |
| 신설 owned transaction 7건 | 7 tests / 2.072초 / OK; commit/rollback/close·현재 claim/lease/actor/revision·예약 commit·중복 예약·once 오류 종료/새 점유 보존 |
| 변경 후 AC02 국소 | 계획의 관련 7 spec 33 passed / 2.9분. 같은 회차 전처리 revision 추가 1 passed / 9.7초 |
| 변경 후 AC04 국소 | 계획의 10모듈 111 tests / 384.546초 / OK |
| 전체 E2E 1차 | 149건 중 148 passed / 12.3분, CSV 모바일 메뉴 fixture 1 timeout. 제품 변경 없이 회차 메뉴를 먼저 열도록 시험 한 줄 수정; 수정 후 해당 1 passed / 14.1초; 이후 최종 전체150건 통과 |
| 저장 실패·CSV 국소 최종 | 2 passed / 17.8초; 저장 오류 시 POST 0·오류 표시·대기 해제, 390/1440 CSV 확인 |
| backend 전체 최종 | 795 tests / 1352.898초 / OK (skipped=2); 역사 v3 로컬 원본 미확보에 따른 2건 skip, 현재 S1 source check는 별도 통과 |
| 프런트 전체 최종 | `npm run test:e2e`: 150 passed / 9.8분. 제품/시험 동결본으로 전체 성공. 후속 문서 검토의 AC-T09 직접 주입 3건은 제품 변경 없이 별도 실행하여 3 passed / 21.5초. 전체 150건과 별도 3건의 합집합 153건 |
| 최종 build | `npm run build`: 통과; `index-aUrPF5jl.js`, 기존 500kB chunk 경고 유지 |
| S1 source check | `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check` exit 0; 카탈로그/규칙/매핑 8자산 source verified. G01/G04 실물 workbook 미수령·주소/산식 검증 대기·Excel import 비활성은 유지 |

최종 전체 E2E 중 Windows asyncio 연결 종료에서 WinError 10054 한 차례가 출력됐고 모든 시험은 성공했다. 초기 실패는 제품 성공 기록과 구분한다. AC01 지연 시험은 disabled fieldset에서 편집을 시도해 timeout했고, 이미 대기 중인 편집 이벤트를 제어된 DOM fixture로 재현하도록 수정했다. 같은 textarea의 채워진 label 문자열에 의존한 선택도 role 기반으로 수정했다. 새 backend 시험은 감사 테이블명 오기로 실패했고 실제 `changes`를 사용하도록 수정했다. imported TestCase의 중복 수집을 module import로 제거했다. 제품 보호 조건·예상값을 낮추지 않았다.

## 4 독립 cold review와 조치

사용자가 이 세션에서 프런트·백엔드 하위 에이전트 검토를 명시 허용했다. reviewer는 구현과 독립적으로 diff·계획·Graft 호출 관계를 검토하고 제어된 회귀를 추가했다.

| ID | 발견 | 판단·수정·재검토 |
| --- | --- | --- |
| AC-CR01 / P2 | AI 조회 중 사용자가 바꾼 선택을 captured snapshot의 selectedId가 덮을 수 있음; 추출 회귀 | 수용. 조회 시작 이후 선택이 바뀌면 조회 결과의 선택 변경만 배제하며 accessLost forget은 우선. held GET→선택→응답·storage 시험 추가. reviewer 해결 확인 |
| AC-CR02 / P2 | 새 전처리 POST의 접수·거절 시 이전 completed execution을 다시 보일 수 있음; 추출 회귀 | 수용. accept에서 이전 상세 제거, 표시할 상세의 execution_id와 현재 tracking 일치 검사. held 상세 시험 추가. reviewer 해결 확인 |
| AC-CR03 / P2 | 접근 상실 정리 뒤 대기 POST 성공이 state/storage를 복원할 수 있음; **기존에도 있던 경쟁 조건**으로 AC02 명시 인수 조건과 충돌 | 수용. forget이 poll sequence·제어 generation·busy/loading/control·pending/선택/storage를 함께 무효화. 자동 재POST 없이 늦은 success/catch/finally 차단. 원인과 영향을 구조 추출 회귀와 구별. held POST→403 정리→늦은 성공 시험 추가. reviewer 해결 확인 |
| AC-CR04 / P2 | pending storage 저장이 request try 밖에 있어 저장 실패 시 AI busy/working이 해제되지 않음; 기존 AI는 operation 안에서 catch/finally 수행 | 수용. 저장을 try 안, POST 앞에 유지해 저장 실패 시 호출 0·오류 표시·busy/control 정리. 독립 reviewer 확인 및 저장 예외 주입 시험 보강 |
| AC01 | 추출된 merge·문구·배열 순서·요약·입력 불변 | actionable 발견 0건 |
| AC03/04 | transaction·복구·게시·감사 | actionable 회귀 0건. reviewer 보강 6건 포함 owned/scoring 29 tests / 10.165초 / OK |

프런트 reviewer는 초기 세 수정 후 source 재검토에서 남은 actionable 발견 0건을 확인했다. 새 공유 403/404/503 시험은 historical read-only 상세에서 없는 실행 버튼을 찾던 fixture 오류를 current writable 문맥으로 수정했으며, 3건 모두 18.0초에 통과했다. 추가 9개 사례는 AI 선택/부분 실패/접근 상실/저장 실패 4건과 전처리 이전 상세/공유 403·404·503/같은 회차 revision 5건이다. 실행 성공 여부는 §3과 AC05의 실제 결과를 따른다.

백엔드 reviewer는 이전 attempt 원 token/최신 attempt, AI 동일 결과 중복·상이한 문서·전용 계정 충돌·최종 actor 변경, AI 및 report 감사 실패 rollback과 불변 bytes 회복을 직접 보강했다. 실제 SQLite와 기존 계산/게시 경로를 사용하며 공급자 호출은 없다.

## 5 의도적으로 남긴 경로와 계약

Graft exhaustive `claim_token|lease_expires_at|check_access` 검색은 12개 파일·44개 symbol·80개 occurrence를 확인했다. 정상 쓰기는 AC03 네 구간과 AC04 다섯 구간이 owned_write를 사용한다. 나머지를 0건으로 지우는 작업은 하지 않았다.

| 분류 | 잔존 위치·이유 |
| --- | --- |
| 새 점유 획득 | analysis.claim: queued/retry_wait/만료 실행을 새 token으로 획득; live 소유권 전제와 다름 |
| guard/heartbeat | analysis.guard·worker.heartbeat·Worker.check: 별도 연결의 유효성 확인과 lease 갱신. 이후 내구 쓰기는 owned_write에서 다시 검증 |
| 오류 종료 | Worker.once: actor/access 실패도 token/status 조건으로 마무리하고 미확인 과금을 보존. 정상 access 검사를 다시 요구하면 실패 기록을 남길 수 없음 |
| 사용자 action/admission | run/report enqueue/action·attachment enqueue/stop: 활성 worker가 아닌 실제 업무 계정의 명시 요청. 공유 접근·retry actor·낙관 충돌 유지 |
| 산출물 검증 | analysis.step_output/write_output: 원 step token·run/step/input/config/hash·불변 경로 검사. 새 run claim으로 원 step token을 치환하지 않음 |
| 전처리·업로드 | preprocess_v4·preprocess_executions_v4·uploads: 별도 실행/receipt 테이블·토큰·원본 파일 수명. runs의 점유 쓰기와 통합하지 않음 |
| reset/조회 | reset_s1 전환 정리·run_v4._progress 상태 투영·domain 저장 필드: 정상 Worker mutation과 다른 책임 |
| 화면 | ReportRunsV4·PreprocessExecutionsV4 목록은 범위 밖. 기존 parent React key와 `api.ts` 유지 |

Python 동적 호출은 Worker.process의 s1/report_v4/attachment_v4 dispatch, run/report process의 worker.stage와 scoring_ai_v4.work→publish를 직접 대조했다. JSX 호출은 ScoreSheetsV4와 pages/Preprocessing의 username/case/session/지정 execution key를 exhaustive 검색으로 보완했다.

## 6 인수 범위와 남은 후속

DB migration·schema·HTTP 경로/DTO·저장 JSON·고객 카탈로그·산식·모델·프롬프트·lockfile 변경 없음. 원점수 이관·구판 실행·옛 소유/동의/삭제 차단을 복구하지 않는다. 실제 행위자·원평가자·독립 제출·불변 파일/판본·발급 bytes·예산/사용량은 회귀 대상이다.

실제 공급자 호출·참가자 데이터·운영 DB 처리·새 ZIP 발행/고객 배포·현장 3PC 검수는 이번 범위에 없다. [기존 실측·확인 후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)의 미수령 기준·교수 검토·실공급자 품질·물리 장비 실측을 완료 처리하지 않는다. 로컬 S1 source check 통과와 G01/G04 실물 미수령은 별개다.

## 7 AC-T01~T22 실제 시험 추적

아래 파일·시험 이름은 실행된 국소 및 전체 suite에 연결한다. “통과”는 해당 자동/합성 조건의 결과이며 실측 인수가 아니다. backend 전체 795건과 frontend 전체 150건은 통과했으며, 후속 AC-T09 직접 주입 3건도 21.5초에 통과했다.

| ID | 실제 관찰 시험·연결 |
| --- | --- |
| AC-T01 | `segments-csv.spec.ts`의 샘플/BOM·CAM3/열 순서·누락/오류 등 기존 parser 6건 |
| AC-T02 | 같은 파일 `초안은 미실시·누락·수동 사실과 기존 offset 순서를 보존하고 입력을 변경하지 않는다` |
| AC-T03 | 같은 파일 `초안 출처는 hash로 중복을 막고 기준 영상·카메라 없는 연결을 임의로 채우지 않는다` |
| AC-T04 | `recording-v4.spec.ts` 첫 CSV 종단: read/hash Promise gate·일반 편집·새 CSV·기준 영상·해제·잘못된 UTF-8. 오래된 결과/busy/error 배제, 기존 입력/summary 유지 |
| AC-T05 | 같은 CSV 종단의 4영상 등록·초안·422 확정 거절·수동 보완·확정; 같은 파일 actual recording 시험의 revision 409·독립 기존 입력 보존 |
| AC-T06 | `analysis-status-v4` 같은 회차 입력판/다른 계정 늦은 응답, `preprocess-executions-v4` 같은 회차 입력판 변경·이전 회차 지정 실행·메뉴 이탈 |
| AC-T07 | 두 spec의 `응답 유실`·일시 미발견·재진입/새로고침; 원 request 조회·자동 재POST 0 |
| AC-T08 | 두 spec의 늦은 running 조회/제어 우선·종료 후 조회 안정·메뉴 이동 정리, AI 조회 중 명시 선택 유지 |
| AC-T09 | sessionStorage 복원·접근 상실 정리, AI held POST→403→늦은 성공 복원 차단·storage 저장 실패 시 POST 0/대기 해제; 전처리 지정 상세404 정리. 후속 `손상된 AI/전처리 접수 JSON` 2건 및 `조회로 확인한 전처리 접수는 늦은 POST 409…` 1건: 손상 복원·미접수 거절 정리·이미 조회한 접수/원요청 보존·완료 pending만 제거 |
| AC-T10 | AI 준비 조회 실패/목록 성공; 전처리 공유403/404/503·지정 상세 성공 보존 및 상세404 정리; `preprocess-v4` 명시 재사용 |
| AC-T11 | `test_owned_run_write`: changed_claim/stopped/expired/missing·current_actor_and_revision; `test_execution_actor_v4` actual retry actor |
| AC-T12 | owned `credential_failure_commits_reservation_and_selection_evidence`·`reservation_is_once_per_attempt`; `test_run_v4` schema repair/reserved caps와 `test_gemini_key_fallback` attempt/call limits |
| AC-T13 | `test_run_v4` restart reservation/uncertain·schema repair·3attempt, `test_gemini_key_fallback` primary/backup/remaining calls·backoff·usage |
| AC-T14 | owned commit/body_failure/connection close·once access failure/new claim; 기존 heartbeat/claim/stop 회귀 |
| AC-T15 | owned `recovery_keeps_original_step_token_and_rejects_older_attempt`; run `restart_recovers_complete_artifact_without_a_second_call` |
| AC-T16 | owned claim/actor/revision, scoring publication `actor_revoked_after_file_checks_cannot_publish`; run/report stop·attachment opinion/actor/media 변경·fallback late token/lease |
| AC-T17 | run `file_changed_after_validation_cannot_be_adopted`; report `mutated_output_between_validation_and_adoption_is_rejected`·policy asset stamp·fallback pending input hash |
| AC-T18 | `AiPublicationV4Tests`: identical idempotency/different document, AI account collision, audit failure account/sheet/result rollback·불변 파일 retry |
| AC-T19 | owned report issue audit rollback/bytes recovery; run 부분 실패·attachment 성공/보류·report 발급; `test_execution_actor_v4` AI publish/report issue actual retry actor |
| AC-T20 | `recording-v4` 4영상/CSV/확정 → `preprocess-v4` clips/reuse → `test_gemini_acceptance`, `test_report_acceptance_v4` 실제 Worker+fake REST·완료 의견·최종본·HTML/PDF·고정 hash·재사용/복원. 하나의 거대 E2E로 합치지 않고 기존 실제 조립 경로를 사용 |
| AC-T21 | 양 화면 응답/문맥 회귀와 `test_run_v4` 중단/회복·호출 상한, `test_gemini_key_fallback` 실제 Worker 전환·usage/uncertain; §5의 전환9/의도적 잔존 전수 분류 |
| AC-T22 | `test_shared_outputs_v4`, `test_business_access_v4`, `test_execution_actor_v4`: 공유 조회/재시도/발급·독립 provenance·기존 bytes·실제 actor. `test_deployment_v4`, `test_reset_s1`, `test_packaging`: attachment가 있는 정상 재시작/반복 초기화·패키징. 운영 DB 미사용 |

AC05 시작 시 제품·시험 17개 변경 파일의 정규화 텍스트 SHA-256을 OS 임시 파일에 고정했다. 제품 소스는 최초 `78f4695`로 고정했다. 전체 E2E 1차에서 새 CSV 캡처가 390px에 남긴 상태로 접힌 회차 메뉴 안의 버튼을 클릭하던 fixture 1건이 timeout했다. 기존 모바일 동작대로 회차 안내를 먼저 여는 시험 한 줄만 추가하고 해당 시험 파일 hash를 갱신했다(나머지 16파일 동일). 이 모바일 fixture 수정은 제품 코드 변경이 아니다. 이후 AC-CR04 실제 hook 회귀를 추가 발견해, 진행 중이던 E2E 재실행을 36건 통과 시점에 작업 소유 프로세스만 종료했다. 후속 국소 시험에서는 CSV viewport 전환 직후 즉시 측정이 한 번 실패했다. 기존 화면 시험과 같이 같은 가로 넘침 조건을 expect.poll로 재검사하도록 바꾸고 저장 실패/CSV 2건을 17.8초에 통과했다. hook 저장 위치·저장 실패 시험·CSV fixture의 3파일 hash를 갱신했으며 최종 전체 E2E 150건을 9.8분에 통과했다. backend 코드는 `78f4695` 이후 동일하며 그 전체 결과는 계속 유효하다. AC05는 모바일 fixture 수정·문서·캡처를 추가하고 hook 수정은 AC02 PR에 `3b75014`로 별도 반영했다(통합 작업 브랜치의 동일 patch `3e52379`).

Graft 최종 wiring build/check: 3575 nodes·10428 edges·294 cards, 동기화 OK. deep 의미 요약은 미생성이며 lexical source·정확한 wiring·전수 검색을 사용했다. 문서 9개 최초 검사: local 상대 링크 88개·기존 HEAD 대상 44개, 줄 범위/개행/fence/공백 오류 0건. 캡처/통합 링크 추가 후 상대 링크 97개·서로 다른 대상 51개·요구12/시험ID22·동결17파일·오류0건을 확인했다. PR 이력·동결 manifest를 더한 최종 검사는 상대 링크99개·대상52개이며 committed 대상까지 검사했다.

AC05 독립 문서 1차 검토: AC-T01~T22·commit/17파일·전환9/잔존80·판본/인수 한계의 사실 불일치 0건. 공식 PyPI 7종 링크 누락 1건은 수용·보완했다. 최종 backend 문서 검토도 불일치 0건이었다. 후속 frontend 문서 검토에서 AC-T09의 손상 JSON/명시 POST 4xx 직접 주입 근거 누락을 발견해 수용했다. AI·전처리 손상 JSON 뒤 409와 조회로 접수 확인한 전처리의 늦은409 세 시험을 추가해 3 passed / 21.5초로 직접 검증했다. 이는 제품 수정 없이 시험 근거를 보완한 것이다. 이 후속 2개 시험 파일만 hash를 갱신했고 제품 11개 파일은 전체 회귀 이후 동일하다. 추가 시험은 AC02 `0e01185`에 반영했다(통합 작업 브랜치 동일 patch `a8c6574`).

## 8 화면 증거

전체 E2E가 생성한 합성 화면이다. 390/1440 viewport의 가로 넘침 assertion과 육안 확인을 함께 수행했다. 기존 레이아웃·문구를 변경하지 않았다. 최종 전체 성공 실행에서 6 PNG를 다시 보관했고 desktop은 구현자, mobile은 독립 reviewer가 육안 확인했다. 실행 중/재연결 안내는 동일 spec의 Promise gate와 상태 assertion으로도 검증한다.

| 화면 | PNG 크기 | SHA-256 |
| --- | --- | --- |
| [analysis-progress-1440.png](evidence/analysis-progress-1440.png) | 1440×3670 | `2894b4503d4708f3b848389326796eff06bd6ec23916879a6de283ccb5b33e91` |
| [analysis-progress-390.png](evidence/analysis-progress-390.png) | 390×4321 | `be802cb8fc0f336e861bcf6da166ecf1bfa4bb99bc97d7942b22e5adbe2e79a9` |
| [preprocess-progress-1440.png](evidence/preprocess-progress-1440.png) | 1440×2148 | `7588761bf7c9814479c47a6e4399e726171da37f7d45196d6dd38e9b4756d01f` |
| [preprocess-progress-390.png](evidence/preprocess-progress-390.png) | 390×2729 | `510186aa37ede8c1911ccc9abca100aba2b972aec528727f133bdac203575d28` |
| [segments-csv-1440.png](evidence/segments-csv-1440.png) | 1440×5992 | `c3de78edc85ea8e0f41696dd10326839289dcb97901b8fe02d408531b8c0fe03` |
| [segments-csv-390.png](evidence/segments-csv-390.png) | 390×10313 | `93f6115f972db2cbddbb5a9421bbaff6820cf78828aa8cf1a6e218bd7532a01f` |

## 9 PR 통합과 최종 고정

| PR | 구현 head / 실제 PR | 병합 근거 |
| --- | --- | --- |
| AC01 | `f949d55` / [#107](https://github.com/syleeVeluga/k-dog-proj/pull/107) | `9601a78` |
| AC02 | `0e01185` / [#108](https://github.com/syleeVeluga/k-dog-proj/pull/108) | `924c9bc` |
| AC03 | `4bbe1f0` / [#109](https://github.com/syleeVeluga/k-dog-proj/pull/109) | `a26d4f6` |
| AC04 | `78f4695` / [#110](https://github.com/syleeVeluga/k-dog-proj/pull/110) | `3ede709` |
| AC05 | 기록 기준 `bd7d65f` + `main` 통합 `36218c5` / [#111](https://github.com/syleeVeluga/k-dog-proj/pull/111) | #111의 GitHub 이력에서 최종 merge commit·상태 확인 |

AC01~04를 순서대로 main에 통합했다. AC05에 main을 통합한 `36218c5`에서 제품11파일을 포함한 변경 source/시험17파일이 [정규화 SHA-256](evidence/source-test-sha256.json)과 일치함을 확인했다. AC02로 옮긴 두 patch는 통합 전후 같은 내용이며 AC05의 main 대비 차이는 문서·화면 증거·CSV 시험 fixture뿐이다. 제품 source를 다시 변경하지 않아 전체 시험 결과가 통합 후에도 유효하다.

최종153건은 전체150건과 추가3건 실행의 합집합이며 한 번의153건 전체 실행으로 기록하지 않는다. 최종commit·merge는 GitHub PR 이력으로 추적한다. 실제 배포·공급자·현장 보류는 §6을 유지한다.
