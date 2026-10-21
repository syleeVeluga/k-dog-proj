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

## CM04 비교 화면과 리포트

| 항목 | 결과 |
| --- | --- |
| 브랜치·PR | `veluga/cm04-comparison-report-display` (CM03 위 누적) |
| 구현 | 공통 패널 모델(`comparison_panels`·`comparison_sources`), HTML 점 표식·PDF `MetricPanel`, 신규 표현 자산, 리포트 화면 기본 누적 발급·안내·발급본 비교표, 연구 export 보고서 선택의 누적 기준일 |
| 검증 | 신규 `test_cumulative_report_v4` 5건 OK. 백엔드 회귀(누적·렌더·디자인·실행·인수·패키징·API·export·참여쌍) 99건 OK(290초, 로컬 원본 셀 대조 1 skip). e2e `cumulative-comparisons-v4`·`report-v4`(신규 CM04 포함 4건)·`report-design-v4`·`report-print-v4`·`external-v4`·`comparisons-v4`·`comparison-participation-v4` 통과. 기존 `external-v4`는 이전 방식 접힘에 맞춰 펼침 단계만 추가 |
| 시각 확인 | HTML 1100px·390px·브라우저 인쇄 확인, 서버 PDF 래스터 확인은 도구 부재로 미실행(텍스트 검증만) |
| cold review | 발견 6·수용 6·보류 0·거절 0 |

## CM05 통합 인수와 운영 적용

| 항목 | 결과 |
| --- | --- |
| 브랜치·PR | `veluga/cm05-cumulative-comparison-acceptance` (CM04 위 누적) |
| 구현 | 종단 합성 인수 `test_cumulative_acceptance_v4`(두 행사·재방문·정정·두 cutoff·별도 export·backup/restore/clean·옛 rp04 보존), 운영·개발·사용 설명서와 RP06·리포트 실행 기록·추적표·인수대장·후속대장 갱신 |
| 전체 시험 | 전체 backend `unittest discover` 835건 OK(1,434초, skip 4: 기존 원본 의존 역사 시험. `KDOG_COMPARISON_DELIVERY`로 로컬 전달표 셀 대조 포함). 이후 cold review로 추가한 종단 시나리오 포함 `test_cumulative_acceptance_v4` 2건 OK(54초). `import_catalogs --spec 20261002 --customer-dir <로컬 원본> --check` 통과, `git diff --check`·`graft check` 통과 |
| e2e·시각 | frontend build 후 전체 e2e 156건 중 155건 통과(573초), copy-guard 1건이 화면의 내부 표기 ‘S1’을 지적해 ‘미연결 대상’으로 수정 후 copy-guard·참여쌍·리포트 spec 10건 재통과. CM04 HTML 1100px·390px 캡처·브라우저 인쇄 PDF 확인. 병합 후 서버 PDF 래스터 확인·설치 ZIP 생성/검증 완료(아래 ‘병합 후 최종 검증’), 원본 XLSX 미포함 |
| cold review | CM05 검토 발견 7건 모두 수용: 실패 실행→참여쌍 변경→명시 재시도 snapshot 불변, 누적 기록 이전 대기 rp04 실행의 이후 처리, 같은 원자료 중복 export 거절, 발급 snapshot 손상 시 clean 중단을 종단 시험에 추가, 실행 기록·인수표 CM-T 전수 연결, 개발 문서의 API 기본값·설명서 화면 문구·포함 범위 정정. 별도로 전체 e2e copy-guard 지적 1건 수정. 전체 PR 누적 cold review: CM01 5·CM02 5·CM03 4(+회귀 2)·CM04 6·CM05 7, 보류·거절 0 |
| 운영 적용 | 미실행: 운영 SF/NF 정의 등록, 운영 참여쌍·대표 확인, 실제 발급 대조. 별도 후속(허가·측정 동등성·실제 AI 품질·현장 실측) 유지 |

## PR과 병합 상태

| PR | 브랜치 | 상태 |
| --- | --- | --- |
| CM01 | `veluga/cm01-comparison-mapping` | [syleeVeluga/k-dog-proj#115](https://github.com/syleeVeluga/k-dog-proj/pull/115) 병합 `8d81357` |
| CM02 | `veluga/cm02-pair-survey-submissions` | [syleeVeluga/k-dog-proj#116](https://github.com/syleeVeluga/k-dog-proj/pull/116) 병합 `498312a` |
| CM03 | `veluga/cm03-cumulative-comparison-snapshots` | [syleeVeluga/k-dog-proj#117](https://github.com/syleeVeluga/k-dog-proj/pull/117) 병합 `ffb054e` |
| CM04 | `veluga/cm04-comparison-report-display` | [syleeVeluga/k-dog-proj#118](https://github.com/syleeVeluga/k-dog-proj/pull/118) 병합 `322635f` |
| CM05 | `veluga/cm05-cumulative-comparison-acceptance` | [syleeVeluga/k-dog-proj#119](https://github.com/syleeVeluga/k-dog-proj/pull/119) 병합 `cc8a2e6` |

병합: 2026-10-21 각 PR을 누적 순서(CM01→CM05)로 원격 `main`에 병합했다. 앞 PR 병합 뒤 다음 PR의 기준 브랜치를 `main`으로 바꾸고 검증한 head SHA 조건으로 병합했다. 병합 뒤 원격 `main`(`cc8a2e6`)의 tree는 CM05 검증 head와 같고, 로컬 `main`을 fast-forward해 일치시켰다. 첫 병합 시도는 세션 권한 판정에 막혔다가 권한 모드 변경 뒤 수행했다.

## 병합 후 최종 검증 (2026-10-21)

병합된 `main`(`e8170c5`)에서 남은 검증을 수행했다.

| 항목 | 결과 |
| --- | --- |
| CM05 최종 commit cold review | `3e8cf83`·병합 기록 commit 대상 독립 검토: 결함 0. 선택 보강 2건(정정 전 응답 변경으로 고정값 증명, clean 실패 시 409·파일 미삭제 단언)을 수용해 종단 시험에 반영, 2건 OK |
| 전체 e2e | frontend build 후 `npx playwright test` 156/156 통과(581초) |
| 서버 PDF 래스터 | 2026-10-21 PyPI 최신 pypdfium2 5.14.0·Pillow 13.0.0을 `uv run --no-project --with`로 일회 사용(프로젝트 의존성·lockfile 변경 없음). 합성 CM 발급 PDF 6쪽 중 비교 패널 쪽을 이미지로 확인: 눈금과 표식 위치 일치, NF 누적·개별 같은 x좌표·다른 줄, 미국 표식은 SF/NF만 |
| 설치 ZIP | 깨끗한 병합 commit `e8170c5`에서 [개발 안내](../../DEVELOPMENT.md) 명령으로 생성·검증. 포터블 `kdog-s1-windows-x64.zip` 1,461파일·SHA-256 `3b545e9a1c77bea0c7b66d7c4665f689973f51bc7130fef2965a9c05c98f319b`, 사용자 설치형 `kdog-s1-windows-x64-online.zip` 252파일·SHA-256 `6f4bf9064e39c05fdd3bfbe95823c06e50f55328ec70591785fd6922839447ad`. 두 ZIP 모두 `verify_release` 통과(170초), 원본 XLSX 미포함·신규 자산 포함 확인. 범위는 현재 Windows 호스트의 새 폴더이며 깨끗한 OS·다른 PC 실측이 아님 |
| 운영 기준 등록·운영 누적 전환 | 미실행. 운영 DB에서 실제 업무 계정 로그인·근거 업로드·기준 저장과 실제 참여쌍 확인이 필요하며, 계획 §1·§5에 따라 사용자가 허용한 범위에서 수행한다 |
