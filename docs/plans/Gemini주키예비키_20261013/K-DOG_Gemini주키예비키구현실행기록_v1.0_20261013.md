# K-DOG Gemini 주키·예비키 구현 실행 기록

버전: v1.0 · 작성 2026-10-13 · 후속 갱신 2026-10-14 · 상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md)

## 공식 API·의존성 확인

확인일 2026-10-13. 새 패키지를 추가하지 않고 기존 manifest/lockfile을 유지한다. Python 3.14.2와 Node 24.13.0을 사용한다. 이번 기능은 평가 규칙·모델 변경이나 의존성 업그레이드를 요구하지 않으므로, 기존 검증된 잠금판에서 기능 변경을 검증한다.

PyPI JSON과 npm 공식 registry의 최신 안정판 및 runtime/peer를 직접 조회했다. Python 패키지의 Python 최소 버전은 모두 3.14 실행을 허용한다. React DOM/타입의 React peer는 잠금판 조합을 유지하며, Vite는 Node >=22.12, Playwright는 Node >=20, TypeScript는 Node >=16.20 조건을 확인했다.

| 패키지 | 최신 안정판 | 선택 잠금판 | 공식 registry |
| --- | --- | --- | --- |
| Pydantic | 2.14.1 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/) |
| FastAPI | 0.143.0 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/) |
| Uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/) |
| HTTPX | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/) |
| OpenPyXL | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/) |
| ReportLab | 5.0.1 | 5.0.1 | [PyPI](https://pypi.org/project/reportlab/) |
| Pillow | 12.3.0 | 12.3.0 | [PyPI](https://pypi.org/project/pillow/) |
| Cryptography | 50.0.2 | 50.0.2 | [PyPI](https://pypi.org/project/cryptography/) |
| PyPDF | 6.20.1 | 6.19.0 | [PyPI](https://pypi.org/project/pypdf/) |
| React / React DOM | 19.3.0 | 19.2.8 | [React](https://registry.npmjs.org/react), [DOM](https://registry.npmjs.org/react-dom) |
| TypeScript | 7.0.2 | 7.0.2 | [npm](https://registry.npmjs.org/typescript) |
| Vite | 8.3.4 | 8.2.2 | [npm](https://registry.npmjs.org/vite) |
| Playwright Test | 1.64.0 | 1.63.0 | [npm](https://registry.npmjs.org/@playwright/test) |
| React types / DOM types | 19.3.0 / 19.3.0 | 19.2.18 / 19.2.7 | [React](https://registry.npmjs.org/@types/react), [DOM](https://registry.npmjs.org/@types/react-dom) |

[Pydantic 타입/API](https://docs.pydantic.dev/latest/concepts/types/), [changelog](https://docs.pydantic.dev/latest/changelog/), [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/), [typed response API](https://fastapi.tiangolo.com/tutorial/response-model/), [Uvicorn releases](https://github.com/Kludex/uvicorn/releases), [React releases](https://react.dev/blog), [Vite releases](https://vite.dev/releases), [Playwright releases](https://playwright.dev/docs/release-notes), [TypeScript releases](https://www.typescriptlang.org/docs/handbook/release-notes/overview.html)를 확인했다. SecretStr·typed response·기존 API를 사용하며 최신 minor 변경을 이번 범위에 섞지 않는다. 기존 Uvicorn release-notes URL 조회 실패는 공식 GitHub releases 조회로 보완했다. 새 Uvicorn API 도입은 없다.

선택판 registry도 재확인했다. FastAPI 0.141.1은 Pydantic >=2.9.0, Pydantic 2.13.5는 pydantic-core 2.46.5를 요구하며 기존 lockfile 조합을 유지한다. React DOM 19.2.8의 React ^19.2.8과 DOM types 19.2.7의 React types ^19.2.0 요구에 현재 잠금판이 맞는다. API는 기존 response_model/SecretStr/REST만 사용하며 새 minor의 기능을 요구하지 않는다.

기존 회귀에서 사용하는 [HTTPX API](https://www.python-httpx.org/api/)/[releases](https://github.com/encode/httpx/releases), [OpenPyXL changes](https://openpyxl.readthedocs.io/en/stable/changes.html), [ReportLab releases](https://docs.reportlab.com/releases/), [Pillow releases](https://pillow.readthedocs.io/en/stable/releasenotes/index.html), [Cryptography changelog](https://cryptography.io/en/latest/changelog/), [PyPDF changelog](https://pypdf.readthedocs.io/en/stable/meta/CHANGELOG.html)도 조회했다. OpenPyXL changelog 페이지는 3.1.3을 표기하므로 최신 안정판은 registry 3.1.5로 구분했다. Cryptography 문서의 개발판 51은 안정판으로 선택하지 않았다. HTTPX의 /changelog/ 조회 실패는 공식 GitHub releases로 보완했다. 이들 기존 데이터/출력 API는 변경하지 않는다.

[Gemini Interactions errors](https://ai.google.dev/gemini-api/docs/api-errors), [troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting), [Files API](https://ai.google.dev/gemini-api/docs/files)를 확인했다. HTTP/정규 code와 로컬 credential 원인을 분리하고 provider message는 저장하지 않는다. 기존 REST와 Windows DPAPI를 사용하며 SDK 재시도를 도입하지 않는다.

## GK01 이중키 저장·API

착수 조사 기준 `6b0d195` 이후 계획 PR #94가 병합된 `ba8508f`를 최종 기반으로 사용한다. 브랜치 `veluga/gk01-gemini-key-slots`.

기존 `gemini` target/reference/ciphertext는 주키로 유지하고 `gemini:backup`을 추가했다. 신규 슬롯 API는 required `expected_reference`를 write fence에서 비교한다. 현재 developer 활성/역할을 같은 fence에서 재검사한다. 원문 중복은 다른 가용 슬롯의 복호화 값과 일시 비교하고 거절한다. 두 슬롯 전체 폐기는 한 transaction으로 확정하며 unlink 실패도 폐기를 되돌리지 않는다.

`gemini_slots`는 source/로컬 미가용 사유와 현재 reference의 시험 결과를 제공한다. 각 시험은 한 슬롯만 요청하고 당시 reference/시각에 고정한다. 백업/복원은 기존 키 제외 정책을 그대로 사용한다. 복원된 주키·예비키 모두 파일 미가용으로 명시 재등록이 필요하며 환경 변수로 부활하지 않는다. 자동 실행 전환은 GK02의 범위다.

검증: 기존 settings 8개와 신규 슬롯 9개(17개/11.987초) 통과. 기존 Gemini transport 4개 포함 13개/6.496초 통과. frontend build와 settings/retirement E2E 2개/7.7초 통과. 실제 Windows DPAPI, 두 슬롯 동시 등록·동일 슬롯 stale 경쟁, 실패한 unlink, 개발자 비활성, Host/Origin, validation 비밀 미반사, backup/restore 재등록을 검사했다. 최초 신규 보안 시험에서 기존 Host 거절 status를 403으로 잘못 기대한 1건을 실제 400 계약에 맞췄다.

분리 검토 단계에서 기존 `secret.test` JSON에 slot/시각이 없는 경우 typed 응답이 실패할 수 있음을 발견해 수용했다. 감사 `happened_at`과 primary 기본값으로 읽고 현재 reference의 최신 시험을 조회하도록 수정했다. 늦은 retired 시험이 새 reference의 시험을 가리지 않도록 회귀를 추가했다. 수정 중 시험 코드 배치 오류 1건을 바로잡고 신규 10개/7.211초 통과. 독립 reviewer 및 최종 triage/PR/병합 기록은 완료 후 추가한다.

추가로 전체 폐기 도중 두 번째 감사 쓰기 실패 시 두 슬롯 모두 rollback되는 시험과 두 슬롯 회전 중 Worker credential 읽기 시험 2개/1.477초를 통과했다. 신규 슬롯 시험은 고유 12개다. 로컬 구현 commit `be3df63` 이후 이 두 시험과 문서 앵커 보완을 추가했다. 백엔드 전체 회귀는 실행 중이며 독립 검토 전 원격 PR/병합은 수행하지 않는다.

이후 전체 backend 759개/929.968초 결과는 756 통과·2 skip·1 실패였다. 실패는 기존 `tests.test_retirement_v4`의 keys-only 응답 기대였으며 `keys`+`gemini_slots` 확장 계약으로 수정했다. skip 2개는 고객 역사 원본 부재이고 통과로 합산하지 않는다. GK01 수용 수정 후 settings·key slots·retirement·deletion restore 26개/19.221초 통과. 신규 슬롯 시험은 최종 고유 14개다. 전체 회귀를 수용 수정 뒤 다시 성공했다고 표시하지 않으며 GK04에서 최종 전체 회귀를 수행한다.

사용자의 별도 검토 에이전트 허용 후 독립 reviewer `gk01_cold_review`가 `ba8508f..8b315cb`와 관련 계약을 읽기 전용 검토했다. 발견 2건 모두 수용, 보류/거절0이다.

| 발견 | 수용 수정·검증 |
| --- | --- |
| CR-GK01-01 / P2: 복호화/파일 읽기 실패 시험이 unavailable 참조에 저장되어 현재 참조의 옛 연결 성공이 남음 | credential 복호화 전에 같은 write fence에서 현재 등록 reference를 고정한다. DPAPI 실패/파일 유실은 당시 reference의 실패 시험으로 갱신하고 외부 요청0을 검증했다 |
| CR-GK01-02 / 계약 인수 공백: vault 등록 이력이 없는 환경 주키 snapshot의 복원 뒤 환경 키가 바로 사용됨 | 복원 staging에 Gemini 재등록 marker를 저장하고 환경 주키 fallback을 막는다. snapshot DB/감사 원장은 바꾸지 않는다. source none/reference null/restore_required, clean 후 유지, 명시 슬롯 등록 후 사용을 검증했다. 다른 공급자 환경 정책은 유지한다 |

복원 marker는 키 원문/참조가 없는 로컬 운영 경계다. 키와 함께 백업에서 제외하며 복원할 때 새 staging에 만든다. 등록 이력이 있는 슬롯은 기존 file_unavailable/removed 경계를 사용한다. 실패한 retired ciphertext 정리는 다음 키 변경에서 재시도할 수 있으며 기존 offline clean이 secrets를 지운다고 표시하지 않는다.

수용 수정 commit `1573fdb`를 reviewer가 재검토하여 두 발견의 해결과 새 actionable defect0을 확인했다. 합성 재현에서 외부 요청0, 환경 주키 복원 차단/clean/명시 재등록 및 OpenAI 환경 정책 유지를 확인했다. 초기 구현 `be3df63`, 원자 폐기·읽기 회귀 `8b315cb`, 수용 수정 `1573fdb`. 문서 상대 링크/공백 검사 및 Graft wiring freshness 통과. PR/병합은 아래에 이어 기록한다.

GK01: [PR #95](https://github.com/syleeVeluga/k-dog-proj/pull/95), main 병합 `7fad053af2c6bffd9f64a1362c94d776dd339b9b`. 원격 check rollup은 비어 있었으며 위 로컬 검증/독립 검토를 근거로 병합했다. GK02는 이 merge에서 새 브랜치로 착수했다.

## GK02 자동 전환 실행

기반 GK01 병합 `7fad053` · 브랜치 `veluga/gk02-gemini-key-fallback`. 같은 잠금 의존성을 유지한다. 공식 [legacy Gemini 오류 형식](https://ai.google.dev/gemini-api/docs/generate-content/api-errors?hl=en)의 `google.rpc.ErrorInfo`/`googleapis.com`/`API_KEY_INVALID` 형식을 추가 확인했다. Interactions snake_case 코드와 HTTP 상태를 보존하고 임의 provider message는 저장하지 않는다. 일반 400·404·409·416·501, JSON/schema·media·guard·cleanup-only는 전환 대상이 아니다.

실제 GeminiScorerV4 호출 세 곳은 `Worker.gemini_request`로 예약/선택을 함께 수행한다. 실제 슬롯 선택과 fallback 요청은 현재 run의 changes에 기록하고 write fence에서 현재 actor/점유/상한을 확인한다. 주키의 로컬 미가용은 첫 credential로 예비키를 선택한다. 외부 주키 실패는 현재 attempt를 실패 이력으로 남겨 별도 다음 attempt/예약으로 예비키를 사용한다. 다음 run은 주키부터 시작한다. Python fake observer의 기존 계약은 그대로 유지한다.

주키 전환 대기의 Retry-After/backoff는 같은 run의 다른 미완료 provider 그룹도 기다리게 하며, 완료 그룹은 재호출하지 않는다. 매 attempt의 현재 슬롯 참조를 읽고 원문은 메모리에만 유지한다. 원격 업로드/정리는 같은 슬롯/참조를 기록하고 예비키는 고정 local bytes/hash를 새로 업로드한다. 후속 정리는 현재 활성 두 슬롯 중 정확히 같은 참조만 사용한다. 이전 uncertain/cleanup_pending과 예약별 계량은 보존한다.

업무 DTO/usage에는 원문/참조 없이 역할·전환 사유·대기/상한/미가용 상태를 제공한다. 재사용은 현재 선택 없이 `source_credential_slot`/`source_fallback_reason`로 옛 역할만 표시하고 예약/비용에 합산하지 않는다. 옛 산출물이나 snapshot/config를 재작성하지 않는다.

검증: 기존 Gemini/settings/run 28개/43.172초, AI API·애착·문장·report API·reset·실행 actor 57개/123.893초 통과. GK01 슬롯·실제 네 경로/usage 21개/41.304초 통과. fallback 신규 고유13개와 기존 명시 재사용2개를 함께 15개/48.725초 통과했다. 최초 새 actor 비활성 시험은 정상403 조회 거절 뒤 상태를 조회하려던 시험 코드만 DB 확인으로 고쳤다. 실제 사업 접근 정책은 바꾸지 않았다. 신규 fake transport는 주키/예비키의 URI/키·local hash, 원격 cleanup, 새 예약/미확인 비용, 상한1/3, Worker 재생성·다음 run 주키·슬롯 회전·중지/비활성·schema/evidence·다운로드/명시 재사용 무호출을 검사한다. 통합 원관찰42그룹+애착은 주키 실패1+예비43=예약44를 확인했다.

독립 cold review 및 발견별 triage/수용 수정·PR/병합은 완료 후 추가한다. 실제 공급자 호출0, 전환/정산/모델 품질 인수는 별도 대기다.

2026-10-14 후속: 전환 대기 중 입력 revision·source hash·actor 변경의 예비 요청0, 늦은 backup lease/token 변경의 게시0, max_attempts2의 두 슬롯 공유 상한을 추가 검증했다(3개/4.579초). 신규 fallback 시험은 최종 고유16개다. 예비키 미가용의 인증 오류는 주키 동일 오류를 반복하지 않고, 예비키가 없는 운영의 일시 장애는 기존 retryable 정책과 같은 상한을 유지한다.

독립 reviewer `gk02_cold_review`는 `7fad053` 이후 구현을 읽기 전용 검토하여 actionable defect0을 확인했다. 수용/보류/거절 발견0이며 독립 재검증 신규13개/43.755초 통과, 실제 공급자 요청0이다. 분류/작업 단계·전환 원장·재시작·backoff·공유 상한·현재 actor/회차/lease/token·네 호출 경로·업로드/정리·원문 미노출·재사용/계량을 검토했다. 추가 3개는 작성자 검증으로 구분한다. Graft wiring freshness와 git diff check 통과.

| 인수 | 실제 근거 |
| --- | --- |
| GK-T07 | 주키 제거/파일 유실/DPAPI 실패 → 첫 예비 credential·주키 요청0, 두 슬롯 미가용 요청0 |
| GK-T08~09 | HTTP/기계 판독 code/phase 표와 실제 HTTPError 정규화·임의 message 미보관, cleanup 전환0 |
| GK-T10 | 실제 scoring·integrated attachment·standalone attachment·narrative Worker+REST 경로 전환 |
| GK-T11 | max_attempts1/2/3·max_ai_calls1·예약별 usage·Retry-After/backoff 대기·기존 schema repair cap 회귀 |
| GK-T12 | Worker 재생성/같은 run 남은 단계 backup·새 run primary·backup 실패3회 상한·슬롯 회전·왕복0 |
| GK-T13 | 대기 중 input/hash/actor 변경 요청0·중지 후 요청0·late actor/lease/token 변경 게시0·기존 guard 회귀 |
| GK-T14~15 | local hash 같음·프로젝트 URI/키 분리·각 upload/delete 같은 참조·backup 정확 정리·retired 참조 대기 유지 |
| GK-T16 | primary uncertain/cleanup_pending + backup 성공 계량 보존·성공 단계 무재호출·기존 bytes 불변·명시 재사용 무호출/중복 계수0 |

GK02: 구현 `aa1be57`, [PR #96](https://github.com/syleeVeluga/k-dog-proj/pull/96). 원격 check rollup은 비어 있었으며 위 로컬 검증/독립 검토를 근거로 main에 병합했다. merge `ad857d1cadce2929ef791e110569eb4227169a2c`. GK03는 이 merge에서 착수했다.

| 요구 시험 | 실제 근거 |
| --- | --- |
| GK-T01 | legacy primary/reference/ciphertext 불변·environment primary·backup none |
| GK-T02 | 실제 Windows DPAPI·슬롯 독립 회전·DB/응답/파일 원문 부재·backup secrets 제외 |
| GK-T03 | primary-only 제거·backup 유지·원자 전체 폐기/실패 rollback·unlink 실패·환경 변수 부활 없음·복원 후 명시 재등록 |
| GK-T04 | 세 일반 역할/익명/비활성 developer·Host400/Origin403·잘못된 slot/type/길이422·no-store·원문 미반사 |
| GK-T05 | 다른 슬롯 동시 등록·동일 기대 참조의 한 승자/409·두 슬롯 회전 중 읽기·동일 원문/환경 주키 중복 거절 |
| GK-T06 | 선택 슬롯만 요청·실패 fallback0·slot/reference/시각 고정·교체 후 옛 시험 비승계·역사/늦은 시험 조회 호환 |

실제 운영 키 조회·실공급자 호출·참가자 영상 사용·운영 DB 변경·고객 배포는 수행하지 않았다.

## GK03 키 관리와 실행 표시

기반 GK02 병합 `ad857d1` · 브랜치 `veluga/gk03-gemini-key-ui` · 구현/검증 2026-10-14. React/DOM·TypeScript·Vite·Playwright Test·types의 공식 registry 최신 안정판과 선택 잠금판을 재확인했고 위 표와 동일하다. 기존 API와 peer 조합을 유지하며 의존성을 추가/갱신하지 않았다. Native 화면 검증은 [Python Playwright PyPI](https://pypi.org/project/playwright/) 최신/선택 1.63.0, Python >=3.10과 [release notes](https://playwright.dev/python/docs/release-notes), [Page API](https://playwright.dev/python/docs/api/class-page)를 확인한 기존 별도 runtime으로 실행했다.

개발자 Gemini 두 카드에 현재 참조의 상태·시험 시각, 독립 등록/시험/제거와 전체 사용 중지를 추가했다. 제출 직후 DOM 입력을 비우고 원문 초안을 상태/브라우저 저장소에 보존하지 않는다. 409는 최신 조회 뒤 재입력을 요구하며 자동 재전송하지 않는다. 늦은 시험은 교체 전 키로 안내한다. 미등록 시험의 unavailable sentinel은 null 참조와 대응시켜 개발자 설정 필요로 표시한다. 환경 주키·복원 재등록·같은 프로젝트 할당량·모델 목록 연결 시험·진행 중 실행과 콘솔 취소의 구분을 설명한다. OpenAI/Anthropic 관리 계약은 유지한다.

공통 `GeminiExecution`은 채점·독립 애착·리포트의 실제 run/attempt 역할과 전환 원인·대기·미가용·상한을 표시한다. 전환 예정과 실제 예비 사용, 재사용 출처와 현재 선택을 구분하고 역할 없는 옛 원장은 기록 없음으로 표시한다. 내부 key reference/원문은 업무 DTO/화면에 추가하지 않았다. 기존 과금 미확인/원격 정리 미완료와 호출 예약/비용 표시를 유지한다.

합성 browser_server만 사용하는 fixture route에서 실제 Worker+GeminiScorer+fake REST를 조립했다. 생산 API에는 경로를 추가하지 않는다. fixture는 disposable 저장소의 기존 계정/로그인을 보존하며 합성 영상·독립 시트·의견·고정 최종본·실제 HTML/PDF까지 생성한다. 주키 실패1+예비43=채점44예약, 새 독립 애착/문장 run은 각각 주키부터 시작해 예비 성공2예약을 확인했다. 실제 공급자 요청0이다.

검증: frontend build 통과(기존 chunk 크기 안내 유지), settings/retirement/scoring/키 전환/문맥 관련 E2E 8개/54.8초 통과. 최종 미등록 시험 안내 수정 후 settings+키 전환3개/40.9초 통과. backend fixture/실제 경로19개/70.639초 통과. 기존 진행/상태/업무 접근/리포트 추가 회귀는 첫15개에서14통과·리포트 재사용 선택1실패였고, 해당 파일 단독3개/18.0초와 새 서버의 동일15개/58.5초 재검증은 모두 통과했다. repeat-each=3 시도는 동일 서버/고정 upload ID로 1회차3통과 뒤 나머지6개 fixture link422가 발생해 반복 검증 근거로 쓰지 않는다. 원인 없는 제품/시험 변경을 하지 않고 GK04 전체 회귀에서도 확인한다. 최초 종단 fixture 작성 시 route mount 순서·로그인 대기·필수 고정 opinion reference·메뉴 이름 오류는 시험 조립에서 바로잡았다.

Native Python Playwright로 login→개발 설정→networkidle 이후 390px/1366px의 label·버튼·원문 없는 화면과 가로 넘침 없음(레이아웃 완료 대기)을 확인했다. [390px 합성 캡처](assets/GK03_Gemini_keys_390_20261014.png), [1366px 합성 캡처](assets/GK03_Gemini_keys_1366_20261014.png)를 실제 열어 검토했다. helper 종료 뒤 남은 tests.browser_server 프로세스는 command line으로 소유를 확인해 종료했고 포트 해제를 확인했다. 실제 키/참가자 자료는 캡처/trace에 사용하지 않았다.

독립 cold review 진행 중이다. 발견별 수용/보류/거절·수정 재검증과 commit/PR/병합은 완료 후 이어 기록한다.

독립 reviewer `gk01_cold_review`가 `ad857d1` 이후 source/합성 fixture/두 슬롯 경합·입력 수명·공통 표시를 읽기 전용 검토했다. 발견1 수용, 보류/거절0: CR-GK03-01(P2)은 두 슬롯 로컬 미가용으로 공급자 요청0/selected_at null인 실패 step에 「주키 사용」을 표시하던 오류다. 선택 시각 없는 역할은 「선택 미완료」로 표시하며 실제 선택·전환 대기·재사용 출처 기록을 구분했다. reviewer는 실제 Worker로 실패 DTO를 재현했다.

별도 인수 공백3건도 시험으로 보완했다: 키보드 Tab의 등록 버튼 focus와 미제출 입력의 메뉴 종료·로그아웃/재로그인·서버 세션 무효화 후 DOM 소멸, 옛 역할 없음/재사용 출처·현재 선택/시도·호출 상한/미가용 문구, 실제 완성된 독립 애착 DTO의 화면 역할·시도·과금 미확인 표시다. 최종 표시 경계의 결정론적 DTO와 애착 POST 응답 intercept는 실제 Worker 인수에 보조하는 UI 근거로 구분한다. 추가 시험 최초 실행은 메뉴 label 오기와 불완전 mock의 token_meters 누락으로 실패하여 시험 조립만 수정했다. 수용 수정 이후 build 통과; 최종 E2E와 reviewer 재검토 결과는 이어 기록한다.

수용 수정/인수 보완 후 최종 settings+키 전환 E2E 3개/45.2초 통과. reviewer 재검토는 CR-GK03-01 해결과 추가 assertion의 범위를 확인하고 새 actionable defect0을 기록했다. 최종 E2E 실행은 작성자 검증으로 구분한다. 상대 링크29개와 공백 검사 통과, wiring graph 동기화 확인. GK04에 실제 Worker 종단 fixture와 화면/API 회귀, 백업/복원·패키지 검증을 인계한다.

GK03: 구현/수용 수정 commit `f61a0a6`, [PR #97](https://github.com/syleeVeluga/k-dog-proj/pull/97). 로컬 검증·독립 검토를 근거로 병합하며 실제 merge SHA는 GK04 착수 기록에서 확정한다.

GK03: main 병합 `9cd4b932209eccbe17f5e960f40e7e3139398d31`. 원격 check rollup은 비어 있었고 위 로컬 검증/독립 검토·수용 수정을 근거로 병합했다.

## GK04 통합 인수와 운영

기반 GK03 merge `9cd4b93` · 브랜치 `veluga/gk04-gemini-fallback-acceptance` · 2026-10-14. `test_gemini_acceptance`는 실제 Worker/fake REST로 원관찰·통합/독립 애착·독립 제출·최종본·문장·HTML/PDF를 조립한다. 채점 backup44예약, 새로운 문장 run의 primary→backup2예약, uncertain/cleanup_pending, 명시 재사용 예약0/현재 키 선택 없음/출처 backup, 발급 bytes/고정 결과 보존을 검사했다. 백업 원문/두 ciphertext/세션 제외·감사 snapshot 그대로 복원·키 없이 새 문장 요청0/성공 게시0·두 슬롯 명시 재등록 뒤 다시 primary→backup 성공·clean 이후 옛 파일 보존을 확인했다(1개/45.684초). 초기 시험 작성의 report 예약 필드/최종본 테이블/세션 기대는 실제 DTO와 changes/users schema에 맞춰 보정했으며 제품 계약은 변경하지 않았다.

개발/운영 안내를 Gemini 두 슬롯·연결 시험·상한/전환 비대상·프로젝트 할당량·앱 제거/실행 중지/콘솔 취소·DPAPI 실행 계정·HTTPS·복원 재등록·정확한 참조 cleanup·미확인 비용으로 갱신했다. build allowlist에는 이 계획의 합성 캡처2개만 추가해 실행 문서의 상대 링크를 보존한다. verify_release의 발행/online 설치는 일반 업무 설정403, developer 허용 및 Gemini 주키/예비키 초기 미등록을 확인하도록 보강했다. 고객 발행/배포와 운영 DB/키 변경은 수행하지 않는다.

공식 최신/선택 runtime 추가 확인: [Python downloads](https://www.python.org/downloads/) 최신 안정3.15.0 / 3.14 계열3.14.8, 로컬 시험3.14.2·기존 portable pin3.14.8; [3.15 변경](https://docs.python.org/3.15/whatsnew/3.15.html) 검토 후 기존3.14 설치/ABI·runtime 해시 계약을 유지한다. [uv PyPI](https://pypi.org/project/uv/) / [0.13.0 release](https://github.com/astral-sh/uv/releases/tag/0.13.0) 최신0.13.0 / 로컬0.11.18, 기존 [locked CLI](https://docs.astral.sh/uv/reference/cli/)가 필요한 sync/export를 지원해 환경 도구를 갱신하지 않는다. [FFmpeg downloads](https://ffmpeg.org/download.html) / [CLI](https://ffmpeg.org/ffmpeg.html) 최신/portable9.0.2, 기존 build.json 해시와 대응 소스 계약을 유지한다. frontend/backend 잠금 의존성은 GK01/GK03 공식 registry/API 확인 결과를 재사용하며 신규 라이브러리/API가 없다.

`uv sync --locked`, `npm ci`, frontend build 통과. npm audit에서 기존 Vite→PostCSS의 dev 의존 `source-map-js 1.2.1` high1건을 확인했다([GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), 수정1.2.2). 외부 indexed source map을 처리할 때 event-loop DoS가 가능한 기존 개발 도구 경계다. 제품 frontend는 빌드된 static assets만 사용하며 이번 Gemini 기능에 의존성 upgrade를 섞지 않는다. 별도 개발 도구 잠금판 갱신 후속으로 남기고 audit clean으로 표시하지 않는다. 전체 회귀/ZIP 검증은 진행 중이다.

깨끗한 구현 commit `4a1e6bbf514311766ba64d2432ec50b3401ea6e3`에서 두 ZIP을 만들고 verify_release를 통과했다. 기존 hash/wheel-only Python3.14.8+FFmpeg9.0.2 runtime, S1 assets/고지문을 유지한다. 계획/실행 MD7개와 합성 PNG2개가 모두 포함되고 tests·secrets·고객 원본이 제외됨을 ZIP inventory로 별도 확인했다. 검증 receipt는 ignored `releases/gk04-release-receipt.json`, 상세 로그는 저장소 밖 `%TEMP%/kdog-gk04-{portable,online}-20261014.log`다.

| ZIP | SHA-256 | 실제 설치 검증 |
| --- | --- | --- |
| `releases/kdog-gk04-windows-x64.zip` · 75,929,185 bytes | `a01773148cadcd25c808188b80d89b7fe1075890b1ee1daa21e15d550c24b77f` | 현재 Windows 새 한글/공백 경로, PATH에서 uv/Python/FFmpeg 제외, 내장 runtime, 손상 거절·login/접수/재시작·감독 종료, 합성 발행 암호화/틀린 키·변조 거절/계정·바로가기·재설치 자료 보존 |
| `releases/kdog-gk04-online-windows-x64.zip` · 3,099,584 bytes | `b4662629936d6dd4bcdbe3a1733da4cd3b0199ed0afe006ac60b3304cdbc4384` | 현재 Windows 새 한글/공백 경로/venv, PATH uv/FFmpeg 및 인터넷/캐시, 설치 전 안내/손상 시 venv 생성 전 거절·환경 override 격리·Python3.14/PATH FFmpeg·login/접수/Start.cmd 재시작·감독 종료 |

두 검증에서 일반 업무의 developer settings403, developer 허용·공유 업무, 주키/예비키 두 슬롯의 available=false/reference=null을 확인했다. 외부 AI 호출0. 실제 깨끗한 OS/다른 PC3대/ARM·현장 업로드 시간의 대체 증거는 아니다. package 검증은 loopback HTTP이며 실제 조직 TLS proxy/인증서·원격 HTTPS 종단은 미실행이다. 기존 backend Host/Origin/Secure-cookie 회귀와 운영 HTTPS 설정 문서를 인계하며 TLS 실측 완료로 표시하지 않는다. 평가 카탈로그/규칙/고객 원본을 변경하지 않아 추가 source importer는 실행하지 않았다; 전체 회귀의 source-dependent skip은 실제 결과에 별도 기록한다.

첫 전체 frontend E2E는134개 중132통과·2실패(11.1분)였다. 연구 내보내기 메뉴 시험은 참가자 열기 click 후 실제 AI 화면 응답을 기다리지 않고 다른 메뉴로 이동해 선택 문맥이 비어 있었다. 이 시험에 AI 실행 영역 확인을 추가해 요청 완료 후 이동하도록 했다. 다른 연구 export 시험의 socket hang up은 제품 수정 없이 새 서버에서 재검증했다. 해당 두 파일7개/33.1초 통과. 초기 전체 실패를 숨기지 않으며 최종 전체 E2E를 새 임시 서버에서 다시 수행한다. ZIP 제품 내용 변경은 없고 이 시험 대기만 보완했다.

전체 backend:780개/1474.573초,778통과·역사 원본 부재2skip·실패0. 두 skip은 test_catalog_v3의 원본 대조와 역사 판본 CLI 검사이며 통과로 합산하지 않는다. 최종 frontend 재실행은134개 중133통과·촬영 화면 이동1실패(11.7분)였다. 촬영 대상 열기 응답 전에 업로드 메뉴로 이동하던 기존 시험에도 대상의 재촬영 영역 확인을 추가해 문맥 완료를 기다리게 했다. 제품 변경/일괄 timeout 상향/자동 retry로 숨기지 않았다. 최종 전체 E2E의 추가 재실행 결과는 이어 기록한다.

撮影 화면 대기 보완 후 intake 파일4개/12.8초 통과. backend/패키지 검증을 마친 상태에서 frontend 전체를 단독으로 재실행한다.
