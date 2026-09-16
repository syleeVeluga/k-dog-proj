# PR-R04 리포트 생성 실행과 저장 — worker 분기·불변 산출물·승인·조회 API

버전: v1.0 · 2026-09-16 · 상태: 구현 계획 · 의존: [R03](K-DOG_PR-R03_HTML템플릿과그래픽_v1.0_20260916.md) · 다음: [R06](K-DOG_PR-R06_리포트메뉴_v1.0_20260916.md), [R05](K-DOG_PR-R05_관찰서술생성과원칙검사_v1.0_20260916.md)

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md) §2·§4. 근거: 변경검토 §3(재사용: worker `stage/claim/guard`, 불변 산출물·해시), 검수인계 §3 「55항목 파이프라인은 삭제하되 모듈은 P2까지 보존 … 새 코드가 이 모듈에 의존하면 결함」, P1 계획 §0 「옛 코드는 대체물이 들어오는 PR에서 지운다」, A08(전처리 수동 실행의 잠금 문제 — 같은 함정을 피함).

## 목적

리포트를 **실행(run)** 으로 만들고 결과 HTML을 불변 파일로 저장한다. 결정적 부분(R02·R03)은 빠르지만 R05의 AI 서술은 분 단위이므로 처음부터 worker 경로로 둔다. 승인·「이전 입력 기준」·조회·내려받기 API를 만들고, 대체물이 들어왔으므로 옛 55항목 리포트 코드(`reporting.py`·`report_models.py`·`report-presentation-v1.json`)를 삭제한다.

## 현재 상태

- `worker.py:207` `Worker.process(row)`는 55항목 단계(`survey→prepare→observe/…→integrate→evaluate→report`)만 안다. `Worker.__init__:45`가 `app.reporting.Reporter`를 만든다.
- `analysis.py`의 `claim(store)`·`guard`·`write_output`·`adopt`·`later`·`digest`는 실행 종류와 무관한 인프라다 — 재사용. 단 `analysis.py`는 legacy 계약을 import하므로 **새 코드는 이 함수들만 쓰고 나머지에 의존하지 않는다.**
- `runs` 표: `config_snapshot_json`·`input_snapshot_json`은 불변(트리거), `status`·`result_ref`·`result_hash`·점유 열은 갱신 가능. `cases.display_run_id`는 `storage.Store.save()`가 입력 변경마다 NULL로 만든다 — **승인본 무효화에 그대로 쓴다.**
- `maintenance.MANAGED`에 `reports`가 없고, `references()`는 `runs.result_ref/result_hash`·`steps.output_ref/output_hash`를 따라간다 → 산출물을 `runs.result_ref`에 두면 백업·정리에 자동 포함.
- `api.py`에 리포트 라우트 없음(PR-10에서 삭제). `CaseView.analysis_status`는 `display_run_id`의 run 상태를 보이지만 화면은 읽지 않는다.
- `exports.py:23`이 `reporting`의 `NOTICE, PRESENTATION, read_saved, run_row`를 import한다.

## 설계 결정

1. **실행 종류 `kind`.** `runs.config_snapshot_json = {"kind": "report-v2", "rules_version", "catalog_version", "scoring_rule_version", "sheet_id", "sheet_hash", "narrative": {…설정 스냅샷 또는 null}, "created_by"}`, `input_snapshot_json = ReportInput(narrative=None) JSON`. `Worker.process`는 첫 줄에서 `kind`를 읽어 `report-v2`면 `app.report.store.process(worker, row)`로 넘기고, 없으면(옛 run) 기존 경로. P2가 `scoring-v2`를 같은 자리에 추가한다.
2. **단계 3개, 분기 키는 입력 해시.** `bundle`(`ReportInput` 재구성·`digest` 대조 — 입력이 바뀌었으면 실패 `input_changed`), `narrate`(R05, 설정이 없으면 건너뜀), `render`(HTML 생성 → `reports/<case_id>/<run_id>/report.html` + `report.json`(ReportInput 최종본) `xb` 저장, 해시). `runs.result_ref`=HTML, `result_hash`=SHA-256. 상태: `queued → running → draft`(성공) / `failed` / `settings_required`(서술 설정은 있는데 키 없음) / `retry_wait`.
3. **승인은 감사 기록 + `display_run_id`.** `POST …/reports/{run_id}/approve`(writer): run이 `draft`, `result_hash`가 파일과 일치, `input_revision`·시트 해시가 현재와 같음을 확인한 뒤 `cases.display_run_id = run_id`, `changes` `report.approve{run_id, result_hash}`. 이후 입력 변경으로 `display_run_id`가 NULL이 되면 조회 응답이 `superseded_by_input`(이전 입력 기준)로 표시한다. 승인 취소는 `report.revoke`(display_run_id NULL).
4. **판(版)은 run 단위.** 서술 수정(R06)은 `narrative_override`를 담은 **새 run**을 만든다(AI 호출 없이 `render`만). 이전 판은 남는다. 한 참가자에 `draft`가 여럿일 수 있고, 승인본은 하나다.
5. **입력 준비 검사는 API에서 먼저.** `POST …/reports`는 구간 확정·`final` 시트·(설문은 선택) 확인 후 409를 즉시 돌려주고, 그 뒤 worker가 같은 검사를 다시 한다(점유 중 변경 대비).
6. **worker와 API의 잠금 관계는 그대로.** 실행기가 띄운 worker가 처리한다. A08의 전처리 잠금 문제는 여기 없다(CLI가 아니라 run 큐).

## 변경 범위

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/report/store.py` | 신설 | `enqueue(store, case_id, session_id, actor, *, sheet_id=None, narrative_override=None) -> RunView`, `process(worker, row)`(3단계; `worker.stage`·`worker.reserve_call`·`analysis.write_output/adopt` 사용), `view(store, db, case_id) -> list[ReportRunView]`, `approve/revoke`, `html_path(store, db, case_id, run_id)`(해시 재검증 후 경로), `status_of(case_row, runs)`(아래 상태표) |
| `backend/app/report/models.py` | 신설 | `ReportRunView{run_id, session_id, input_revision, status, kind, created_at, updated_at, sheet_id, rater_label, chapters: [{key,title,number}], omissions, narrative_status: none\|ai_draft\|edited, approved: bool, superseded: bool, result_hash}`, `ReportCreate{expected_revision, session_id, sheet_id\|None}`, `ReportApprove{expected_revision, result_hash}`, `ReportListView{configured: bool, message, runs}` |
| `backend/app/worker.py` | 변경 | `__init__`에서 `Reporter` 제거(`reporter` 인자 삭제). `process()` 첫 줄 `kind` 분기. `stage()`·`reserve_call`·`fail`·`heartbeat`는 그대로. 55항목 경로의 `from app.reporting import generate_report`(:275, :497 두 곳) 호출은 `report_source=None`으로 대체(옛 run은 모두 종료 상태라 실행되지 않지만 import가 깨지지 않게) |
| `backend/app/api.py` | 변경 | `POST /api/cases/{id}/reports`(writer, 201) · `GET /api/cases/{id}/reports`(reader) · `GET /api/cases/{id}/reports/{run_id}`(reader, 상세 = `ReportRunView` + `ReportInput`) · `GET /api/cases/{id}/reports/{run_id}/html`(reader; `FileResponse` text/html, **자체 CSP** `default-src 'none'; style-src 'unsafe-inline'; font-src 'self'; img-src data:`, `Content-Disposition: inline`) · `GET …/html?download=1`(standalone 렌더를 즉시 만들어 `attachment; filename="{event}_{sequence or participant}_리포트.html"` — 저장 파일과 폰트 선언만 다름; 해시는 응답 헤더 `X-KDOG-Source-Hash`) · `POST …/reports/{run_id}/approve` · `POST …/reports/{run_id}/revoke` · `POST …/reports/{run_id}/cancel`(queued/running → stopped, 기존 55항목 cancel 로직 재사용 가능한 부분만). `GET /fonts/NanumGothic-Regular.ttf` 정적 제공(`StaticFiles` 또는 FileResponse, 캐시 허용) |
| `backend/app/input_models.py` | 변경 | `CaseView.analysis_status` → `report_status: Literal["needs_segments","needs_sheet","ready","queued","running","draft","approved","superseded","failed","settings_required"]` + `superseded_reason`(아래 표). `display_run_id`는 응답에 노출하지 않음 |
| `backend/app/storage.py` | 변경 | `view()`가 `report_status`를 계산(`display_run_id`·최신 report run). `Store.__init__`에 `reports` 폴더 |
| `backend/app/maintenance.py` | 변경 | `MANAGED`에 `"reports"` |
| `backend/app/launcher.py` | 변경 | `REQUIRED`에 `resources/rules/report-v2.json`, `resources/report/report-v2.css` |
| 삭제 | — | `backend/app/reporting.py`, `backend/app/report_models.py`, `resources/report-presentation-v1.json`. `exports.py`는 `reporting` import를 끊고 `NOTICE`·`read_saved`·`run_row`를 파일 안으로 옮김(`PRESENTATION` 참조 함수는 N10 전까지 호출되지 않으므로 상수를 빈 dict로 두고 주석) — 모듈이 import되는지만 시험 |
| `backend/tests/test_report_run.py` | 신설 | 아래 |
| `docs/DEVELOPMENT.md` · `docs/README.md` | 변경 | 「리포트」 절(실행 종류·상태·파일 위치·승인), 리포트 계획 폴더 링크 |

## 참가자 리포트 상태(`report_status`)

| 값 | 조건 | 화면 문구(R06) |
| --- | --- | --- |
| `needs_segments` | 8구간 미확정 | 「촬영 메뉴에서 8구간을 확정하세요」 |
| `needs_sheet` | 구간은 확정, `final` 사람 시트 없음(AI `draft`만 있어도 여기) | 「채점 화면에서 사람 검수를 확정하세요」 |
| `ready` | 입력은 갖췼고 report run 없음(설문 미등록이면 함께 표시 — 설문 없이도 생성 가능) | 「생성 가능」 / 「생성 가능 · 설문 미등록」 |
| `queued` / `running` | 최신 run 상태 | 「생성 중」 |
| `draft` | 최신 run 성공, 승인 없음 | 「초안 — 확인 후 승인」 |
| `approved` | `display_run_id`가 report run | 「승인」 |
| `superseded` | 승인 이력은 있으나 `display_run_id` NULL(입력 변경) 또는 승인 run의 시트 해시 ≠ 현재 final 시트. 응답에 `superseded_reason: survey \| segments \| sheet \| participant`(마지막 `changes` 기록으로 판정) | 「이전 입력 기준(설문 변경) — 다시 만들기」 |
| `failed` / `settings_required` | 최신 run | 사유와 「다시 시도」 |

한 번에 한 가지만 말한다. 두 조건이 함께 빠지면 절차 순서(구간 → 시트)대로 먼저 것을 보인다.

## 시험 (`backend/tests/test_report_run.py`, `support.AppCase` + `Worker(store).once()`)

- 준비: 참가자 생성 → 합성 영상 등록 → 8구간 확정(`PUT …/segments confirm`) → R01 `POST /sheets`로 fixture 시트 저장(`tests/report_fixtures.py`) → 설문 가져오기.
- 생성: `POST /reports` 201 → `once()` → `draft`; `reports/<case>/<run>/report.html` 존재·`xb`·`result_hash` 일치; `GET …/html` 200 + 자체 CSP 헤더; `?download=1`은 `@font-face` 없음·외부 URL 없음.
- 사전 검사: 구간 미확정 409, 시트 없음 409, reviewer 403, 삭제 요청 403.
- 결정성: 같은 입력 두 run → `result_hash` 동일.
- 입력 변경: 승인 뒤 설문 재가져오기 → `report_status=superseded`, 승인 run HTML은 여전히 조회 가능(이력), `approve`에 옛 `result_hash` 넣으면 409.
- 시트 교체: 새 `final` 시트 저장 → 기존 draft는 `bundle` 단계에서 `input_changed`로 실패하지 않고(스냅샷 기준으로 렌더는 가능) 상태만 `superseded` 표시 — 스냅샷 원칙(불변 run)을 지킨다.
- worker 중단 복구: `running` run의 점유 만료 후 `claim`이 다시 잡아 완료(기존 `LEASE_SECONDS` 시험 방식).
- 옛 run 보존: legacy `runs` 행이 있어도 `Worker.once()`가 건드리지 않고(모두 종료 상태), `kind` 없는 config를 만나면 옛 경로로 들어간다(합성 행으로 분기만 확인).
- `maintenance.backup`에 `reports/` 포함, `clean`이 승인·초안 파일을 지우지 않음.
- `reporting`·`report_models` import가 저장소 어디에도 없음(`grep`).

## 완료 조건

1. 구간 확정 + 사람 시트 + 설문이 있는 참가자에서 `POST /reports` → worker → 조회·HTML 다운로드가 끝까지 되고, 결과가 결정적이다.
2. 승인 뒤 입력이 바뀌면 `superseded`가 되고, 승인 HTML은 이력으로 남는다.
3. 옛 55항목 리포트 코드가 삭제되고 `exports.py`는 독립적으로 import된다. 새 코드는 `app.legacy`·`evaluation`·`video_evaluation`·`ledger`를 import하지 않는다.
4. 백엔드 전체 시험·`launcher --check`·`git diff --check` 통과.

## 미결

- `runs` 표의 열 이름(`input_snapshot_json` 등)은 55항목 판 용어지만 의미가 같아 그대로 쓴다. P2에서 `kind` 열을 실제 열로 승격할지 결정.
- 내려받기 파일명에 보호자 이름을 넣지 않는다(01 §7). 행사·순번 기준.

권장 PR 제목: `feat: 리포트 실행(report-v2) worker 분기·불변 HTML 산출물·승인 API, 옛 리포트 코드 삭제`
