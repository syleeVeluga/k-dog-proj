# PR-R01 채점 시트 저장 구조와 조회 API

버전: v1.0 · 2026-09-16 · 상태: 구현 계획 · 의존: 없음 · 다음: [R02](K-DOG_PR-R02_리포트입력과장선택_v1.0_20260916.md)

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md) §4. 근거: 01 §3(3상태 저장)·§5(사람 검수, 복수 채점자 기록 전부 보존), 05b(J=AI·K=사람·L=비고), P0 계획 §8 PR-5 행 「채점 시트 테이블(채점자×쌍×항목)」(P1에서 미구현).

## 목적

리포트의 입력 절반은 「한 쌍의 42항목 채점 시트」다. 계약 `app.domain.contracts.ScoreSheet`·`ItemScore`·`Rater`와 계산 `app.scoring.behavior_scores`는 P0에 있지만, **시트를 저장하는 곳이 없다.** 이 PR은 저장 구조와 저장·조회 API만 만든다. 시트를 실제로 만드는 주체는 P2다 — AI 채점(N7)이 `kind=ai` 시트를 쓰고, 검수 3열 화면(N8)에서 사람이 고쳐 `kind=human`·`final` 시트를 확정한다. **운영자가 채점을 파일로 옮겨 넣는 수동 경로는 만들지 않는다.** 리포트 시험은 05 예비촬영 엑셀에서 만든 fixture를 같은 API로 넣는다.

## 현재 상태

- `backend/app/domain/contracts.py:53` `ScoreSheet{sheet_id, case_id, session_id, catalog_version, rater{rater_id, kind, label}, recorded_at, items}` — 검증만 있고 저장 없음.
- `backend/app/domain/validation.py:9` `validate_score_sheet(sheet, catalog, mode)` — 채점 대상 41항목 정확히·라벨 있는 점수만.
- `backend/app/storage.py:33` `SCHEMA`에 시트 표 없음. `runs`·`steps`는 55항목 실행용.
- `backend/tests/test_scoring_golden.py:62` `read_pairs(catalog)`가 05 엑셀에서 6쌍의 `ScoreSheet`를 만든다 — 시험 fixture 변환기로 재사용한다(제품 코드가 아님).

## 설계 결정

1. **시트는 불변 파일 + DB 색인.** 매니페스트(`inputs/`)·클립(`clips/`)과 같은 방식: `sheets/<case_id>/<sheet_id>.json`을 `xb`로 쓰고 SHA-256을 표에 둔다. 수정은 새 시트(새 `sheet_id`)이며 이전 시트는 지우지 않는다(01 §5 「기록을 모두 남겨야 한다」). ICC 계산(P2)이 이 이력을 쓴다.
2. **시트 상태는 `draft | final`.** 리포트(R02)와 결과 조회는 `final`인 **사람** 시트만 쓴다. AI 시트는 항상 `draft`이며 리포트 입력이 될 수 없다(01 §5 사람 검수 필수). `final`은 검수 화면(P2)에서 사람이 「확정」을 눌러야 된다.
3. **채점자는 문자열 ID + 종류 + 표시 이름.** 앱 계정과 1:1로 묶지 않는다(교수·외부 채점자는 계정이 없을 수 있음). 저장을 수행한 앱 계정은 `changes.actor`에 남는다.
4. **입력 revision·세션에 묶는다.** 시트는 `case_id`·`session_id`·`input_revision`(당시 확정 구간·영상)을 기록한다. 이후 입력이 바뀌어도 시트는 유효하지만 리포트는 「이전 입력 기준」이 된다(R04). 채점은 영상을 보고 한 것이므로 구간 시각 수정만으로 무효가 되지는 않는다.
5. **P2와 함께 쓰는 최소 API.** `POST`(저장)·`GET`(목록·본문·결과)만. 검수 화면·AI 채점이 어떤 순서로 저장하든 이 API를 지나간다.

## 변경 범위

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/storage.py` | 변경 | `SCHEMA`에 `score_sheets(sheet_id PK, case_id REFERENCES cases, session_id, input_revision, rater_id, rater_kind CHECK IN('ai','human'), rater_label, status CHECK IN('draft','final'), catalog_version, sheet_ref UNIQUE, sheet_hash, recorded_at, created_at)` 추가. `Store.__init__`에 `sheets` 폴더 생성. `user_version 7`(표 추가만, 이관 없음). `sheet(db, sheet_id) -> ScoreSheet` 읽기(해시·case_id·session_id 대조, 불일치 409 — `manifest()`와 같은 형식) |
| `backend/app/sheets.py` | 신설 | `save_sheet(store, db, case_id, sheet: ScoreSheet, *, status, actor)`: 삭제 요청 상태 확인(`store.case`), 세션 존재 확인, `kind=ai`면 `status=final` 거절(422), `validate_score_sheet` 호출, 파일 `xb` 저장, 행 삽입, `changes` 감사 `sheet.save{sheet_id, hash, rater_id, kind, status, counts{scored, unreadable, not_applicable}}`. 같은 채점자·세션의 직전 시트와 항목이 전부 같고 상태도 같으면 새 시트를 만들지 않고 기존 `sheet_id`를 돌려준다(멱등). `list_sheets(db, case_id, session_id=None)`, `final_sheet(store, db, case_id, session_id, rater_id=None)`(가장 최근 `final` 사람 시트; `rater_id`로 고를 수 있음), `sheet_result(store, db, sheet_id, catalog) -> ScoreResult`(behavior_scores) |
| `backend/app/input_models.py` | 변경 | `SheetCreate{expected_revision, session_id, rater{rater_id, kind, label}, status, recorded_at, items[{item_id, score, status, reason}]}`(계약 `ScoreSheet`로 변환), `SheetView{sheet_id, session_id, input_revision, rater, status, recorded_at, counts{scored, unreadable, not_applicable}, sheet_hash}`. `CaseView`에는 시트를 넣지 않고(목록 응답 크기 유지) `sheet_summary{final_human: bool, raters: int}`만 둔다 — 리포트 메뉴(R06) 목록이 이 둘만 필요 |
| `backend/app/api.py` | 변경 | `POST /api/cases/{id}/sheets`(writer, 201; `expected_revision` 불일치 409) · `GET /api/cases/{id}/sheets`(reader) 목록 · `GET /api/cases/{id}/sheets/{sheet_id}`(reader) 본문 · `GET /api/cases/{id}/sheets/{sheet_id}/result`(reader) → `ScoreResult`. 검수 화면·AI 채점 라우트는 P2 |
| `backend/app/maintenance.py` | 변경 | `MANAGED`에 `"sheets"`. `references()`가 `score_sheets` 표도 순회하도록 `for table in (...)`에 추가 |
| `frontend/src/types.ts` | 변경(최소) | `Case.sheet_summary`. 화면 변경 없음(R06이 쓴다) |
| `backend/tests/report_fixtures.py` | 신설 | `read_pairs()`로 만든 05 6쌍 시트를 `POST /sheets` 본문(`SheetCreate`)으로 바꾸는 도우미. R02~R08 시험이 공유 |
| `backend/tests/test_sheets.py` | 신설 | 아래 |
| `docs/DEVELOPMENT.md` | 변경 | 「채점 시트」 절: 파일 위치, `final` 사람 시트만 계산·리포트에 쓰임, AI 시트는 `draft`만, 시트는 P2 검수 화면·AI 채점이 만든다 |

## 시험 (`backend/tests/test_sheets.py`)

- 05 6쌍 fixture를 `POST /api/cases/{id}/sheets`로 저장 → 파일 해시·행·감사 기록·`GET .../result`가 `test_scoring_golden`의 기대값과 같은 `ScoreResult`를 낸다(골든 재사용).
- 계약·검증: `DOG-22`(자동 계산) 포함 거절, 냄새 4점 거절(`allowed_scores` — 엑셀 도우미 열이 0으로 만드는 값을 저장 단계에서 거절, P0 §1), 사유 없는 `unreadable` 거절, 41항목 누락 거절, `kind=ai`+`final` 거절.
- 멱등: 같은 채점자가 같은 항목을 다시 저장 → 새 시트 없음. 한 항목이라도 다르면 새 `sheet_id`, 이전 시트 보존.
- `final_sheet`: 사람 `final` 둘이면 최근 것, `rater_id` 지정 시 그 채점자, AI `draft`만 있으면 None.
- 권한: reviewer 저장 403·조회 200, developer 403, 삭제 요청 참가자 403, `expected_revision` 불일치 409.
- 무결성: 파일 바이트 수정 후 조회 409, 다른 참가자 `sheet_id` 접근 404.
- `maintenance.backup` 결과에 `sheets/` 파일 포함, `clean`이 참조된 시트를 지우지 않음. `Store` 재시작 시 `user_version 7` 멱등.

## 완료 조건

1. 05 예비촬영 6쌍이 API로 저장되고, 시트 결과 조회가 골든 테스트와 같은 값을 낸다.
2. 라벨 없는 점수·자동 계산 항목·사유 없는 미판독·AI `final`이 저장 단계에서 거절된다.
3. 시트 파일은 덧쓰기되지 않고(`xb`), 백업·정리에 포함되며, 해시 불일치는 409로 드러난다.
4. 백엔드 전체 시험·`--check`·`git diff --check` 통과. 화면 변경은 타입 추가만이라 `npm run build` 통과.

## 미결·주의

- **채점자 역할.** 현재 `reviewer`(교수/검토자)는 모든 쓰기가 403이다. 교수가 검수 화면에서 직접 채점을 저장하려면 P2에서 역할 또는 채점자 위임 방식을 정해야 한다. 이 PR의 `POST /sheets`는 writer(운영자·관리자) 기준이며, P2가 역할을 넓히면 같은 라우트의 권한만 바꾼다.
- **여러 채점자 중 리포트용 시트 선택.** 기본은 「가장 최근 `final` 사람 시트」. 운영자가 고르는 화면은 R06에 둔다.

권장 PR 제목: `feat: 채점자별 42항목 시트 저장 구조와 조회 API`
