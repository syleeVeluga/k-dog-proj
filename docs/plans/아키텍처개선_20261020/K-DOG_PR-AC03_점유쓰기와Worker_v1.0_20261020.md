# PR-AC03 점유 쓰기와 Worker

버전: v1.0 · 2026-10-20 · 상태: **구현·독립 검토 완료** · 기준: `bdc526f` · 직접 선행: 없음 · 후속: AC04

브랜치 제안: `veluga/ac03-owned-run-write` · 제목 제안: `refactor: centralize owned run write transactions`

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 요구 AC-R06·R07·R10~R12.

## 1 문제와 완료 결과

Worker의 예약·복구 실패 기록·새 attempt 생성·실패 기록은 write 트랜잭션을 열고 현재 run을 읽어 claim/running/lease와 실제 실행 계정을 각각 검사한다. 이를 기존 `analysis.py` module의 작은 interface 뒤로 모은다. **트랜잭션 열기부터 검증·commit/rollback·close까지** 함께 소유해 호출자가 검증과 쓰기를 분리할 수 없게 한다.

조건식을 반환하는 boolean helper나 별도 연결에서 실행하는 guard만 만들면 목적을 달성하지 못한다. `Store.connect`의 `BEGIN IMMEDIATE`와 예외 처리 의미를 재사용하며 새 transaction framework나 저장소 adapter를 만들지 않는다.

## 2 interface 및 import 방향

예정 형태는 `analysis.owned_write(store, row, *, conflict_detail)` context manager다. 유효한 현재 run을 읽고 공통 검사한 뒤 **같은 db와 current row**를 body에 제공한다. 구체적 이름/타입은 구현에서 확정한다.

1. `store.connect(write=True)`를 한 번 연다.
2. `row.run_id`의 현재 DB 행을 읽고 존재, `status == running`, 같은 `claim_token`, 아직 유효한 `lease_expires_at`를 확인한다. 실패는 작업 맥락의 기존 409 오류로 거절한다.
3. 기존 `analysis.check_access(store, db, current)`를 같은 연결에서 실행한다. 이 함수가 `s1/report_v4/attachment_v4`별 현재 실행 계정·입력 조건을 검사한다.
4. body가 같은 연결에서 필요한 판본/stamp/step 조건을 더 검사하고 기록한다.
5. 정상 종료면 기존 connect가 commit, 예외면 rollback, 항상 close한다. body 오류를 삼키거나 새 retry를 수행하지 않는다.

공통 module은 lease를 자동 갱신하지 않는다. 기존 `worker.check`·heartbeat의 실행 위치를 보존한다. 호출자가 `db`를 body 밖으로 가져가 쓰거나 같은 body에서 두 번째 write 연결을 열지 않는다. 네트워크 호출·무거운 계산·파일 생성은 원래 위치에 두며, 이미 필요한 최종 stamp 확인만 body 안에 둔다.

`analysis.py`는 이미 kind별 검사에 지연 import를 사용한다. `worker.py`가 이 module을 가져오는 기존 방향을 유지하며, 공통 module이 Worker나 새 provider engine을 import하지 않게 한다. 원래 `check_access` dispatch와 업무별 검증은 유지한다.

## 3 파일별 전환

| 파일/구간 | 적용 | 보존할 특수 동작 |
| --- | --- | --- |
| [analysis.py](../../../backend/app/analysis.py#L57) | owned_write 동작 추가; check_access 재사용 | guard·claim·adopt는 AC03에서 기존 실행 유지 |
| [Worker.reserve_call](../../../backend/app/worker.py#L48) | 현재 51~68행 write 수명을 공통화 | call 상한·한 step 한 예약·선택/audit·오류의 commit 시점 |
| [Worker.stage 복구](../../../backend/app/worker.py#L109) | 복구 불가 attempt의 abandoned 기록을 공통화 | 이전 usage와 call_reserved 기반 billing_uncertain |
| [Worker.stage 생성](../../../backend/app/worker.py#L131) | retry_wait supersede + 새 attempt INSERT를 같은 body에 유지 | attempt 순서·repair/총 시도 상한·불변 step_id |
| [Worker.fail](../../../backend/app/worker.py#L166) | usage 병합·예비키 요청·실패 상태 기록을 공통화 | fallback_status·retry_at·call_limit·attempt_limit·기존 usage |
| `backend/tests/test_owned_run_write.py` (신설 예정) | 실제 임시 SQLite의 rollback·점유 경쟁 결과 시험 | internal SQL 호출 횟수 단언 대신 기록 여부·불변 행 확인 |
| 기존 `test_run_v4`, `test_gemini_key_fallback`, `test_execution_actor_v4` | 실제 Worker 경로 회귀/보완 | 새 helper만 직접 시험하고 완료하지 않음 |

## 4 반드시 보존할 commit 의미

`reserve_call`은 **예약 성공 후 credential 선택 실패를 기록한 상태를 commit하고, 트랜잭션 밖에서 ProviderError를 다시 던진다.** 현재 `selected = failure = None`, 내부 try/except, 외부 raise 순서를 보존한다. 새 context body에서 그 예외를 즉시 전파하면 예약과 선택 근거까지 rollback될 수 있으므로 금지한다.

- 예약 전 예산 소진·다른 attempt·이중 예약 실패는 기존처럼 새 예약을 남기지 않는다.
- 현재 attempt만 `call_reserved=1`로 바꾸는 SQL 조건과 rowcount 판정을 유지한다.
- `fail`의 credential fallback 판단과 usage 병합은 같은 write body에 남는다. 성공한 이전 step을 다시 추론하지 않는다.
- `billing_uncertain`, cleanup 대기, 선택 슬롯/원격 파일 참조, `max_ai_calls`·`max_attempts`·schema repair 상한과 backoff를 바꾸지 않는다.
- `Worker.stage`의 기존 회복·validate·immutable output·채택 orchestration은 유지한다. AC03은 그 네 write 구간만 바꾼다.

## 5 같은 형태로 전환하면 안 되는 경로

| 경로 | 이유·유지 계약 |
| --- | --- |
| `analysis.claim` | queued/retry_wait/만료 점유에서 **새 소유권 획득**; live running 소유권을 전제로 할 수 없음 |
| `analysis.guard`·heartbeat | 읽기/갱신과 자체 연결의 수명; 뒤따르는 쓰기의 같은 연결 검사를 대체하지 않음 |
| `Worker.once` 208~219행 | access 실패나 자료 유실도 오류 종료해야 함. 현재 token/running 조건부 UPDATE와 usage 불확실성 기록 유지 |
| enqueue/action·명시 중지/재시도 | 활성 worker 점유가 아닌 사용자의 명시 요청 계약 |
| uploads/preprocess 실행 기록 | 별도 테이블·토큰·상태·보관 의미. `runs` 공통 쓰기의 대상이 아님 |

특히 `Worker.once`를 owned_write로 감싸면 inactive actor 등 원래 원인 때문에 실패 기록 자체가 거절되는 회귀가 생길 수 있다. 이 예외는 잔존 중복이 아니라 다른 책임이며 AC05 잔존 검토에 남긴다.

## 6 시험과 구현 순서

1. 기존 Worker/fallback/actor 회귀를 기준 실행하고 예약 선택 실패의 DB 상태를 특징화한다.
2. owned_write와 임시 SQLite 시험을 작성한다. 정상 commit, body 예외 rollback, validation 실패 무기록을 검증한다.
3. 네 write 구간을 전환하고 위 commit 특수 사례를 실제 Worker에서 재현한다.
4. AC04는 아직 기존 검사를 사용해도 정상 동작함을 확인한다. import 순환과 optional/현재 actor 해석을 검토한다.

| ID | 상황 | 기대·주 시험 |
| --- | --- | --- |
| AC-T11 | 트랜잭션 진입 직전 token 교체·중지·lease 만료·현재 actor 비활성/입력 변경 | body 기록 없음, 기존 오류/권한 의미; `test_owned_run_write`·`test_execution_actor_v4` |
| AC-T12 | 예약 상한·동일 step 이중 예약·예약 뒤 credential 선택 실패 | 상한 초과 새 호출 0, 한 예약만 기록, 선택 실패에도 이미 확정해야 할 예약 보존; `test_gemini_key_fallback`·`test_run_v4` |
| AC-T13 | 복구 실패·schema repair·fallback 대기·backup 실패·사용량 병합 | attempt/usage/retry_at·uncertain·예산 의미 동일; 같은 기존 시험 |
| AC-T14 | body가 기록 후 예외, Worker.once의 access 실패·옛 token 오류 종료, heartbeat와 쓰기 | 정상 body만 commit, 예외 rollback, 새 소유자 기록 변경 0, 실패 마무리 가능; 신설 및 기존 Worker 시험 |

경쟁 시험은 현재 guard 이후와 새 write 진입 사이에 두 번째 실제 DB 연결로 상태를 바꾸거나 기존 동기화 fixture를 사용한다. 테스트용 callback을 제품 interface에 노출하지 않는다. DB 파일과 immutable 산출물은 임시 경로만 쓴다.

```powershell
# backend/ — test_owned_run_write 신설 후
uv run --locked python -X utf8 -m unittest -v tests.test_owned_run_write tests.test_run_v4 tests.test_gemini_key_fallback tests.test_execution_actor_v4 tests.test_attachment_ai_v4 tests.test_report_runs_v4
# 저장소 루트
git diff --check
graft build
graft check
```

## 7 되돌림·AC04 인계·완료 기록

DB/schema/출력 형식을 바꾸지 않으므로 AC03 단독은 코드 revert로 되돌린다. AC04까지 적용되면 AC04를 먼저 되돌린다. 실패 시험을 맞추기 위해 lease·actor 검사를 약화하거나 상한을 늘리지 않는다.

AC04에 interface의 실제 이름/예외·commit 규칙과 제외 경로 목록, 예약 실패 증거를 인계한다.

- [x] AC-T11~T14와 기존 세 실행 흐름 회귀 통과
- [x] 네 write 구간의 같은 연결 검증·기록 확인
- [x] credential 실패 예약 commit와 once 오류 종료 증거
- [x] 공식 문서·버전 확인, 독립 cold review·수용 재검증

| 실행 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | `f58b21e` → 본 AC03 commit; `veluga/ac03-owned-run-write`; AC04 쓰기 전환은 후속 commit에 분리 |
| 시험 명령·건수·시간·결과 | 변경 전 기존 5모듈 74 tests / 309.026초 / OK. 신설 공통 시험 7 tests / 2.072초 / OK. 최초 결합 81건 중 감사 테이블명 fixture 오기 1건만 실패했고 해당 7건 수정 재검증. AC04/05에서 전체 결합 최종 결과 확정 |
| cold review·발견사항 조치 | 독립 backend reviewer: 소스 회귀 0건, 같은 db 수명·예약 commit/외부 raise·once 제외 확인. reviewer 보강 포함 owned/scoring 29 tests / 10.165초 / OK |
| AC04 인계 interface·commit 의미 | 예정 그대로 `analysis.owned_write(store, row, *, conflict_detail)` → `(db, current)`. 같은 Store.connect body에서 현재 claim/running/lease와 check_access 검사, 자동 갱신·재시도 없음. credential ProviderError는 내부 보관→commit→외부 raise. claim/guard/heartbeat/once/action/업로드·전처리 제외 |

2026-10-20 공식 확인: Python 최신 3.15.0·3.14 계열 3.14.8, 실행 3.14.2(`>=3.14,<3.15`); FastAPI 최신 0.148.0·선택 0.141.1, Pydantic 최신 2.14.1·선택 2.13.5, httpx 0.28.1. 기존 lock/runtime 유지와 무관한 업그레이드 제외. [Python 배포](https://www.python.org/downloads/)·[contextlib](https://docs.python.org/3.14/library/contextlib.html)·[sqlite3](https://docs.python.org/3.14/library/sqlite3.html), [FastAPI](https://fastapi.tiangolo.com/release-notes/)·[Pydantic](https://pydantic.dev/docs/validation/latest/get-started/changelog/)와 공식 PyPI registry의 runtime/API·변경점을 확인했다. AC05 통합 기록에서 전체 명령·잔존 분류를 연결한다.

최종 통합 근거·공식 버전·실측 한계는 [제품 실행 기록](K-DOG_아키텍처개선실행기록_v1.0_20261020.md)을 따른다.

2026-10-20 사용자 요청의 [PR별 추가 독립 cold review](K-DOG_아키텍처개선PR별ColdReview_v1.0_20261020.md) 결과와 후속 판단을 연결한다.
