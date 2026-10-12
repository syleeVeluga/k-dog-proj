# PR-ES01 전처리 내 실행 조회와 진행 계약

버전: v1.0 · 2026-10-12 · 상태: 구현·검증·독립 cold review 수용 반영·재검토 완료 / 병합 완료 · 기준 commit: `1702f2b`
상위: [전체 계획](K-DOG_내실행과분석진행표시계획_v1.0_20261012.md) · 선행: 없음 · 다음: [ES02](K-DOG_PR-ES02_전처리내작업화면과자동갱신_v1.0_20261012.md)
권장 브랜치: `codex/es01-preprocess-executions` · PR 제목: `feat: 전처리 실행별 내 작업 조회와 진행 상태 제공`

## 1 문제와 결과

현재 `/cases`는 공유 참가자 진행 요약이고, 전처리 상세 상태는 회차의 최신 시도와 이전 완료 batch를 조합한다. 실행 직원·시작/종료 시각·개별 시도 DTO가 없어 내 작업 목록으로 쓸 수 없다. 전처리 POST는 `asyncio.to_thread`에서 실제 처리가 끝날 때까지 응답하지 않는다. 시작/완료/실패 사이의 단계 기록도 없다.

이 PR은 기존 공유 상태/결과 조회와 별도로 **실행 원장 기반 내 작업 조회**와 **실제 전처리 단계 기록**을 제공한다. 실행 방식·계산·영상 생성 정책·업무 접근 권한을 바꾸지 않는다.

근거: [API](../../../backend/app/api.py#L553), [시작 원장](../../../backend/app/preprocess_v4.py#L405), [완료/실패](../../../backend/app/preprocess_v4.py#L460), [상태 DTO](../../../backend/app/domain/preprocess_v4.py#L151), [공유 상태](../../../backend/app/preprocess_v4.py#L491).

## 2 조회 계약

1. `GET /api/preprocess-s1/executions`를 신설한다. 인증된 현재 계정과 **시작 이벤트 actor**가 같은 실행만 반환한다. 클라이언트가 임의 username을 보내 조회 주체를 바꿀 수 없게 한다. 기본 최신순 50개, 다음 페이지 cursor와 검색/행사/상태 필터를 서버에서 적용한다. cursor는 고정 원장 순서로 처리하고 필터 전 50개 잘라 결과가 빠지지 않게 한다.
2. 한 실행의 안정 식별자는 기존 `batch_id`를 사용하고 연결은 `(case_id, session_id, batch_id, claim_token, request_id)`로 검증한다. 같은 대상·회차의 다른 직원/다른 시도·늦은 종료 이벤트를 섞지 않는다. 기존 `changes`의 actor/time/row 순서를 읽으며 원장을 재작성하지 않는다.
3. 실행 DTO 필드: `execution_id`, `case_id`, `session_id`, 참가자/반려견/행사 표시 정보, `input_revision`, `requested_by`, `started_at`, `finished_at | null`, `status`, `current_stage | null`, `stage_updated_at | null`, `message`, `outdated`, 해당 실행의 `result_pointer | null`. 원본 경로·claim token·오디오/영상/관찰·개인 설문 내용을 목록에 싣지 않는다.
4. 개별 실행 조회는 `GET /api/cases/{case_id}/sessions/{session_id}/preprocess-s1/executions/{execution_id}`로 제공한다. 공유 업무 접근은 유지하되 지정 실행의 원래 상태/결과를 읽는다. 결과 열기/미리보기는 기존 batch hash·회차·clip 검증 경로를 사용한다. 내 목록 필터가 원본/공유 결과 접근 조건이 되지 않는다.
5. 접수 거절/잠금 409처럼 시작 이벤트가 없는 요청은 실행 기록을 만들지 않는다. UI의 일시적 `요청 중`은 서버 실행 상태로 저장하지 않는다. POST에 사용한 `request_id`로 내 원장의 접수 여부를 확인할 수 있게 하여 응답 유실 때 동일 실행을 찾는다.

## 3 상태와 진행 계약

| 실행 상태 | 판단 | 목록 필터 |
| --- | --- | --- |
| running | 종료 없음 + 실제 전처리 잠금 점유 + 현재 활성 시작의 claim 일치 | 실행 중 |
| complete | 해당 실행의 검증된 완료 batch가 complete | 완료 |
| partial | 해당 실행의 완료 batch가 partial | 확인 필요 |
| failed | 같은 실행의 실패/대체 기록과 사유 | 확인 필요 |
| interrupted | 종료 없음 + 해당 claim이 실제 활성 작업이 아님 | 확인 필요 |

`outdated`는 당시 실행 상태를 바꾸지 않는 현재 입력/규칙에 대한 적합성 값이다. 성공 기록은 완료로 보존하고 `현재 입력과 다름` 배지를 표시한다. 상태 필터의 `완료`에는 정상 완료 이력을, `확인 필요`에는 partial/failed/interrupted 또는 outdated인 이력을 포함한다. 겹칠 수 있음을 문서/시험에서 명시한다.

- 종료 판정은 같은 실행의 원장과 검증된 해당 batch를 우선한다. 다른 시도의 이전 성공 batch를 이 실행의 결과로 붙이지 않는다.
- 현재 전처리는 전역 잠금으로 실행을 거절하며 큐가 없다. `대기` 상태/작업 큐를 추가하지 않는다. 중단 판정은 최신 전처리 시작 claim과 실제 잠금 양쪽을 확인한다.
- 실행 도중 실제 코드 경계에서 `preprocess_v4.progress` 원장 이벤트를 제한적으로 기록한다. 새 제작은 `clips → windows → verify_save`, 재사용은 `reuse_verify → verify_save`다. 진행 기록은 원래 실행 actor와 위 시도 식별자를 유지하며 원본 입력을 바꾸지 않는다.
- 각 단계 시작 때 한 번 기록한다. 프레임별 기록/로그 수집 시스템을 만들지 않는다. 예정 클립 수는 현재 코드에서 전체 계획을 미리 확정하지 않으므로 완료율/예상시간을 표시하지 않는다.
- 기존 `_history`/guard/중복 요청 검사의 의미를 진행 이벤트 때문에 바꾸지 않는다. 활성 점유/종료 판단은 기존 시작/종료 원장만 사용하고 진행 이벤트는 별도로 읽는다. 기존 superseded 종료도 실행별 조회에서 포착한다.
- 과거 실행에는 단계 기록을 역으로 만들지 않는다. 완료/실패 시각이 있으면 그대로 표시하고 당시 단계가 없으면 `단계 기록 없음`으로 둔다. 진행 조회는 과거 결과를 새 입력으로 채택하지 않는다.
- POST 중에는 입력 revision·원본 hash·자산 hash·actor 활성 상태·claim guard를 유지하고, 결과 게시 후에는 마지막 진행 이벤트보다 완료 상태가 우선한다.

## 4 변경 위치와 경계

| 파일 | 변경 |
| --- | --- |
| `backend/app/domain/preprocess_v4.py` | 실행 조회 DTO/단계 상태 계약 추가, 기존 공유 DTO 유지 |
| `backend/app/preprocess_v4.py` | 원장 기반 조회/실행 연결·실제 단계 이벤트; 필요하면 전용 작은 조회 모듈 분리 |
| `backend/app/api.py` | 내 목록·개별 실행·request_id 접수 확인 API 연결 |
| `backend/tests/test_preprocess_v4.py` | 기존 처리·hash·guard·명시 재사용 회귀 |
| `backend/tests/test_preprocess_execution_v4.py` | 신설: 직원/시도/회차별 조회·진행·원장 보존 검증 |

구현 전 Graft callers로 `execute/status/_history`와 API·guard 호출 영향을 확인한다. 기존 DB schema/점수/영상 제작 계약을 이 PR에서 재구축하지 않는다. 새로운 인덱스는 실제 조회 계획에서 필요할 때만 추가한다.

## 5 인수 기준과 검증

- [x] ES-T01: A 완료 후 같은 대상 B 실패. A 목록/상세의 완료·결과 hash가 유지되고 B 목록에 B 실패만 표시된다. 제3자도 공유 결과/재사용 경로를 사용할 수 있다.
- [x] ES-T02: 같은 직원의 여러 시도·이전 회차·새 입력·명시 재사용이 별도 행으로 보존된다. 완료와 outdated의 교집합/필터가 계약대로 동작한다.
- [x] ES-T03: 실제 잠금 점유/해제와 claim 교체로 running/interrupted를 구분한다. 다른 작업의 잠금으로 오래된 시작을 running으로 오판하지 않는다. 409를 큐 대기로 만들지 않는다.
- [x] ES-T04: 진행 이벤트가 중복 요청/guard/종료 판정에 간섭하지 않고 같은 request_id의 기존 idempotency/다른 actor 또는 내용의 409가 유지된다. 늦은 실패/완료는 해당 시도에만 연결된다.
- [x] ES-T05: 51개 이상 이력의 페이지·필터·정렬, 계정 actor 일치, 빈 목록, request_id 조회, 이전 단계 기록 부재, 손상/유실 결과 ref를 검증한다. 손상 결과를 정상 완료로 제공하지 않는다.
- [x] ES-T06: 새 진행 이벤트가 없어도 기존 원장이 정상 조회되며, 이전 DB/불변 batch/원본/감사 bytes는 유지된다. 상태 조회는 AI 호출·입력 revision·실제 열람 기록을 만들지 않는다.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest tests.test_preprocess_v4 tests.test_preprocess_execution_v4 -v
# repository root
git diff --check
```

상태 전이 시험은 임시 합성 저장소와 명시 잠금/처리 경계 제어를 사용한다. 제품 최신 의존성 검증·cold review·수용 반영·실행 기록/푸시는 전체 계획 절차를 따른다. 위 체크는 아직 실행하지 않았다.

## 6 구현 실행 기록 — 2026-10-12

- 착수 기준: `main / 1d62f12`, 깨끗한 작업트리. 브랜치 `veluga/es01-preprocess-executions`.
- 기존 원장을 재작성하지 않고 시작 actor·rowid와 회차/batch/claim/request 식별을 대조하는 전용 조회 모듈을 추가했다. 목록은 필터 적용 후 50개를 반환하고 rowid cursor로 다음 페이지를 연결한다. request_id 조회와 공유 개별 실행 상세를 제공한다.
- 새 제작은 clips/windows/verify_save, 명시 재사용은 reuse_verify/verify_save 시작 이벤트만 기록한다. 기존 `_history`의 시작/종료 범위와 guard/idempotency는 유지한다.
- 완료 batch/input/clip hash와 요청 내용을 검증한다. 손상·유실 결과는 실패 안내와 null 결과 pointer로 제공한다. 당시 성공과 현재 입력/규칙 적합성(outdated)을 분리한다.
- 합성 검증: 기존 `tests.test_preprocess_v4 tests.test_preprocess_api_v4` 15개 통과(34.353초). 신규 `tests.test_preprocess_execution_v4` 6개 통과(7.549초). 실제 외부 AI 호출 0건. 운영 자료 변경 없음.
- 의존성 확인일 2026-10-12: FastAPI 최신 0.143.0 / 선택 0.141.1, Pydantic 최신 2.14.1 / 선택 2.13.5. 기존 Python 3.14 잠금 환경과 선택판의 query/response_model 및 model_validate/model_dump API를 확인했다. 범위 밖 의존성 업그레이드와 새 패키지는 도입하지 않는다. FastAPI 0.143의 breaking change도 이 변경에 혼합하지 않는다.
  - [FastAPI registry](https://pypi.org/project/fastapi/), [선택판](https://pypi.org/project/fastapi/0.141.1/), [release notes](https://fastapi.tiangolo.com/release-notes/), [response DTO](https://fastapi.tiangolo.com/tutorial/response-model/)
  - [Pydantic registry](https://pypi.org/project/pydantic/), [선택판](https://pypi.org/project/pydantic/2.13.5/), [changelog](https://docs.pydantic.dev/latest/changelog/), [model API](https://docs.pydantic.dev/latest/concepts/models/)
- 독립 cold review·수용 판단·수정 재검증·PR 병합은 아래에 실제 결과를 추가한다.

- 확대 검증: 신규6개 + 실제 actor/공유 진행 회귀16개, 합계22개 통과(39.427초). 신규 최종11개 통과(12.509초). 원본 손상·claim 조회 경쟁·이전 회차·부분 결과·잠금 거절을 추가 검증했다.
- 독립 cold review P2 2건 수용: (1) 원본 source_files hash 검증 누락 → 결과 파일·입력·원본·clip 모두 검증 (2) 잠금 확인 전 최신 claim 조회 경쟁 → 실제 점유 확인 후 최신 시작 조회. 재현 시험 추가 후 reviewer가 2개 직접 통과 및 두 finding 해결·추가 actionable 0건 확인. 보류/거절 0건.
- ES-T01~06 완료. 단계 없는 과거 원장은 읽기만 하며 제품 원장/입력/감사 bytes를 재작성하지 않는다. 시험의 과거 원장 fixture 구성만 별도 임시 저장소에서 수행했다.

- 병합: [PR #87](https://github.com/syleeVeluga/k-dog-proj/pull/87), 구현 b7b3364, 원격/로컬 main 121d14a. ES02는 이 병합 commit에서 시작했다.
