# K-DOG 문항 매핑과 누적 비교 구현 실행 기록

버전: v1.0 · 2026-10-21 · 대상: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md) CM01~CM05 · 기준: `main 5e46ba8`

PR별 실제 commit·명령·결과·cold review·병합을 누적 기록한다. 합성 시험 결과와 실제 전달표 등록·운영 적용을 구별한다.

## CM01 확정 문항 매핑과 기준 자료

| 항목 | 결과 |
| --- | --- |
| 브랜치·PR | `veluga/cm01-comparison-mapping` |
| 구현 | `resources/report/survey-comparison-20261008.json`(EXT1.1, SHA-256 `7ad7b8f1cf451c1a23a87398c063ffe1415c47c3e481b0597eb4f72d98c277bb`), `backend/app/comparison_mapping_v4.py`, 기준 정의 목록의 전달 기준 대조, 설정 화면 ‘전달 기준 수치 불러오기’, launcher 필수 자산 |
| 원본 대조 | 로컬 XLSX 41,661 bytes · `6e52a3ad…bcfa` 셀 대조 시험 통과. 원본은 `/docs/참고자료/` 무시 목록, 미커밋 |
| 검증 | backend 43건 OK, packaging 20건 OK(build 후), S1 catalog check 통과, e2e `external-v4.spec.ts` OK |
| cold review | 발견 5·수용 5·보류 0·거절 0, 수정 후 재검증 통과 |
| 실제 기준 등록 | 미실행 — 운영 계정의 실제 근거 업로드·저장은 CM05에서 상태로 기록 |

## CM02 참여쌍과 대표 설문

| 항목 | 결과 |
| --- | --- |
| 브랜치·PR | `veluga/cm02-pair-survey-submissions` (CM01 위 누적) |
| 구현 | `backend/app/cumulative_comparisons_v4.py`, `backend/app/domain/cumulative_comparisons_v4.py`, API 4개, `maintenance.references` typed 분기, 설문 상세 `ComparisonParticipationV4` 패널 |
| 검증 | 신규 11건·관련 회귀 107건 OK, e2e 4건 OK |
| cold review | 발견 5·수용 5·보류 0·거절 0 |
| 운영 자료 | 운영 DB 참여쌍 연결·대표 확인은 미실행(CM05). 기존 자료 자동 편입 없음 |

## CM03 누적 집계와 출력 고정

| 항목 | 결과 |
| --- | --- |
| 브랜치·PR | `veluga/cm03-cumulative-comparison-snapshots` (CM02 위 누적) |
| 구현 | 접수 시 대표 설문 집합·9지표 정수 분자/분모·정확 반올림 snapshot 고정(`build_snapshot`/`adopt_snapshot`/`snapshot_document`/`public_rows`), 신규 실행·표현 판본, SF/NF 독립 외부 연결, Worker·다운로드 재검증, export 행, maintenance typed 분기 |
| 검증 | 신규 `test_cumulative_outputs_v4` 13건 OK. 초기 회귀 149건 중 28건 오류(시험 seam의 config 위치 인자)→수정 후 4건 실패(rp04 표현 판본 분기)→수정. 최종 회귀 153건 OK(352초, 로컬 원본 셀 대조 1건 skip) |
| 전달표 사례 | C01 SF 1.00·NF 1.33(n3)/개별 0.50·1.33/미국 0.66·1.03, C02 1.50·1.75(n4), C03 SF 1.25(n2)·NF n3, 10+90쌍 1.90, 83/100 n83, 9/8→1.13 합성 시험 통과 |
| cold review | 독립 검토 4건 모두 수용: 발급본은 자기 판본으로 열기(현재 매핑 변경이 옛 발급을 막지 않음, 새 실행만 재계산), 접수 트랜잭션에서 외부 기준 정의 재확인(변경 시 409), 기준 손상은 미준비가 아닌 기술 오류, 집계 기준일은 한국시간. 별도로 회귀에서 발견한 config 호출 형태·표현 판본 분기 회귀 2건을 수정. 수정 후 재검증 통과 |
