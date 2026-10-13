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

GK02: 구현 `aa1be57`, [PR #96](https://github.com/syleeVeluga/k-dog-proj/pull/96). 원격 check rollup은 비어 있으며 위 로컬 검증/독립 검토를 근거로 병합한다. 실제 merge SHA는 GK03 착수 기록에 확정한다.

| 요구 시험 | 실제 근거 |
| --- | --- |
| GK-T01 | legacy primary/reference/ciphertext 불변·environment primary·backup none |
| GK-T02 | 실제 Windows DPAPI·슬롯 독립 회전·DB/응답/파일 원문 부재·backup secrets 제외 |
| GK-T03 | primary-only 제거·backup 유지·원자 전체 폐기/실패 rollback·unlink 실패·환경 변수 부활 없음·복원 후 명시 재등록 |
| GK-T04 | 세 일반 역할/익명/비활성 developer·Host400/Origin403·잘못된 slot/type/길이422·no-store·원문 미반사 |
| GK-T05 | 다른 슬롯 동시 등록·동일 기대 참조의 한 승자/409·두 슬롯 회전 중 읽기·동일 원문/환경 주키 중복 거절 |
| GK-T06 | 선택 슬롯만 요청·실패 fallback0·slot/reference/시각 고정·교체 후 옛 시험 비승계·역사/늦은 시험 조회 호환 |

실제 운영 키 조회·실공급자 호출·참가자 영상 사용·운영 DB 변경·고객 배포는 수행하지 않았다.
