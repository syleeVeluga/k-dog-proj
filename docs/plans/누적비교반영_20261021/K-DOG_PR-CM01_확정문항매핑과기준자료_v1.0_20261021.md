# PR-CM01 확정 문항 매핑과 기준 자료

버전: v1.0 · 2026-10-21 · 상태: **구현 전** · 직접 선행: 없음

상위: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md). 요구 CM-R01·R02·R03·R11·R12·R14. 브랜치 제안: `veluga/cm01-comparison-mapping` · PR 제목: `feat: define confirmed survey comparison mappings`

## 1 문제와 완료 결과

전달표에는 28문항의 비교 가능 범위와 9개 출력 지표가 있지만 앱에는 이 전달 판본이 연결되지 않았다. 기존 미국 수치와 산식은 일치한다. 계산을 다시 만들지 않고 새 비교 기능이 사용할 검증 가능한 매핑·출처를 추가한다. 기존 수동 기준 정의 저장 기능을 실제 적용 경로로 재사용한다.

완료 결과는 **문항·지표·외부 출처의 정확한 대응을 코드가 읽을 수 있고, 실제 업무 계정이 전달 근거로 두 기준을 저장할 수 있는 것**이다. 운영 DB 자동 초기화·가짜 확인값·정의 자동 덮어쓰기는 하지 않는다.

## 2 파일별 변경 계획

| 파일 | 변경·조사 범위 |
| --- | --- |
| 신규 예정 `resources/report/survey-comparison-20261008.json` | 9지표 매핑, 원문항/산식/척도/방향/역채점/결측, 외부2출처, 전달 XLSX hash/위치·판본 주석 |
| 신규 예정 `backend/app/comparison_mapping_v4.py` | 작은 엄격 로더·매핑 검증. 고객 XLSX 실행·런타임 Excel 파싱은 없음 |
| [survey_v4.py](../../../backend/app/survey_v4.py#L103) | 기존 계산 interface 재사용, 원응답·RP01 정책 불변 확인 |
| [comparisons_v4.py](../../../backend/app/comparisons_v4.py#L370) | `save_definition`/근거/기대 revision 재사용. 새 매핑과의 대응 확인 interface만 추가 |
| [catalog_v4.py](../../../backend/app/domain/catalog_v4.py#L146) | 기존 SRC02/SRC03 출처 검증은 유지. 새 전달 근거를 원본 통합명세 출처로 위장하지 않음 |
| [ExternalComparisonSettingsV4.tsx](../../../frontend/src/ExternalComparisonSettingsV4.tsx) | 기존 두 출처의 실제 수치·근거 등록 경로 확인. 필요한 경우 매핑 판본/입력 안내만 추가 |
| 신규 예정 `backend/tests/test_comparison_mapping_v4.py` | committed 자산 계약 및 로컬 원본이 있을 때의 별도 셀/hash 대조 |
| [launcher.py](../../../backend/app/launcher.py), [test_packaging.py](../../../backend/tests/test_packaging.py) | 새 런타임 자산 필수 목록·포함, 원본 XLSX 미포함 확인 |

신규 파일명은 제안이며 실제 이름 변경 시 이 문서와 CM02~CM05 참조를 함께 갱신한다. 기존 `comparison-sources-v4.json`, 설문 카탈로그·정책·매핑 원본 bytes는 보존한다.

## 3 매핑 계약

1. 지표 키는 S01~S09, 문항 키는 s01~s28이다. 각 문항은 정확히 한 지표에 속한다. SF/NF는 S03/S04 별칭이다. 카탈로그 표시 이름의 S02/S06/S08 차이는 지표 이름을 문자열 매칭해 해결하지 않는다.
2. Q25는 현재 계산 결과의 `standalone`에서 가져온다. 다른 8개 `domains`만 순회하는 구현은 전수 검증에서 실패해야 한다.
3. 외부는 기존 source ID 두 개만 사용한다. SF `(s10,s11)`와 NF `(s12,s13,s14)`의 평균·0~4·높을수록 두려움·완전응답을 고정한다. 평균/SD/유효n/전체n은 상위 표와 정확히 일치해야 한다.
4. 신규 전달 근거 필드는 원본 파일명·SHA-256·시트/셀·전달 판본을 명시한다. 기존 `SourceV4`가 검사하는 SRC02/SRC03 hash를 바꾸거나 새 자료에 그 source ID를 재사용하지 않는다. 신규 로더에서 별도 구조로 검증한다.
5. 초기 호환 범위는 확인된 현행 설문의 문항 원문/선택지/방향 signature와 RP01 정책이다. 과거판은 같은 지표의 의미·척도·방향이 확인되어 매핑에 명시된 경우만 허용한다. 날짜·허용 숫자 범위만으로 호환을 추정하지 않는다.
6. XLSX 첫 시트 EXT1.1과 둘째 시트 C55 EXT1.0의 차이를 출처 주석으로 보존한다. 최신 누적 연결은 12~15절을 따른다. T12의 ‘당일’, T14의 ‘자기 값만’은 외부 미연결·예시 문맥으로 기록하고 전 회차 누적 비교를 삭제하는 근거로 쓰지 않는다. 원본 셀을 조용히 수정하지 않는다.

제품에 필요한 매핑·수치만 정규화해 넣고 논문 전문·개인 응답·가상 누적 평균을 자산에 넣지 않는다. 사용·번안 행정 상태 및 측정 동등성 검증 완료를 선언하는 필드도 만들지 않는다.

## 4 실제 기준 정의 적용

기존 기준 정의의 `source_asset_hash`, scope, 근거 파일, 수치, 대상 설명, 수치 출처, 사유, 기대 revision을 그대로 사용한다. 전달 원본을 기존 evidence 업로드로 등록하고 SF/NF 두 정의를 실제 actor로 저장한다. 새 매핑은 이 두 정의의 문항·척도·산식·수치를 대조할 수 있는 기준이다.

- 실제 등록은 구현 fixture와 다르다. CM05에 등록 시각·실제 정의 revision·근거 hash·적용 범위를 남긴다. 설정이 없으면 외부 지표만 미준비다.
- 별도 교수/관리자 승인이나 여섯 confirmed 체크를 복원하지 않는다. 임의 actor로 설치 시 자동 seed하거나 기존 사용중단 정의를 다시 켜지 않는다.
- 새 모드에서 사용하는 정의가 전달 매핑과 다르면 사유를 반환한다. 숫자를 강제 교체하거나 다른 정의로 조용히 fallback하지 않는다. 실제 수치 정정은 새 근거·정의 판본으로 명시한다.
- 등록 편의를 위해 기존 화면에 값을 채우는 동작을 추가한다면 ‘전달 기준 불러오기 → 근거/수치 확인 → 기존 저장·적용’ 하나의 경로로 제한한다. 새 승인 화면·별도 기준 관리 플랫폼은 만들지 않는다.

## 5 과거 hash 보호와 구현 순서

현재 [외부 snapshot](../../../backend/app/external_comparisons_v4.py#L117)은 출처·설문 자산 hash를 검증한다. 신규 파일을 기존 `comparisons.assets()` 결과에 무조건 추가하거나 원래 출처 자산을 덮으면 과거 발급 제공도 깨질 수 있다.

1. Graft callers로 `_sources`, `assets`, `save_definition`, 새 매핑을 읽을 호출자를 확인한다.
2. 매핑 로더·계약 시험을 먼저 만들고 기존 28문항·2개 수치와 대조한다.
3. 새 매핑 자산을 추가하고 신규 실행만 그 hash를 받게 한다. 기존 로더의 판본 상수를 전체 치환하지 않는다.
4. 실제 근거 등록 경로와 일반 계정 사용을 확인한다. fixture는 임시 저장소에서만 작성한다.
5. 원본 확인·기존 회귀·패키징·독립 검토 후 CM02/03에 매핑 interface와 hash를 인계한다.

## 6 검증과 명령

| 공통 시험 | 확인 내용 |
| --- | --- |
| CM-T01~T03 | 28→9 전수, Q25·역채점·0/null·허용 범위, 기존 RP01 계산 불변 |
| CM-T11·T24 | 판본/문항/척도 불일치, 실제 원본 셀·hash·전사 대조 |
| CM-T15·T18·T20 | 미등록·중단·다른 scope·근거 손상 구별, 일반 계정/actor |
| CM-T22 | 옛 기준 정의·외부 snapshot·출처 자산 bytes/hash 보존 |

```powershell
# backend/ — 신규 시험 파일은 본 PR에서 작성
uv run --locked python -X utf8 -m unittest tests.test_comparison_mapping_v4 tests.test_survey_v4 tests.test_comparisons_v4 tests.test_external_comparisons_v4 tests.test_packaging -v
uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check
# frontend/ — 설정 화면을 변경한 경우
npm run test:e2e -- external-v4.spec.ts
npm run build
# 저장소 루트
git diff --check
graft check
```

로컬 XLSX 부재 시 committed 계약 시험은 계속 실행하고 원본 셀 대조만 명시 skip한다. 원본이 있어도 hash가 다르면 skip이나 통과로 처리하지 말고 정정본 확인 오류로 기록한다. 기존 S1 importer의 8자산 성공을 신규 전달표 검증 성공으로 대체하지 않는다.

## 7 완료·되돌림·인계

- [ ] CM-T01~T03·T11·T15·T18·T20·T22·T24 중 본 PR 범위 통과
- [ ] 전달표와 자산의 출처·판본 차이 기록, 원본 미커밋/배포 미포함
- [ ] 과거 출처·설문 자산 hash 불변, 기존 기준 정의 저장 동작 유지
- [ ] 실제 기준 등록 여부를 합성 검증과 분리, 독립 검토·수용 재검증

오류 시 신규 매핑 사용 경로만 비활성하고 원본·기존 정의·기존 발급은 보존한다. 새 정의가 실제 등록된 뒤에는 원장을 삭제해 되돌리지 않고 새 판본으로 사용중단한다.

| 실행 기록 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | 미실행 |
| 공식 버전 확인일·최신/선택·이유·링크 | 구현 착수 시 기록, 새 의존성 계획 없음 |
| 명령·시험 수·시간·결과/skip | 미실행 |
| cold review·판정·수용 수정 | 미실행 |
| 매핑 interface·hash·실제 기준 등록 여부 | CM02/03/05 인계 시 기록 |
