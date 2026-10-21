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
