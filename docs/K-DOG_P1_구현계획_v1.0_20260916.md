# K-DOG 42항목 판 P1 구현 계획 — PR-5 ~ PR-11 (촬영 당일 필수)

버전: v1.0 · 2026-09-16 · 상위 문서: [변경 검토 v1.0](K-DOG_변경검토_v1.0_20260915.md) 6장 P1, [P0 구현 계획](K-DOG_P0_구현계획_v1.0_20260916.md) 8장 · 근거: `docs/최종 고객 문서/` 01 §1·§2·§7, 04, 05b `구간_시각`

## 0. 범위와 원칙

P1은 10월 31일 현장에서 반드시 돌아야 하는 것 — **접수 · 설문 28 · 영상 파일 여러 개 등록 · 8구간 시각 기록** — 과 그 뒤에 이어지는 전처리 파이프라인을 만든다. AI 채점·검수·리포트·내보내기(P2·P3)는 다루지 않는다.

**화면은 대메뉴 단위로 PR을 나눈다.** 상단 주 메뉴는 `접수 · 설문 · 촬영 · 자료 가져오기 · 직원 계정`(+ 개발자 설정)이 되고, 메뉴 하나가 PR 하나다. 한 PR은 그 메뉴의 라우트·컴포넌트·API만 바꾼다.

**옛 55항목 분석 파이프라인은 P1에서 「동결」한다.** 이유는 P0 조사에서 확인됐다: `analysis.enqueue`·`worker.process`·`reporting`·`exports`·`settings.trial`은 모두 `Manifest.sessions[].survey`(q01~q30)와 옛 체크리스트를 입력으로 삼는다. 입력 계약을 28문항으로 바꾸면 새 자료로는 그 파이프라인을 시작할 수 없다. 그러므로 PR-5에서 (1) 새 run 시작·내보내기 생성·설명 생성을 409로 막고, (2) 저장된 옛 run은 `app/legacy/input_models_v1.py`로 계속 읽어 보여 주고, (3) 그 파이프라인을 돌리는 시험(fixture가 55항목·30문항에 묶인 것)은 삭제한다. 파이프라인 코드 자체는 P2에서 42항목 판 채점(N5·N7)이 들어오는 PR에서 대체·삭제한다. 옛 화면(분석·검토·보고서·내보내기 컴포넌트)은 PR-10에서 지운다.

검증 명령과 PR 절차는 P0 계획 §0과 같다. 프론트 변경이 있는 PR은 `frontend/`에서 `npm run build`(tsc 포함)와 `npm run test:e2e`를 추가로 통과해야 한다.

## 1. 입력 계약 v2 (intake-2.0) — PR-5의 뼈대

| 항목 | intake-1.0 (현행) | intake-2.0 | 근거 |
| --- | --- | --- | --- |
| 설문 | `survey: {q01..q30}` | `survey: {s01..s28}` + `survey_not_applicable: [s07|s08|s09]`. **입력은 사람이 CSV·Excel로 가져오기만** 하고 화면은 등록 현황을 읽기 전용으로 보인다(2026-09-16 결정) | 04, P0 §5 |
| 설문 버전 | `catalog-20260904-v1` | `catalog-20260913-v2` | — |
| 촬영 메타 | `capture_mode`(동시/순차) · `route_note` · `checklist`(입장/분리/훈련/놀이/퇴장) | `note`(자유 메모 2000자) | 01 §2 — 절차가 바뀌어 옛 체크리스트 무의미. 구간 기록은 PR-8의 `segments` |
| 영상 | `camera_id`·원본명·해시·크기 | 원본명·해시·크기만. 카메라 개념(ID·역할·연결)은 모두 없애고 한 쌍에 파일을 여러 개 등록한다(2026-09-16 결정) | 01 §1 ③ |
| 구간 시각 | 없음 | PR-8: `segments`(8구간 시작·끝·출처, 확정 여부) | 01 §2, 05b `구간_시각` |
| 참가자 | event_id·participant_id·dog_name·reservation_at | PR-6: + 순번·동의 확인·보호자명·견종·성별·나이·크기·함께 산 기간·입양 경로 | 01 §1 ①, 04 설문지 머리 |

기존 자료(시험 릴리즈 v0.1.0 사용자 폴더)는 `Store` 초기화 때 한 번 이관한다: 참가자마다 최신 manifest를 읽어 `survey-v1-to-v2.json`으로 답을 옮기고(대응 없는 옛 답은 manifest의 `migration_note`에 남기고 버림), `note = route_note(+촬영 방식)`, 영상은 그대로, 새 revision으로 저장한다. `changes` 표는 actor가 실제 계정이어야 해서 이관 기록은 manifest 안에 둔다. 옛 run의 `input_snapshot_json`은 건드리지 않는다.

## 2. PR-5 입력 계약 v2 전환과 55항목 분석 동결

### 2.1 백엔드

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/legacy/input_models_v1.py` | 신설 | 현행 `Session`·`StoredVideo`·`Checklist`·`Manifest`(intake-1.0)·`SURVEY_IDS`(q) 사본. 옛 run의 `input_snapshot_json` 읽기 전용 |
| `backend/app/input_models.py` | 변경 | `SURVEY_IDS`는 `app.domain.catalog`에서. `SurveyEdit{…, answers: dict[s], not_applicable: list[Key]}`(28개 정확히, NA 답은 null). `SessionEdit{expected_revision, session_id\|None, note}`. `SessionMetadata{expected_revision, note}`. `Session{session_id, note, survey_version, survey, survey_not_applicable, videos}`. `Manifest.schema_version="intake-2.0"`. `Checklist`·`capture_mode`·`route_note` 삭제 |
| `backend/app/storage.py` | 변경 | `SCHEMA` 그대로. `user_version 5` 이관 `migrate_manifests()`: 모든 cases(삭제 요청 포함)의 manifest가 intake-1.0이면 `legacy.input_models_v1.upgrade()`로 2.0 파일을 새로 쓰고 revision+1·참조 갱신(버린 답 목록은 `migration_note`). `manifest()`는 2.0만 검증 |
| `backend/app/intake.py` | 변경 | `new_session`(28·NA 빈 목록·note). `save_survey`(NA 검증은 `domain.validation.validate_survey_answers`). `headers("survey") = event_id, participant_id, survey_version, s01..s28`; s07~s09 칸의 `NA`/`해당없음` 문자열은 「해당 없음」. 옛 30문항 가로 양식(`mapping.horizontal`) 삭제 — 원본 양식이 바뀌었음 |
| `backend/app/api.py` | 변경 | `/api/catalog/survey` → v2 `SurveyCatalog`. 세션 편집은 `note`. `/imports/columns`의 `horizontal` 삭제. **동결**: `POST /cases/{id}/analysis`, `POST …/analysis/{run}/retry`, `POST /exports`, `POST /exports/preview`, `POST …/reports/{run}/generate` → 409 「55항목 판 분석은 종료되었습니다. 42항목 채점·리포트·내보내기는 다음 판에서 제공합니다.」 GET 조회·cancel·기존 내보내기 파일 다운로드는 유지 |
| `backend/app/analysis.py` | 변경 | `session_snapshot`이 `legacy.input_models_v1.Manifest`로 옛 run 스냅샷을 읽음. `enqueue` 첫 줄에서 409 |
| `backend/app/developer_sample.py` | 변경 | `Session` import를 legacy v1로(합성 샘플 시험은 유지) |
| `backend/app/legacy/__init__.py` | 변경 | 동결 상태와 `input_models_v1` 설명 |

### 2.2 시험

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/tests/support.py` | 신설 | `AppCase`(임시 폴더·역할별 계정·`client_for`·`make_case`·`upload`·`answers`) — 옛 `ObservationTests.setUp`에서 worker·fixture 의존을 뺀 것 |
| `backend/tests/test_intake_api.py` | 재작성 | 28문항 저장·NA 결측·NA 허용 문항 외 거절·bool/0/6 거절·멱등 저장; 영상 여러 개 등록; 세션 note; 재촬영 세션·revision 격리; 인증·CSRF·삭제 요청·업로드 재확인·손상 파일(기존 사례 유지); **intake-1.0 → 2.0 이관**(q→s 대응·버린 답 감사·옛 run 스냅샷 보존·재기동 멱등); 동결 엔드포인트 409; CSV/XLSX 가져오기 28문항·NA |
| `backend/tests/test_settings.py` | 축소 | 인프라 시험만 유지(개발자 라우트 권한·설정 스키마 거절·샘플링 옵션·키 회전/폐기/백업 비포함·백업 손상·오프라인 정리·동시 회전·복원 실패·응답 비식별). `start()`·worker에 묶인 5개 삭제, 4개는 파이프라인 부분만 잘라 유지. setUp은 `support` |
| `backend/tests/test_packaging.py` | 변경 | `UsageTests`는 파이프라인 대신 DB에 run·steps 행을 직접 넣어 사용량 집계를 시험 |
| `backend/tests/browser_server.py` | 변경 | worker 스레드·fixture 제거 |
| 삭제 | — | `test_observation.py`·`test_evaluation.py`·`test_reporting.py`·`test_video_evaluation.py`·`test_ledger.py`·`test_workspace.py`·`pilot_scenario.py`·`report_preview.py`·`evaluation_fixtures.py`·`report_fixtures.py`·`video_fixtures.py` (모두 55항목 파이프라인을 시작해야 함). `fixtures/contract-case.json`은 `test_legacy_contracts`가 쓰므로 유지 |

### 2.3 프론트(최소 — 화면이 깨지지 않게)

| 파일 | 내용 |
| --- | --- |
| `frontend/src/types.ts` | `Catalog` v2(`response_scale`, items `{item_id, number, text, domain, allows_not_applicable}`), `Session.note`·`survey_not_applicable` |
| `frontend/src/SurveyView.tsx` | `SurveyEditor` 삭제 → 읽기 전용 현황(영역 A~E, 값·해당 없음·미응답, `n/28`). 설문 입력은 자료 가져오기 CSV·Excel |
| `frontend/src/VideoUpload.tsx` | 카메라 ID 입력 제거, 파일 여러 개 대기열만 |
| `frontend/src/MetadataEditors.tsx` | `SessionEditor`: 체크리스트·촬영 방식 제거, `note`만 |
| `frontend/src/main.tsx` | 목록 `n/28`(응답+해당 없음), 자료 상태 필터, 세션 요약 문구 |
| `frontend/src/Importer.tsx` | 설문 28 열, 가로 양식 옵션 삭제 |
| `frontend/tests/intake.spec.ts` | 영상은 파일만 등록, 설문은 CSV 가져오기(NA 포함)로 등록해 28/28·「해당 없음」 표시 확인, 「three views」 분석 시험 삭제 |
| 삭제 | `frontend/tests/reporting.spec.ts`·`workspace.spec.ts`(모두 분석 시작 필요) |

완료 기준: 백엔드 시험 전부 통과, `npm run build`·`test:e2e`(intake·notifications·settings) 통과, 시험 릴리즈 자료 폴더를 흉내 낸 intake-1.0 fixture가 이관되어 화면에 28문항으로 보임.

## 3. PR-6 접수 메뉴

목적: 01 §1 ① 「참가자·반려견 정보 등록, 동의 확인, 순번 부여」. 04 설문지 머리 칸(번호·이름·견종·성별·나이·크기·함께 산 기간·입양 경로·보호자명·동의)을 프로그램이 받는다. **연락처는 받지 않는다**(01 §7 「보호자 이름·연락처는 어떤 파일에도 넣지 않는다」 — 이름은 리포트 제목에 필요하므로 저장하되 내보내기(P2 N10)에서 제외).

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/storage.py` | 변경 | `cases`에 `sequence_no INTEGER`, `consent_confirmed INTEGER NOT NULL DEFAULT 0`, `guardian_name TEXT NOT NULL DEFAULT ''`, `dog_profile_json TEXT NOT NULL DEFAULT '{}'` 추가(`user_version 6`, ALTER ADD COLUMN). `UNIQUE(event_id, sequence_no)`는 NULL 허용 인덱스로 |
| `backend/app/input_models.py` | 변경 | `DogProfile{breed, sex: 암\|수\|중성화\|미기재, age_years: int\|None, size: 소형\|중형\|대형\|미기재, years_together: str, adoption_route: 분양\|입양\|기타\|미기재}`. `CaseCreate/CaseEdit`에 `sequence_no: int\|None`, `consent_confirmed: bool`, `guardian_name`, `dog: DogProfile`. `CaseView`에 같은 필드 |
| `backend/app/intake.py` | 변경 | `create_case` 저장, 참가자 CSV/XLSX 템플릿·미리보기 열 확장. 식별 3열(event_id·participant_id·dog_name) 외 접수 열은 모두 생략 가능(빈칸=미기재) |
| `backend/app/api.py` | 변경 | `add_case`/`edit_case` 필드 저장, `case.identity` 감사에 포함 |
| `frontend/src/App.tsx` | 신설 | `main.tsx`의 셸(로그인·헤더·주 메뉴·알림)을 분리. 주 메뉴는 이 PR에서 접수 · 자료 가져오기 · 직원 계정이며 설문(PR-7)·촬영(PR-8)이 추가된다. 참가자 선택 상태를 셸이 보관 |
| `frontend/src/pages/Intake.tsx` | 신설 | 참가자 목록(순번·참가자 ID·반려견/보호자·동의·설문 n/28·영상 수; 구간 확정 여부는 PR-8에서)·등록 폼(`ParticipantFields.tsx` 공용)·상세 열기. 목록의 일괄 내보내기 패널·선택 체크박스는 동결 상태라 없앰 |
| `frontend/src/pages/CaseDetail.tsx` | 신설 | 옛 `Detail`을 그대로 옮기고 접수 정보(순번·보호자·반려견 정보·동의)를 머리에 표시. 영상 등록·촬영 메모·설문 현황·이전 분석(`Observations`)이 아직 여기 있으며 PR-7·PR-8이 각 메뉴로 빼고 PR-10이 분석 부분을 지운다(계획의 `LegacyDetail` 분리는 하지 않음 — 영상·설문 현황이 아직 이 화면에 있어 「legacy」라 부를 수 없음) |
| `frontend/src/main.tsx` | 변경 | `createRoot(...).render(<App />)`만 |
| `frontend/tests/intake.spec.ts` | 변경 | 등록 폼 새 칸, 순번 중복 거절, 동의 미확인 표시 |
| `backend/tests/test_intake_api.py` | 변경 | 새 필드 저장·정정·순번 중복 409·CSV 가져오기 |

## 4. PR-7 설문 메뉴

목적: 01 §1 ② 「28문항 입력 → 자동 채점」. 2026-09-16 결정: 설문은 사람이 CSV·Excel로 가져오기만 한다(태블릿 직접 응답·문항별 화면 입력은 만들지 않음).

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/api.py` | 변경 | `GET /cases/{id}/survey/result` → `app.scoring.survey_scores`(P0) 결과(`SurveyResult`). 저장 시 계산하지 않고 조회 시 계산(설문은 결정적) |
| `frontend/src/pages/Survey.tsx` | 신설 | 설문 메뉴 = CSV·Excel 가져오기(`Importer`를 설문 종류로 고정해 포함; 「자료 가져오기」에서도 여전히 가능) + 참가자별 등록 현황(n/28·미응답 수·해당 없음 수) + 영역별 응답 수와 분리 유형 이름 조회(화면에는 숫자 점수·총점 없음, 01 §6; API `GET /cases/{id}/survey/result`는 계약 그대로 평균값도 담음) |
| `frontend/tests/survey.spec.ts` | 신설 | CSV 가져오기(NA 포함)·오류 행·현황 표시·결과 조회·768px·검토자 읽기 전용 (XLSX 경로는 백엔드 시험이 담당) |
| `backend/tests/test_intake_api.py` | 변경 | `/survey/result` 계약·부분 응답·NA |

## 5. PR-8 촬영 메뉴

목적: 01 §1 ③ 「영상 파일을 쌍에 연결, 구간 시각 기록」, 01 §2 「각 쌍마다 8구간의 시작·끝 시각을 저장 … 채점 화면에서 그 구간으로 바로 이동」, 변경검토 §5 「확정 전에는 채점을 시작하지 않는다」. 카메라 역할 연결은 두지 않는다(2026-09-16 결정): 한 쌍에 영상 파일을 여러 개 등록하고, 파일마다 원본 이름과 자유 표시 이름만 둔다.

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `backend/app/input_models.py` | 변경 | `Session.segments: SegmentTimes \| None`; `SegmentTimes{video_id, confirmed, windows: 8개 {segment, start_sec, end_sec}}` — 구조 검증은 `domain.contracts.SessionSegments`로 위임(초안은 `operator_draft`, 확정은 `operator_confirmed`). `SegmentsEdit{expected_revision, video_id, windows, confirm: bool}`(세션은 경로에서) |
| `backend/app/api.py` | 변경 | `PUT /cases/{id}/sessions/{sid}/segments`; `confirm=true`면 `source`를 전부 `operator_confirmed`로. 기준 영상(`video_id`)은 운영자가 등록된 파일 중에서 고른다 |
| `frontend/src/pages/Recording.tsx` | 신설 | 참가자 선택 → 영상 파일 여러 개 등록(파일별 진행, 카메라 구분 입력 없음) → 기준 영상 선택 → 8구간 시각 입력(m:ss, 재생기 위치로 「지금 시각」 버튼) → 초안 저장 / 확정(입력 잠금, 「확정 해제 후 수정」으로 새 revision). 촬영 메모·재촬영 세션 추가도 이 메뉴로 옮김. 구간 경계는 마이크 음성으로 잡으므로(01 §2) 영상 재생기에 오디오 유지 |
| `frontend/src/VideoUpload.tsx` | 변경 | PR-5에서 카메라 입력을 이미 제거했으므로 그대로 `Recording`에 포함 |
| `frontend/tests/recording.spec.ts` | 신설 | 파일 세 개 등록·부분 실패 재시도, 8구간 입력·순서 오류 거절·확정 잠금 |
| `backend/tests/test_intake_api.py` | 변경 | segments 저장·겹침 거절·확정 후 수정은 새 revision |

영상 길이 대조(`validate_segments(…, duration_sec)`)는 ffprobe가 필요하므로 PR-9에서 전처리 단계가 확인한다.

## 6. PR-9 ~ PR-11 (PR 단위)

| PR | 내용 | 파일(예정) | 의존 |
| --- | --- | --- | --- |
| PR-9 전처리 | `media.probe`·`media.cut_clip`(구간 절단·fps·오디오 유지·선택적 다운스케일·v360 equirectangular 크롭)과 `app/preprocess.py`(확정 구간으로 기준 영상만 절단 — 다른 파일은 동기 오프셋이 없어 원본 유지; 자극 창 4곳 5초 8 fps, 나머지 2 fps; `clips/<case>/<session>/<batch>/` 불변 파일 + `clips.json` 해시; `preprocess.complete` 감사로 백업·정리 참조), `manage.py preprocess` CLI. worker 단계 편입은 P2 채점 파이프라인에서. 규칙은 `resources/rules/preprocess-v1.json` | `media.py`, `preprocess.py`, `manage.py`, `maintenance.MANAGED`, `tests/test_preprocess.py`(ffmpeg 합성 45초 영상) | PR-8, 07 문서 |
| PR-10 옛 화면 제거 | `Observations`·`Scores`·`Reports`·`VideoAssessments`·`EvidencePlayer`·`Exports`·`EvaluationSettings` 삭제, `CaseDetail`은 접수 정보·세션 요약·자료 관리만, 접수 목록의 분석 상태 열 삭제, `DeveloperSettings`는 공급자 키 관리만(프롬프트·파이프라인 버전 편집기는 55항목 단계용이라 제거 — 백엔드 `settings` 라우트·시험은 P2 재사용을 위해 유지), API에서 분석·리포트·내보내기·평가/설명 설정 라우트 삭제와 `analysis.enqueue/control`·`FROZEN` 삭제(`view_analysis`는 `reporting`이 import하여 P2까지 유지), 삭제된 라우트만 쓰던 요청 모델(`AnalysisRequest`·`ReviewEdit`·`FrameEdit`·`ReportSettingsEdit/View`·`ExportRequest`·`SettingsEdit`) 삭제, 옛 화면 전용 CSS 정리, e2e settings.spec은 키 관리만 | frontend 7개 파일 삭제 + 6개 수정, `api.py`, `analysis.py`, `*_models.py` | PR-6~8 |
| PR-11 패키징·리허설 | `launcher.REQUIRED`(behavior-v2·survey-v2·survey-v1-to-v2·scoring-v2·preprocess-v1·폰트·화면 빌드; v1 카탈로그는 패키지에 남되 시작 요건에서 제외), `build_release`(추적 파일만), `scripts/rehearsal.py`(합성 영상 72쌍: 참가자 CSV 가져오기→설문 CSV 가져오기(매 3쌍 7~9 NA)→파일 2개 등록→8구간 확정→전처리, 단계별 시간·용량·클립 해시 JSON; 임시 폴더만 사용) + `tests/test_rehearsal.py`(2쌍), `README`·`PILOT_OPERATIONS`(촬영 당일 절차 5단계·전처리 명령·이관 안내)·`DEVELOPMENT`(패키징·리허설 절) 갱신, 버전 0.2.0, v0.2.0 시험 릴리즈 | `launcher.py`, `scripts/`, `tests/test_packaging.py`, docs, `pyproject.toml`·`package.json` | PR-9·10 |

## 7. 완료 기준 요약

- PR-5: 28문항·note로 저장·조회, intake-1.0 자료 이관, 옛 분석 시작 409, 백엔드·e2e 시험 통과.
- PR-6: 접수 메뉴에서 순번·동의·보호자명·반려견 정보 등록·정정, 목록에 진행 상태.
- PR-7: 설문 메뉴에서 28문항 입력·「해당 없음」·영역 응답 수·분리 유형 확인(숫자 점수 없음).
- PR-8: 촬영 메뉴에서 영상 파일 여러 개 등록·8구간 시각 입력·확정 잠금.
- PR-9~11: 합성 영상 72쌍 리허설 통과, 설치 패키지 갱신 — 변경검토 6장 P1 완료 기준.
