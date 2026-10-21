# PR-CM03 누적 집계와 출력 고정

버전: v1.0 · 2026-10-21 · 상태: **구현·검증·cold review 반영 완료** (2026-10-21) · 직접 선행: CM01·CM02

상위: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md). 요구 CM-R01~R10·R12·R13. 선행: [CM01](K-DOG_PR-CM01_확정문항매핑과기준자료_v1.0_20261021.md)·[CM02](K-DOG_PR-CM02_참여쌍과대표설문_v1.0_20261021.md). 브랜치 제안: `veluga/cm03-cumulative-comparison-snapshots` · PR 제목: `feat: pin cumulative survey comparisons in outputs`

## 1 문제와 완료 결과

현재 수동 집단·외부 비교는 별도 선택 pointer이며 전 회차 누적 선정·대표 정정·지표별 외부 미준비를 표현하지 않는다. 새 발급 접수에서 전체 비교값을 한 번 고정하고 Worker·HTML/PDF·연구 export가 같은 자료를 사용하게 한다.

완료 결과는 **9개 지표의 정확한 누적값과 SF/NF의 유효 외부값이 새 출력 snapshot에 고정되는 것**이다. 계산·선정은 서버가 소유하고 프런트/렌더러가 다시 집계하지 않는다. 이 PR의 서비스/DTO를 CM04가 기본 화면에 연결한다.

## 2 파일별 변경 계획

| 파일 | 변경·재사용 범위 |
| --- | --- |
| CM02 신규 `cumulative_comparisons_v4.py` 및 domain 타입 | 대표 집합 읽기·9지표 집계·누적 snapshot/public aggregate·지표별 상태 |
| [survey_v4.py](../../../backend/app/survey_v4.py#L103), [comparisons_v4.py](../../../backend/app/comparisons_v4.py#L191) | 기존 원응답/역채점/완전응답과 영역 집계 재사용. 옛 `aggregate` 결과·계약은 무관하게 변경하지 않음 |
| [external_comparisons_v4.py](../../../backend/app/external_comparisons_v4.py#L82) | 새 builder가 출처별 준비를 판단하고 유효 source만 기존 snapshot 생성에 전달 |
| [domain/report_runs_v4.py](../../../backend/app/domain/report_runs_v4.py), [domain/report_profile_v4.py](../../../backend/app/domain/report_profile_v4.py) | 신규 실행/표현 판본과 optional 누적 pointer/public 자료, 옛 직렬화 보존 |
| [report_runs_v4.py](../../../backend/app/report_runs_v4.py#L340) | enqueue 고정·멱등·config hash·Worker/발급 검증·파일 참조 |
| [exports_v4.py](../../../backend/app/exports_v4.py), [domain/exports_v4.py](../../../backend/app/domain/exports_v4.py) | 선택한 보고서의 동일 누적 snapshot·표시값을 CSV/XLSX 공통 테이블로 전달 |
| [maintenance.py](../../../backend/app/maintenance.py#L71) | 누적 snapshot→pair state/submission/input/외부 근거 참조 순회 |
| 신규 예정 `backend/tests/test_cumulative_comparisons_v4.py`, `test_cumulative_outputs_v4.py` | 원평균·n·상태·접수 고정·재시도·export·과거 보존 |

## 3 후보 선정과 집계 interface

CM02 resolver가 읽은 **고정 대표 설문 한 건**을 기존 `survey_scores_v4`로 산출한다. 전 회차를 대상으로 하며 현재 보고서 pair도 같은 조건이면 포함한다. case당 한 회차 규칙을 pair당 대표 한 건으로 확장하되 기존 수동 집단의 `one_case_one_explicit_session` 계약은 유지한다.

- pair 미확정/명시 제외, 대표 부재, 문항·척도·방향 미확인은 제외 이유다. 옛 consent/deletion/owner metadata는 선정 조건이 아니다.
- 매핑이 확인한 signature/정책을 만족한 지표만 포함한다. 대표 설문 하나를 지표별로 평가하고, 서로 다른 방문의 유효 부분을 합치지 않는다. 구판의 다른 지표까지 일괄 동일하다고 간주하지 않는다.
- 개별 보고서 설문은 선택 최종 결과의 고정 원입력이다. 누적 대표와 다를 수 있다. 대표 A=1, 재방문 A=5, 대표 B=3이면 새 재방문 보고서 개별 A=5이고 누적은2·n2다.
- 후보는 registry 최신 head 집합을 먼저 고정하고 계산한다. 채택 transaction에서 후보 집합·각 pointer·매핑/정의 hash를 다시 검사한다. 새 pair/정정/제외가 끼어들면409로 다시 요청하게 하며 부분 구버전 집합을 채택하지 않는다. 신원 오류/원입력 손상은 제외로 숨기지 않는 기술 오류다.

예정 서비스 interface는 `build_cumulative_snapshot(store, target, actor, request_id, expected...)`와 `for_output(store, reference, actor)` 정도로 제한한다. 앞 함수는 새 접수의 고정 생성, 뒤 함수는 고정 부모 검증과 public 자료 반환을 맡는다. 실제 이름은 CM04 착수 전에 확정 인계한다.

### 3.1 원평균과 반올림

각 지표는 완전응답 구성 문항 수가 고정되어 있다. 변환된 정수 응답의 개인 numerator/denominator를 재사용해 누적의 정확한 정수 분자·분모를 보존한다. 예를 들어 NF는 `모든 대표의 변환 응답 합 / (3×유효 pair 수)`다. 개인 평균을 둘째 자리로 먼저 반올림한 뒤 평균내지 않는다.

새 비교 영역은 표준 라이브러리 Decimal 또는 동등한 정확 계산으로 Excel ROUND의 양수 절반 올림을 적용한다. NF 누적9/8은 원값1.125·표시1.13이어야 한다. 이진 float에 `round`/`toFixed`를 각각 적용하여 채널별 결과가 갈리지 않게 한다. 기존 전역 `number()`의 동작을 바꾸지 않고 원값·표시 문자열·표시값 차이를 새 비교 자료에 함께 고정한다.

## 4 지표별 상태와 외부 연결

상태는 독립 축으로 표현한다. 한 전역 boolean으로 설문·누적·외부의 준비 상태를 합치지 않는다.

| 축 | 상태·동작 |
| --- | --- |
| 개별 | 유효 / 응답부족 / 입력확인 / 판본확인. 개별 무효면 해당 패널 안내·비교문장 없음 |
| 누적 | 평균 null·n0 / 계산됨·n1·표식생략 / 표시가능·n≥2. 미확정·제외 사유/건수 별도 |
| 외부 | 미대응(7지표) / 기준미준비·중단·범위불일치 / 사용가능(SF/NF). 미대응은 오류 아님 |

현재 `_entries`는 선택한 두 source 중 하나라도 응답부족이면 전체409다. 새 builder는 각 source의 실제 정의·scope·개별 완전응답을 먼저 판정하고 **사용 가능한 source ID만** 기존 외부 snapshot 생성에 넘긴다. 양쪽 모두 불가이면 external pointer 없이 사유만 누적 snapshot에 보존한다. 기존 명시 외부 API의 실패 계약을 전역 완화하거나 null 평균을 가짜 ExternalEntry로 넣지 않는다.

정의 없음/명시 중단/설문 부족과 파일 손상·hash 불일치를 구별한다. 정상적인 미준비는 해당 외부점만 생략한다. 등록 근거 또는 고정 정의가 손상되면 정상 미준비처럼 조용히 제공하지 않는다. 사전 판정과 snapshot 저장 사이 기준이 바뀌면 충돌로 재접수하며 숫자를 자동 교체하지 않는다.

누적 비교 문장은 개인·누적 표시값끼리, 미국 비교 문장은 개인 표시값·참고 평균끼리 판단한다. 미국 비교 고정 문장은 전달표 TXT-H/L/E를 사용한다. 7개 비두려움 지표의 누적 비교는 같은 숫자 비교만 하고 좋은/나쁜 성격 평가를 만들지 않는다.

## 5 snapshot·접수·과거 판본

신규 누적 artifact에는 cutoff/집계 판본·매핑 hash·9개 지표·원값/표시값·유효n·선정/제외 이유·pair state/submission/input pointers·외부 정의/근거 pointers를 보존한다. 공개 자료에는 평균/n/범위/사유·공개 출처만 전달하고 pair별 원응답·신원은 렌더러에 넘기지 않는다.

1. 신규 리포트 실행/표현 판본을 추가한다. 제안은 `report-run-20261021-cm` / `report-presentation-20261021-cm`이다. 기존 rp04 literal·자산·hash는 보존하고 버전 dispatch로 검증/렌더 입력을 선택한다.
2. enqueue에서 최종 결과 원입력과 개인 target을 맞춘 뒤 누적·외부를 고정한다. 동일 request ID의 기존 접수가 있으면 누적 최신 여부와 무관하게 같은 접수를 반환한다.
3. config/input/profile/prepared/publication의 연결에 동일 pointer/hash를 포함한다. 새 optional 필드가 없는 옛 문서는 직렬화에서 해당 필드를 생략해 기존 hash를 지킨다.
4. Worker/재시도/다운로드는 고정 부모의 무결성을 검사하며 현재 원장에서 후보를 다시 고르지 않는다. 최신 원장 변경은 기존 snapshot의 값을 바꾸지 않는다. 실제 기준 사용중단·현재 actor 검사 등 기존 새 발급 보호는 유지하되 자동 새 집계/묵시적 재접수는 하지 않는다.
5. 구판 S1 발급·대기 실행은 자기 config/자산 판본을 사용한다. 옛 점수 실행 복원이나 구판→신판 점수 변환은 추가하지 않는다.

## 6 연구 export와 참조 폐쇄

보고서가 선택된 export는 그 보고서의 누적 snapshot을 그대로 받는다. export 생성 시 ‘현재 누적’으로 바꾸지 않는다. 신규 export에서 현재 비교를 원하면 먼저 같은 서비스로 명시 snapshot을 생성·선택하고 그 pointer를 보낸다.

- CSV/XLSX 공통 `tables`에 metric ID·문항·source 종류(individual/cumulative/external)·원값/표시값·n의 의미·cutoff·매핑/집계/정의 판본을 연결한다. 기존 CSV 열/행은 무관하게 재정렬하지 않고 새 표/필드를 판본과 함께 추가한다.
- 서로 다른 원자료의 복수 보고서는 각 보고서 pointer별 cutoff/값을 유지한다. 동일 원자료에서 cutoff만 달라진 보고서들은 각각 별도 export로 보존한다. 기존 원자료 중복 선택 금지는 유지하고, 같은 원자료의 복수 보고서를 한 파일에 담는 새 계약은 추가하지 않는다. 별도 수동 집단 선택과 보고서 누적도 서로 덮어쓰지 않는다.
- 공개 보고서/export 비교표에는 pair 식별값·이름·전체 구성원 원응답을 넣지 않는다. 기존 원자료 연구 export의 가명화·선택된 자료 범위는 유지한다.
- typed 참조 수집은 누적 snapshot의 모든 부모/근거를 포함하고 백업/restore/clean으로 보존한다. 원장 최신 head만 남기고 과거 snapshot의 부모를 삭제하지 않는다.

## 7 검증·완료·인계

| 공통 시험 | 본 PR의 기대 |
| --- | --- |
| CM-T04~T12 | 가상 A/B/C·추가·정정·결측, 실제 n, 가중평균, n0/1/2, 정확 원값/반올림 |
| CM-T13·T15 | 표시값 판정, SF/NF 독립·둘다미준비·7개 외부미대응 |
| CM-T16~T22 | 원자적 후보 채택·멱등·재시도·손상·actor·동일 export·참조 폐쇄·구판 보존 |

```powershell
# backend/ — 신규 시험은 본 PR에서 작성
uv run --locked python -X utf8 -m unittest tests.test_cumulative_comparisons_v4 tests.test_cumulative_outputs_v4 tests.test_comparisons_v4 tests.test_external_comparisons_v4 tests.test_external_exports_v4 tests.test_exports_v4 tests.test_report_runs_v4 -v
# 저장소 루트
git diff --check
graft check
```

시험은 실제 enqueue/Worker retry/CSV ZIP/XLSX 경로를 사용하고 AI 응답은 기존 fake provider로 고정한다. 실제 AI 호출은 필요하지 않다. 원시 응답이 만들 수 없는 equal_display 사례는 표시 helper 단위로 검사한다.

- [x] 9지표 집계·상태·정확 원값·표시값·API와 export 완료
- [x] 신규 판본의 config/input/profile/publication pin 연결, 옛 bytes/대기 실행 보존
- [x] 후보 변경 충돌·지표별 외부 연결·참조 폐쇄·독립 검토/수용 재검증
- [x] CM04에 확정 DTO/상태·표시문자열·렌더/프런트 연결점 인계

실패 시 신규 발급 접수만 중지하고 snapshot/기존 발급을 보존한다. 새 누적 참조가 운영에 저장된 뒤에는 해당 형식을 모르는 옛 앱으로 운영 DB를 되돌리지 않는다. 수정판은 원본을 보존한 채 새 접수를 만든다.

| 실행 기록 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | 브랜치 `veluga/cm03-cumulative-comparison-snapshots`(CM02 위 누적). commit·PR은 [실행 기록](K-DOG_문항매핑과누적비교구현실행기록_v1.0_20261021.md) |
| 공식 버전 확인일·최신/선택·이유·링크 | 2026-10-21 CM01 기록과 동일. 반올림은 표준 라이브러리 `decimal`(ROUND_HALF_UP)만 사용, 새 의존성 없음 |
| 명령·시험 수·시간·결과 | 신규 `test_cumulative_outputs_v4` 13건 OK. 초기 회귀 149건 중 28건 오류(시험 seam의 config 위치 인자)→수정 후 4건 실패(rp04 표현 판본 분기)→수정. 최종 회귀 153건 OK(352초, 로컬 원본 셀 대조 1건 skip) |
| cold review·판정·수용 수정 | 독립 검토 4건 모두 수용: 발급본은 자기 판본으로 열기(현재 매핑 변경이 옛 발급을 막지 않음, 새 실행만 재계산), 접수 트랜잭션에서 외부 기준 정의 재확인(변경 시 409), 기준 손상은 미준비가 아닌 기술 오류, 집계 기준일은 한국시간. 별도로 회귀에서 발견한 config 호출 형태·표현 판본 분기 회귀 2건을 수정. 수정 후 재검증 통과 |
| 실제 실행/표현/DTO 판본·CM04 인계 | 실행 `report-run-20261021-cm`, 표현 `report-presentation-20261021-cm`, 집계 `cumulative-comparison-20261021-cm-1`. 접수 요청 `cumulative: true`(생략 시 기존 rp04 계약·hash 유지). profile `survey_comparison`(`CumulativePublicV4`, 행 `ComparisonRowV4`: 개별/누적/외부 원값·표시 문자열·n·상태·TXT 문장), config `cumulative_comparison`, changes `comparison.cumulative.snapshot`, artifact `comparison-cumulative`. 외부는 등록 기준을 지표별로 판정해 사용 가능한 출처만 기존 외부 snapshot으로 고정. 연구 export `comparisons` 표에 `report_individual/report_cumulative/report_external` 행 |
