# PR-S14 검수자료와연구내보내기

버전: v1.0 · 2026-10-03 · 상태: 구현·자동 검증·독립 cold review 완료, 실측·원본 승인 후속 분리 · 선행: S06·S08·S09·S12·S13 · 기준: main 3654596

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 공통 검증·리뷰·버전 확인·저장 보호는 상위 §7을 적용한다.

브랜치 제안: `veluga/s14-research-exports` · 권장 PR 제목: `feat: 검수 출처와 연구 원자료 내보내기`

## 문제와 결과

전달된 세 행동 비교표는 독립 사람 정답이 아니라 수정·AI 잠정값이 누적된 참고 자료다. 출처·확정 상태를 갖춘 검수 import와 원자료/기본 결과/행사 출력이 분리된 연구 export를 제공한다.

근거: 통합명세 1~2절·G03·T30, 기존 C12. 인수: T01·T02·T15·T20·T27·T30.

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `backend/app/validation_data_v4.py`, `backend/app/domain/validation_data_v4.py` | 신설 | 파일·평가자·확정/재확인/AI 잠정·판본 분류와 연결 |
| `backend/app/exports_v4.py`, `backend/app/domain/exports_v4.py` | 신설 | 명시 snapshot의 CSV/XLSX 원자료·계산·판정·출력 |
| `backend/app/s1_workbook.py` | 신설 | 점수 있는 비교 파일의 참고용 프로필, 빈양식 승인과 분리 |
| `backend/app/api.py`, `backend/app/maintenance.py` | 수정 | 권한·자료 등록·파일 참조·다운로드·삭제 및 복원 |
| `frontend/src/ValidationData.tsx`, `frontend/src/ResearchExportsV4.tsx`, `frontend/src/researchTypesV4.ts` | 신설 | 대응표·유효성 검토·출처별 상태·명시 원자료와 내보내기 선택 |
| `frontend/src/App.tsx`, `frontend/src/pages/Scoring.tsx` | 수정 | 검수자료 메뉴·연구 export 연결 |
| `backend/tests/test_validation_data_v4.py`, `backend/tests/test_exports_v4.py`, `backend/tests/test_research_api_v4.py`, `backend/tests/test_deletion_restore_v4.py`, `frontend/tests/exports-v4.spec.ts` | 신설 | 독립성·분모·출처·값 보존·접근 제어·삭제 후 복원 차단 |

## 구현 순서와 자료 계약

1. 검수 원본 hash·파일/시트/셀·원값·수식 캐시·평가자 정보·판본·확정 여부·AI 노출을 보존한다. 보호자 이름으로 평가자를 채우거나 캐시 일치율을 앱 실측으로 표시하지 않는다.
2. ‘에디/예디’ 표기, 네 설문·네 영상 사례·세 채점 사례를 명시한 대상/회차 대응표로 연결한다. 이름만으로 자동 확정하지 않는다. 참여 중단 사례는 동의 상태를 확인하고 사람 정답 분모에서 제외한다.
3. 고객 검수 파일의 개8·10·12·30·34 재채점 필요, 루키 물건/걷기 재확인, AI 잠정값·예시 메모·구판 값·미관찰을 출처 상태로 구별한다. 이 참고 분류는 제거한 앱 점수의 복원·현재 시트 복사가 아니다. S1 앱 점수는 전부 새로 채점하며 실제 비교는 같은 기준·창·대상의 양쪽 유효 관찰에 한정한다.
4. 연구 원자료는 새 S1 결과를 대상×회차×평가자×항목/창의 긴 표로 낸다. 직접 숫자83, 자동4, 메모3, 개59별도를 구별하고 null과0을 보존한다. 제거한 구판 앱 점수·폐기 항목을 연구 산출물에 싣지 않는다. 고객 검수 원본과의 대조는 별도 출처/참고 상태로 구분한다.
5. 별도 표에 자동 계산, AI 최초/독립 사람 판정, AI 노출 후 검수, 완료 의견, 최종 결과·리포트, 설문 원응답/역채점/집계, 비교 출처를 둔다. 행사 수정 결과를 AI 최초 출력에 덮지 않는다.
6. 독립 비교 대상표에는 부적합 쌍을 제외하고 사유를 남긴다. 미확인 점수를 제외한 분모·유효 항목 수·결측률을 제공하되 범주/횟수/유형을 하나의 정확도로 합치지 않는다.
7. 내보내기 요청은 평가자/회차/판본/시트 revision/hash를 고정한다. 직접 식별정보와 키는 연구 파일에 넣지 않고 필요한 대응표 접근은 기존 권한·동의 범위로 제한한다. CSV 수식 주입은 막되 음수 숫자는 보존한다.
8. 생성·채택·다운로드 직전 권한·미공개 시트·삭제·hash를 확인한다. 새 저장물과 부모 참조의 백업/복원/삭제를 연결한다.

## 검증과 완료 조건

- 독립 사람·AI 최초·AI 노출 후 수정·행사 의견·잠정값이 서로 다른 출처로 남는다.
- 동일 카메라3개가 표본3개가 되지 않고, 같은 슬롯 다른 batch는 구별된다.
- S1 원값0/−2/횟수/null이 보존된다. 구판 개32=99·예시 메모는 현재 점수/연구 결과에서 제외되며 고객 검수 원본 hash는 바뀌지 않는다.
- 루키 재확인값·미확인 평가자·의미변경 구값은 사람 확정 정답 분모에 들어가지 않는다.
- 선택 당시 snapshot이 재현되고 이후 수정/삭제·다른 평가자 미공개 자료의 접근 제어를 지킨다.
- 합성 파일로 export 재읽기·열/값/분모를 대조한다. 실제 파일의 캐시 검사는 실제 Excel 재계산과 구별한다.

## 경계와 인계

S16이 이 자료 계약으로 실제 비교를 수행한다. 정식 연구의 표본수·통계모형·합격 정확도를 개발자가 발명하지 않는다. 입력 원본/G01의 승인과 누적 비교 파일의 참고 import는 서로 다른 상태로 관리한다.

## 구현 및 검증 기록

- [x] 구현·변경 파일 및 commit/PR 기록 — commit은 [구현 실행 기록](K-DOG_구현실행기록_v1.0_20261003.md)의 S14에 연결
- [x] 명세 기대값과 실제 시험 결과·미실행 사유 기록
- [x] 라이브러리/API 최신·선택 버전·확인일·근거 기록
- [x] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [x] 남은 D/G 확인, 활성/보류 기능, 다음 PR 인계 기록

### 2026-10-04 backend 구현과 출처 경계

- [validation_data_v4.py](../../backend/app/validation_data_v4.py), [domain/validation_data_v4.py](../../backend/app/domain/validation_data_v4.py), [s1_workbook.py](../../backend/app/s1_workbook.py): 별도의 검수 참고 등록 경로를 추가했다. 원본 XLSX의 bytes/hash·시트/셀·XML 원값·수식·저장 캐시를 보존하고 명시 대응표·평가자·판본·확정/AI 노출 상태를 기록한다. 수식을 실행하거나 고객 참고값으로 현재 S1 시트를 채우지 않는다. `SRC05~07`은 원본 hash로 분류하고 개8/10/12/30/34를 재확인 대상으로 둔다. 동명이인/별칭은 자동 대응하지 않는다.
- [exports_v4.py](../../backend/app/exports_v4.py), [domain/exports_v4.py](../../backend/app/domain/exports_v4.py): 정확한 대상·회차·시트 revision/ref/hash와 선택한 기본/최종/발급/자체집단/참고 원본을 고정하는 CSV ZIP·XLSX를 추가했다. 숫자83/자동4/메모3·개59, F 근거/G 검토, 실제 관찰량/발성 분모·걷기 예외, 자동/수동/유효 판정, 완료 의견·최종·발급, 설문 원값/역채점/집계, 독립 비교·항목별 유효 n·결측률을 별도 열과 표로 구분한다. 3카메라를3표본으로 늘리거나 구판99·누적 참고값을 정답 분모에 넣지 않는다.
- 관찰 원본은 현재 또는 보존 history에 실제 속하는 pin이어야 한다. 다른 평가자 원본은 현재 유효한 grant와 실제 명시 공개가 필요하고, 의견/최종본은 S09 해석 공개 계약도 검사한다. AI 공개 이전 사람 제출 원본은 보존하며 노출 후 review는 독립 분모에서 제외한다. 내보내기 생성·채택·다운로드에서 동의·삭제·현재 계정과 영상 계보·부모/산출물 hash를 다시 검사한다.
- 연구 파일의 대상/회차/평가자는 파일별 가명으로 낸다. 이름/참가자ID/행사·평가자 식별 열과 원파일 경로를 출력하지 않고, 자유문자열의 현재/과거 등록 이름·ID 및 선택 발급본 header 식별값과 명시 `redact_terms`를 비식별 처리한다. 등록되지 않은 제3자의 이름을 자동 판별하는 기능은 아니므로 실제 자유서술의 연구 제공 전 검토가 필요하다. 별도 연구 동의 정책을 발명하지 않았으며 현재 등록된 참가 동의와 분석·피드백 동의가 확인되지 않은 대상은 제외한다.
- `api.py`에 참고 preview/register/list/detail와 연구 create/list/detail/download를 연결했다. 새 DB 테이블은 만들지 않고 불변 JSON/bytes와 기존 변경 원장으로 requestID 멱등성을 유지한다. `maintenance.py`는 `validation-reference`의 source, `research-export`의 parent_files/output만 typed 참조로 따라가며, 삭제된 참고/비교집단/리포트를 포함한 export까지 정리한다.

### 자동 시험·cold review

backend에서 `uv run --locked python -X utf8 -m unittest tests.test_validation_data_v4 tests.test_exports_v4 tests.test_research_api_v4 tests.test_acceptance_v4 -v`를 실행하여 **27개 통과(31.435초)**했다. S14 검수9·연구11·실제 HTTP2와 T05/T08/T18/T21/T23의 추가 인수5개다. 모든 파일·영상·AI 출력은 합성이다. 독립 reviewer는 수정 전 core17개를 별도 실행하여 통과했고 아래 경계 결함을 재현했다.

| 발견 | 수용한 수정 | 회귀 |
| --- | --- | --- |
| P1: 등록 이름/ID를 수정한 뒤 옛 시트의 메모를 export하면 과거 이름이 남음 | 같은 case의 `case.identity` before/after 식별값과 선택한 report header도 고정 비식별 목록에 포함 | `test_historical_identity_in_free_text_is_redacted_after_name_and_id_change` |
| P1: 동일 전체 XLSX의 무대응 참고 복제가 대상 삭제 후 남음 | 등록 audit에 source_sha256 고정, 동일 원본의 모든 참고·의존 export 폐쇄, 최소 hash tombstone, preview/열람/재등록 차단, 이전 백업 복원 시 tombstone 전파 | `test_same_source_unbound_copy_and_old_backup_cannot_restore_deleted_cells` — 대응 기록이 생기기 전의 무대응 백업도 재노출하지 않음 |
| P2: 같은 시트/셀 주소를 중복한 XML의 마지막 값이 조용히 채택됨 | 중복 시트명/셀 주소를 참고 등록 전 거절 | `test_duplicate_cell_or_sheet_name_is_rejected_without_last_value_wins` |
| API 통합: 엄격 도메인의 tuple을 JSON list 응답에서 거절 | preview/full response의 도메인을 `model_validate_json`으로 명시 정규화 | `tests.test_research_api_v4` 2개 |
| 자체 점검: XLSX 긴 셀의 자동 잘림 | 셀32,767자·행 한계/지원하지 않는 제어문자는 명시422와 CSV ZIP 안내, 임의 축약 없음 | `test_xlsx_keeps_numeric_zero_negative_and_sanitizes_formula_text`에서 −2/0/수식 주입 방지 및 긴 셀 CSV 보존 |

새 blob 변조·원본/부모 변조·미공개 타인 시트·동의 철회·늦은 삭제·영상 receipt 취소·백업 복원/파일 폐쇄·원값0/−2/null·수식/캐시 분리도 포함했다. 이후 UI cold review P2를 수용해 집단 비교 적격 후보와 검수 대응 후보를 분리했다. 새 `validation_data_v4.candidates`는 동의 미확인/철회에도 참고 대응을 허용하되 실제 삭제 대상은 제외한다. `test_reference_candidates_include_declined_consent_but_never_deleted_cases` 1개를 별도 추가 통과(0.656초)했으며, 전달된 참여 중단 상태는 독립 정답 제외로 유지한다.

독립 reviewer는 위 수용 3건의 수정 코드를 재검토하고 검수9·연구11·참가자ID 변경 뒤 삭제/반복 복원1의 **21개를 별도 실행해 통과(36.258초)**했다. 해당 실행에는 이후 추가한 후보 시험은 포함하지 않았으며, 각 증거의 범위를 합산한 단일 실행으로 표시하지 않는다. 최종 cold review에서 S14 범위의 잔여 actionable finding은 없었다.

`frontend/tests/exports-v4.spec.ts`의 **실제 브라우저 3개가 통과(22.8초)**했다. 합성 XLSX 참고 등록·대응 후보·엄격한 출처 상태와 CSV/XLSX 내보내기, 실패 응답·입력 유지·권한 경계를 확인했다. `npm run build`(56 modules)가 통과했고, 360px 화면에 가로 넘침이 없음을 확인한 뒤 검수자료/연구 내보내기 화면 이미지2개를 시각 검토했다. 구현 파일·단계 commit 연결은 [구현 실행 기록](K-DOG_구현실행기록_v1.0_20261003.md)의 S14에 남긴다.

### 의존성과 미실행 범위

새 의존성을 설치하거나 잠금파일을 변경하지 않았다. 착수 시 공식 출처로 확인한 Pydantic 2.13.5·openpyxl 3.1.5와 Python 3.14의 선택/최신판·공식 출처는 2026-10-03 [공통 의존성 검증](K-DOG_구현실행기록_v1.0_20261003.md)을 재사용했다. XLSX 행/셀 한계는 [Microsoft Excel specifications and limits](https://support.microsoft.com/en-us/excel/excel-specifications-and-limits)(2026-10-04 추가 확인)를 따른다. CSV 수식 문자는 문자열만 escape하며 실제 음수 숫자는 바꾸지 않는다.

G01/G04 빈양식·수식/예시 정정 실물 인수는 여전히 대기이고, 이 참고 reader가 정식 점수 Excel import를 활성화하지 않는다. G03 고객 비교 사례의 실제 새 사람 관찰·평가자 확인·독립 정답 승인, 실제 영상/유료 공급자 정확도·시간·비용 실측은 수행하지 않았다. S16 준비 도구가 본 export의 고정 pin·최초 AI/독립 사람 분모를 소비하는 연결 시험과 실제 측정 완료를 구분한다. 구체 재개 입력은 [실측 및 확인 후속 대장](K-DOG_실측및확인후속대장_v1.0_20261003.md)에 남긴다.
