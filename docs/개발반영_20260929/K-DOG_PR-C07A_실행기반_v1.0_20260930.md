# PR-C07A 실행 기반

버전: v1.0 · 2026-09-30 · 상태: 구현·검증·cold review 완료 · 선행: C04·C05·C06 · 추정: 2~3개발일

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20260930.md). 후속: [C07B AI 채점 연결](K-DOG_PR-C07B_AI채점연결_v1.0_20260930.md). 근거: 기존 실행 불변·점유·재사용 보호장치와 00 §3·§7. 권장 제목: `feat: 새 판본 실행 종류와 불변 입력 기반 연결`.

## 문제와 결과

현재 worker와 실행 입력 파서는 55항목 계약에 결합되어 있다. 점유·heartbeat·불변 산출물·채택 절차는 재사용하되 새 채점 실행과 리포트 실행이 구판 파서에 들어가지 않게 한다. 이 PR은 실행·복구 기반을 검증하고, provider 요청과 운영 AI 활성화는 C07B에서 연결한다.

## 변경 파일

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `backend/app/run_v3.py` | 신설 | 실행 접수·스냅샷 검증·명시적 재사용·종류별 입력 조회·중지·재시도 |
| `backend/app/worker.py`, `backend/app/analysis.py` | 필요한 변경 | 실행 종류 분기, 공통 claim·guard·adopt 재사용, 단계별 복구와 실패 처리 |
| `backend/app/storage.py` | 변경 | 실행 종류·중복 생성 방지·불변 입력 trigger의 명시적 DB migration |
| `backend/app/domain/contracts_v3.py`, `backend/app/input_models_v3.py` | 확장 | 실행 입력·상태·단계·재사용·요청 계약 |
| `backend/app/api.py` | 확장 | 생성·조회·중지·재시도 API와 종류별 권한·입력 revision 검사 |
| `backend/app/maintenance.py` | 변경 | 새 실행 참조·해시·백업·복원·삭제 순서 |
| `backend/tests/test_runs_v3.py`, `test_intake_api.py`, `test_settings.py` | 신설/확장 | 종류 분기·스냅샷·점유·중복·재사용·복구·유지보수 |

## 실행 구조와 경계

1. `runs.kind`로 새 채점과 이후 새 리포트를 구분한다. 기존 실행은 구판으로 식별해 보존하며, 새 실행을 55항목의 `session_snapshot()`, `related_input()`, `split_branch_key()`에 전달하지 않는다. 알 수 없는 종류는 실패 사유를 남겨 차단한다. 신규 실행이 없는 기존 앱의 queued·retry_wait·점유 만료 실행도 종류별로 처리한다.
2. C01의 migration 순서를 이어 DB 변경을 적용한다. 지원하는 버전보다 높은 DB에는 쓰지 않는다. 기존 DB의 trigger는 `CREATE ... IF NOT EXISTS`만으로 바뀌지 않으므로 migration에서 명시적으로 재생성한다. 종류와 실행 입력·설정·재사용 스냅샷은 변경할 수 없게 한다.
3. 새 채점 생성 요청은 expected input revision, 선택 세션, 촬영 절차·카탈로그·계산 판본, 확정 관찰창, 전처리 manifest 참조·해시, 클립 참조·해시, 항목군, 프롬프트·schema·모델·샘플링 설정을 고정한다. 검증한 파일과 DB 상태를 다시 대조해 입력이 바뀐 사이에 접수되지 않게 한다. 장시간 파일 해시 검사 동안 DB 쓰기 잠금을 유지하지 않는다. 리포트 종류의 입력 조건은 C10에서 별도로 연결하며 영상 재관찰이 필요 없는 출력에 채점용 클립 조건을 일괄 적용하지 않는다.
4. 같은 생성 요청이 재전송돼도 실행이 중복 생성되지 않게 요청 식별과 입력 해시를 검사한다. 같은 요청 식별에 다른 입력이면 거절한다. 의도한 재생성은 새 요청으로 기록한다. 상태 조회는 실행을 생성하지 않으며 중지·재시도는 명시적 동작이다.
5. 실행 중에는 claim token·lease·heartbeat를 유지한다. 각 attempt의 파일을 불변 경로에 기록하고 검증 후 DB에 채택한다. 점유가 바뀐 옛 token의 결과와 삭제 요청된 자료의 결과는 채택하지 않는다. 파일 기록 후 DB 채택 전에 종료된 최신 attempt는 envelope·해시·입력·설정 연결을 검사한 뒤 복구한다.
6. 완료 시 `cases.display_run_id`를 자동 변경하지 않는 F-04를 유지한다. 실행 중 입력이 편집되면 고정된 옛 실행은 이력으로 보존하고 현재 표시 결과를 덮어쓰지 않는다. 시트·판정·리포트의 현재 표시 선택은 해당 기능의 명시적 API가 담당한다.
7. 재사용은 명시한 manifest로만 허용한다. 같은 사례·세션, 판본, 원본·클립 해시, 실제 창, 항목군, 프롬프트·schema, 제작 fps·요청 fps·media_resolution이 일치해야 한다. 다른 실행의 산출물 연결·해시·성공 상태를 확인한다. 겹친 창이나 동기화하지 않은 카메라의 횟수를 더하지 않는다.
8. 신규 단계에 공통 호출 예약·시도 상한·스키마 수리 상한·과금 불확실성 기록을 적용할 수 있게 한다. 단계 등록과 실제 provider·모델 계량은 C07B가 채운다. 비용을 산출하지 못한 상태를 0원으로 간주하지 않는다.
9. 실행 조회·결과 제공은 C05의 독립 채점과 AI 공개 정책을 우회하지 않는다. 운영 상태 조회 권한과 AI 원값·근거를 볼 권한을 구분한다. 새 실행 파일·DB 참조는 같은 PR에서 유지보수 참조 탐색과 삭제 순서에 연결한다.

C07A에는 공급자 전송·109개 직접 채점·메모 항목의 프롬프트·AI 유형 판정·AI 시작 화면을 넣지 않는다. 신규 실행기의 시험은 주입한 시험용 작업 함수로 수행하며, 앱·CLI에 가상 공급자나 임의 작업 실행 기능을 노출하지 않는다. C07B 연결 전에는 운영 AI 생성 요청을 명확한 미활성 상태로 거절한다.

## 검증과 완료 조건

- 구판 실행·새 채점 실행·알 수 없는 종류, 수정할 수 없는 kind·입력·설정·재사용 스냅샷, 재기동 migration의 멱등성을 검증한다.
- 두 번 전송한 같은 생성 요청, 다른 입력의 요청 식별 재사용, stale revision, 다른 사례·세션의 전처리 참조, 손상 manifest와 동일 크기 클립 변조를 거절한다.
- 브라우저 종료와 API 재기동 후 처리, 중복 점유, lease 만료, 이전 token 채택 차단, 중지·재시도·시도 상한을 검증한다.
- 파일 기록 후 DB 채택 전 종료, 불완전 파일, 최신 attempt가 아닌 산출물, 복구 중 삭제 요청을 구분한다. 미완 파일을 성공으로 표시하지 않는다.
- 명시한 재사용만 통과하고 창·항목군·프롬프트·schema·샘플링 설정 변경 후 재사용은 거절한다. 입력 편집 후 완료가 현재 표시를 바꾸지 않는다.
- 신규 실행 파일의 백업·복원·정리, 삭제 전 백업 복원 시 최신 삭제 이력 재적용, 참조 해시 불일치 거절이 통과한다.

## 추가 확인과 인계

Q07·Q09·Q11. provider 설정·실제 호출·프론트 AI 시작 기능은 C07B에서 연결한다. 구판 worker 경로는 실제 대체물이 들어오기 전까지 보존하며, 종류별 최소 분기 외의 공통 엔진 재설계는 하지 않는다.

## 구현 및 검증 기록 — 2026-10-01

- [x] `runs.kind`의 구판 기본값 `legacy`와 `scoring_v3`·`report_v3`를 분리했다. 신판 채점은 `run_v3.py`·`domain/runs_v3.py` 계약을 사용하고 구판 세션/분기 파서로 전달하지 않는다. `report_v3`는 C10 연결 전 명시 실패 `v3_report_inactive`, 알 수 없는 종류는 `unsupported_run_kind`를 남긴다. 기존 구판 worker 경로는 보존했다.
- [x] SQLite10 migration으로 kind·request ID/hash·고정 입력 hash·실패 코드를 추가했다. 요청의 사례/세션/종류/ID는 UNIQUE이며, 기존 trigger를 DROP/CREATE하여 kind·요청·입력·설정·재사용 불변성을 적용했다. 더 높은 DB 버전은 WAL/schema 쓰기 전에 차단한다. 기존 DB 이관과 재기동 멱등성을 검사했다.
- [x] 접수는 expected revision·선택 세션·고정 부모 ref/hash·전체 촬영/영상·확정 BatchV3 창/클립·카탈로그/절차/창/계산 판본·항목군별 prompt/schema/model·제작/요청 fps·해상도·호출/시도/수리 상한을 고정한다. 채택된 전처리 audit·사례/세션/revision/원본을 대조한다. 긴 해시 검사는 쓰기 transaction 밖에서 수행하고 두 번째 검사 후 파일 stamp·DB revision·계정 권한을 접수 직전에 재확인한다. 같은 요청은 재전송/동시 접수에도 같은 run ID이며 다른 입력은409다.
- [x] 공통 claim/lease/heartbeat·불변 attempt 경로·token/lease/삭제 fence를 재사용했다. 신판 envelope에는 kind/attempt/stage/key를 추가한다. 최신 미채택 attempt만 복구하며 동일 바이트의 envelope 검증과 SHA256을 사용한다. 채택은 정확한 attempt 경로/hash/envelope와 transaction 직전 stamp·최신 attempt를 다시 확인한다. 미완·손상 후보는 abandoned이며 새 시도도 기존 상한을 지킨다.
- [x] 호출은 현재 점유한 running attempt에서 한 번만 예약한다. 단계별 시도 최대3회·schema 수리 최대1회·전체 호출 상한을 명시적 재시도에서도 유지한다. 예약 호출의 통신 중단·불완전 후보·명시적 중지에 `worker_interrupted`/`billing_uncertain`을 보존한다. 미확인 비용을0으로 만드는 코드는 추가하지 않았다.
- [x] 재사용은 성공한 다른 실행 단계의 정확한 ref/hash와 명시 manifest로만 수행한다. 같은 사례/세션·고정 입력/원본/클립/창/판본·항목군·prompt/schema/model·제작/요청 fps/해상도를 compatibility hash로 비교한다. 원래 사용량은 다시 더하지 않으며 자동 재사용·카메라/겹친 창 횟수 합산을 추가하지 않았다.
- [x] 생성·상태·중지·재시도 API를 명시 모델로 추가했다. 운영 생성은 C07B 연결 전503 미활성 상태다. 주입 작업 함수는 Python 시험용 경계이며 앱/CLI의 가상 공급자·임의 실행 경로는 없다. 상태 API는 운영 상태/단계/예약/불확실성만 반환하고 AI 원값·근거·snapshot·파일 ref/hash를 공개하지 않는다. 실제 AI 결과는 C07B에서 C05 공개 절차로 연결한다.
- [x] 완료는 `cases.display_run_id`를 자동 변경하지 않는다. 실행 후 입력 편집은 고정 옛 입력을 보존하고 `outdated`로 표시한다. 기존 maintenance의 `runs`/`steps`/audit JSON 재귀 ref/hash 탐색이 새 부모/Batch/클립/결과까지 검증·백업한다. 기존 FK 삭제 순서로 새 실행도 정리되며 삭제 전 백업 복원은 최신 삭제 목록을 재적용하여 복원 사례/실행을 제거한다. 새 중복 관리 표는 만들지 않았다.
- [x] 최초 신규8개 통과(13.582초), 추가 복구/최신 attempt/삭제/foreign batch/시도 상한11개 통과(20.953초), cold 수정 포함13개 통과(24.265초). 마지막 구판 종류 경로 회귀1개 통과(1.283초). 최초 전체 백엔드208개 통과(212.884초); 수용 수정 뒤 최종 전체 결과는 아래 완료 기록으로 갱신한다. `app.import_catalogs --spec all --check`의8개 원본 대조와 `git diff --check` 통과. UI 변경이 없어 브라우저/화면 검증은 이 PR의 변경 범위에 포함되지 않는다.
- [x] 독립 cold review P2 두 건을 모두 수용하고 아래와 같이 보완했다. 독립 재검토에서 표적2개 직접 재실행(3.590초), 구판 envelope/채택 호환성 확인, 추가 actionable finding 없음.
- [x] 수용 수정 후 최종 전체 백엔드213개 통과(235.009초), 마지막 구판 retry_wait/점유 만료 실행 회귀를 포함한 최종 표적14개 통과(25.497초). 원본8개 대조·문서 링크·diff 공백 검사를 마치고 C06 base의 `veluga/pr-c07a-run-foundation`을 푸시한다. PR 연결은 아래 완료 기록으로 갱신한다.
- [x] 구현 커밋 `5d41e55` 푸시·[PR #33](https://github.com/syleeVeluga/k-dog-proj/pull/33) 생성과 현재 작업 연결을 완료했다. base C06(#32)이며 병합은 수행하지 않았다.

| 독립 리뷰 발견 | 수용 여부와 반영 | 검증 |
| --- | --- | --- |
| P2 호출 예약 뒤 OSError로 실행만 실패하고 과금 불확실성 누락 | 수용. 복구 가능한 running attempt는 유지하며 중단/예약 불확실성을 저장, 명시 stop에도 기록, 상태의 미채택 예약도 보수적으로 표시 | 예약 후 통신 중단과 명시 stop은 unknown billing, 비용0으로 대체하지 않음 |
| P2 복구 envelope 검사 뒤 다른 읽기의 해시를 채택할 수 있음 | 수용. `step_output`의 동일 바이트에서 검증/hash/stamp 생성, adopt의 exact ref/hash/envelope 재검증과 transaction 내 stamp/최신 attempt fence | 기록 직후 변조 거절, 복구 검증 직후 변조 후보 abandoned·다음 올바른 시도만 채택 |

의존성 온라인 확인일은2026-10-01이다. [C01 최신/선택/공식 API·호환성 표](K-DOG_PR-C01_판본이관과접수_v1.0_20260930.md)와 [C04 런타임 표](K-DOG_PR-C04_관찰창전처리_v1.0_20260930.md)의 잠금을 유지한다. [FastAPI 공식 최신 릴리스0.142.2](https://fastapi.tiangolo.com/release-notes/)와 [PyPI의 선택0.141.1](https://pypi.org/project/fastapi/), [Pydantic2.13.5](https://pypi.org/project/pydantic/), [Python 최신3.14.7](https://www.python.org/downloads/release/python-3147/)을 다시 확인했다. 선택은 기존 FastAPI0.141.1/Pydantic2.13.5/Python3.14.2이며 기존 잠금과 프로젝트 `>=3.14,<3.15`를 유지하려는 것이다. 사용 API는 기존 FastAPI request/response model·Pydantic v2 strict model/validator·Python sqlite3/hashlib/pathlib/threading이다. 새 설치·manifest/lock 변경·공급자 SDK/API 사용은 없다.

필수 codebase-memory MCP는 도구 목록에 없어 알린 직접 소스 fallback을 사용했다. 시험은 합성 불변 파일과 주입한 Python 작업으로 실행 기반을 검증한 것이며 실제 provider 호출0회다. 실제 고객 영상·두 전문가 채점·provider 검증 환경/자료는 없어 실증을 생략하고 C07B/C15로 인계한다. Q07/Q09/Q11은 고객 확인 대기 상태를 유지한다. 신판 리포트의 출력용 입력 계약은 C10에서 별도로 연결한다.
