# PR-CM04 비교 화면과 리포트

버전: v1.0 · 2026-10-21 · 상태: **구현 전** · 직접 선행: CM03

상위: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md). 요구 CM-R01·R02·R07~R10·R12~R14. 선행: [CM03](K-DOG_PR-CM03_누적집계와출력고정_v1.0_20261021.md). 브랜치 제안: `veluga/cm04-comparison-report-display` · PR 제목: `feat: render mapped cumulative and research comparisons`

## 1 문제와 완료 결과

현재 그래프는 개인 막대이며 선택 집단 평균·외부값은 설명문으로 붙는다. 이 상태는 전달표의 7개 지표 2점·두려움 2개 지표 3점 비교가 아니다. 기존 리포트의 다른 카드·영상 산식·AI 문장 흐름을 유지하고 비교 구역과 기본 발급 연결만 바꾼다.

완료 결과는 **추가 picker 조작 없이 새 발급에서 9개 지표가 고정 누적값·사용 가능한 미국값과 함께 출력되고, 상태·숫자·문장이 같은 근거를 가리키는 것**이다. 사용자 화면에는 계산·선정의 내부 구현 대신 비교 대상·값·n·기준일·부족 사유를 보여 준다.

## 2 파일별 변경 계획

| 파일 | 변경·재사용 범위 |
| --- | --- |
| [ReportRunsV4.tsx](../../../frontend/src/ReportRunsV4.tsx), 관련 report 타입 | 신규 기본 발급은 CM03 자동 누적·등록 외부 기준 사용. 확인/발급 결과에 cutoff·지표별 상태 표시 |
| [ComparisonSettings.tsx](../../../frontend/src/ComparisonSettings.tsx) | 기존 명시 집단은 수동 선택 집단으로 유지, 전체 누적과 이름/설명 혼동 방지 |
| [ExternalComparisonPickerV4.tsx](../../../frontend/src/ExternalComparisonPickerV4.tsx), [ResearchExportsV4.tsx](../../../frontend/src/ResearchExportsV4.tsx) | 기존 명시 선택 용도 보존. 보고서 선택 export는 고정 비교값을 사용하도록 연결 |
| [report_render_v4.py](../../../backend/app/report_render_v4.py#L82) | 새 판본 공통 비교 행 모델/문장 연결. 기존 `number()`와 옛 출력 유지 |
| [report_design_v4.py](../../../backend/app/report_design_v4.py#L22), [report_pdf_v4.py](../../../backend/app/report_pdf_v4.py) | 새 표현 판본에서 동일 행을 HTML/PDF 점 위치로 렌더링 |
| 신규 예정 report JSON/HTML/CSS 자산 | 신규 `report-presentation-20261021-cm`만 사용. 기존 rp04 bytes 보존 |
| [report_runs_v4.py](../../../backend/app/report_runs_v4.py#L537) | CM03 판본 dispatch에서 새 renderer/자산 선택 |
| [test_report_design_v4.py](../../../backend/tests/test_report_design_v4.py), [test_report_render_v4.py](../../../backend/tests/test_report_render_v4.py) 및 신규 출력 회귀 | 숫자·문장·좌표·옛 발급·PDF 실제 내용 |
| [report-design-v4.spec.ts](../../../frontend/tests/report-design-v4.spec.ts), [report-print-v4.spec.ts](../../../frontend/tests/report-print-v4.spec.ts), 신규 예정 `cumulative-comparisons-v4.spec.ts` | 실제 기본 발급·390px·인쇄·오프라인·export 연결 |

기존 파일별 exact span은 CM03 병합 후 Graft로 다시 확인한다. 자산이 새로 추가되면 CM01의 launcher/패키징 필수 목록에 같이 반영한다. runtime 라이브러리나 차트 패키지를 추가하지 않고 기존 HTML/CSS·PDF 도형을 사용한다.

## 3 공통 비교 행과 표시 규칙

서버가 반환하는 행은 metric ID·제목·문항 집합·축 min/max·개별/누적/미국의 원값과 둘째 자리 문자열·n·상태/사유·비교문장·출처·cutoff를 포함한다. HTML과 PDF가 같은 행을 소비하고 JS/PDF에서 각각 평균·반올림·고저를 재계산하지 않는다.

| 표시 | 규칙 |
| --- | --- |
| SF/NF | 각각 별도 0~4 가로축, 높을수록 보고된 두려움 |
| 나머지 7지표 | 1~5 원척도, 누적·개별만 표시 |
| 표식 색 | 미국 회색·우리 누적 파란색·개별 주황색. 색 외에 이름/모양·줄로 구분 |
| 같은 값 | 같은 x좌표에 두되 표시 줄을 달리함. 겹침 회피를 위해 값 위치를 이동하지 않음 |
| 숫자 | 0.00·1.00처럼 둘째 자리 고정. 원평균·중간값 보존 |
| 누적 라벨 | ‘우리 누적 참여견 평균(n={해당 지표 유효 수})’, 집계 기준일 |
| 외부 라벨 | ‘미국 연구 평균’, 지표별 유효 n·P1 저자/연도·DOI·해석 한계 |

미국 평균이 없는 지표에 회색0점·빈 막대·범례를 만들지 않는다. 9지표를 가로지르는 미국 레이더 선, 두려움의 0~100 사회성 환산, 평균±SD 오차막대를 추가하지 않는다. 기존 리포트의 교육·애착·걷기 유형을 이 평균으로 자동 변경하지 않는다.

### 3.1 지표별 안내

- 개별 응답 부족/입력확인/판본확인은 해당 패널 자리를 유지해 안내한다. 그 패널에 미국·누적 비교 표식과 고저 문장을 그리지 않는다. 다른 유효 패널은 정상 표시한다.
- 개별이 유효하고 실제 누적 n=0/1이면 누적 표식·누적 고저 문장만 생략한다. SF/NF의 유효 미국값은 개별과 2점으로 유지한다.
- 기준 미등록/사용중단/대상 범위 불일치이면 해당 외부점만 미준비로 표시한다. 누적·개별이 유효하면 그 2점은 유지한다.
- 후보 선정 미확정·제외 자료가 있으면 실제 확인 범위/제외 건수를 안내한다. 구현하지 않은 누적을 n0으로 표시하지 않는다.
- 근거 손상·타 대상 pointer 등 기술 오류는 정상적인 응답 부족으로 표시하지 않는다. CM03의 오류를 원인에 맞게 전달한다.

### 3.2 문장과 출처

미국 비교는 TXT-H/L/E/M/V/I의 의미를 유지해 영역명·표시값·유효 표본·출처를 연결한다. 표시값이 같으면 ‘소수 둘째 자리 표시 기준에서 같습니다’라고 한다. 누적 비교도 표시값의 산술 차이만 설명한다. 다른 7지표의 높음/낮음을 좋음/나쁨·위험·정상으로 바꾸지 않는다.

공통 한계: 미국 연구 참여견의 참고 평균이며 한국어 번안·조사 맥락 차이가 있고 국내 표준이나 진단 기준이 아니다. 두려움은 사회성 전체와 같지 않다. 유효 n을 전체43,517이나 개인 응답 문항 수와 혼동하지 않는다. SD는 필요 시 근거 상세에서만 제공한다.

고정 비교문장은 deterministic 비교 구역에 표시한다. AI에게 평균 대비 진단·백분위·유의성 해석을 새로 맡기지 않는다. 기존 narrative에 비교 내용을 전달할 경우에도 동일 고정 사실만 사용하며 고정 문구와 상충하는 판단이 없는지 확인한다.

## 4 화면 흐름과 과거 보존

1. 설문 화면의 CM02 참여 상태를 확인한 뒤 기존 최종 결과에서 새 리포트를 발급한다. 수동 집단·외부 picker를 다시 선택하지 않아도 CM03의 새 기본 모드가 동작한다.
2. 발급 전 안내에는 전체 회차 누적 대상·미확정 자료·외부 기준 미준비 여부를 표시한다. 발급 후 숫자는 접수 시점 snapshot이며 현재 조회값으로 바꾸지 않는다.
3. 연구 export에서 보고서를 선택하면 그 보고서의 누적 기준일/판본을 보여 준다. 현재 평균과 옛 보고서 값이 다르더라도 옛 값을 유지한다.
4. 옛 rp04 보고서·명시 수동 집단·외부 선택 UI는 자기 판본과 기능으로 남는다. 옛 파일을 신판 모양으로 다시 렌더링하거나 과거 bytes를 덮지 않는다.

case/session/계정 변경 뒤 늦은 응답·download·설정 변경 결과가 다른 대상에 붙지 않게 한다. 일반 업무 계정의 조회/발급을 허용하고 개발자 설정 보호를 변경하지 않는다.

## 5 구현·검증

1. CM03 확정 DTO/판본을 받은 뒤 Graft callers로 report config·renderer·picker·export 연결을 확인한다.
2. 공통 비교 행 모델과 두/세 표식 도형을 구현한다. 기존 전역 숫자 표시·다른 보고서 구역은 바꾸지 않는다.
3. 신규 기본 발급 UI·상태 안내·고정 export 연결을 완성한다.
4. 실제 HTML/PDF를 생성해 텍스트와 각 페이지 이미지를 확인한다. 인쇄·오프라인 HTML·390px에서 표식·n·출처·장문 안내를 확인한다.
5. 독립 검토와 수용 재검증을 완료하고 CM05에 화면/발급 증거를 인계한다.

| 공통 시험 | 기대 결과 |
| --- | --- |
| CM-T01·T03·T04 | 9개 모두 표시, Q25·Q24 단일값·S09 역채점, 가상 예시 수치 일치 |
| CM-T06·T10·T15 | 한 지표 결측/기준미준비가 다른 패널을 없애지 않음, n0/1/2에 맞는 표식 |
| CM-T12~T14 | 1.125→1.13, 표시값 동률 문장·동일 좌표·구분 가능한 표식 |
| CM-T19·T22·T23 | HTML/PDF/export 같은 값·출처, 옛 bytes, 작은 화면·인쇄·오프라인 |

```powershell
# backend/
uv run --locked python -X utf8 -m unittest tests.test_cumulative_outputs_v4 tests.test_report_render_v4 tests.test_report_design_v4 tests.test_report_runs_v4 tests.test_external_report_acceptance_v4 -v
# frontend/ — 신규 시험은 본 PR에서 작성
npm run test:e2e -- cumulative-comparisons-v4.spec.ts report-design-v4.spec.ts report-print-v4.spec.ts external-v4.spec.ts comparisons-v4.spec.ts
npm run build
# 저장소 루트
git diff --check
graft check
```

UI 캡처는 합성 자료로 만들고 로컬 원본 XLSX/개인 자료를 포함하지 않는다. PDF 페이지 수를 고정 합격조건으로 삼지 않고 내용 잘림·반복/누락·한글·출처·표식을 본다. 새 문구가 기존 copy-guard와 충돌하면 내부 ID를 노출하는 대신 업무 언어로 고친다.

## 6 완료·되돌림·인계

- [ ] 9지표의 실제 2/3점·독립 안내·고정 문장/출처
- [ ] 신규 발급의 자동 연결과 보고서 기반 export 연결
- [ ] HTML/PDF 전 페이지·390px·인쇄·오프라인 시각 검증
- [ ] 과거 판본 보존·독립 검토·수용 수정, CM05 인계

문제가 있으면 신규 표현 판본의 발급을 중지하고 수정한다. 옛 자산을 덮어 동일 판본처럼 보이게 하지 않는다. 이미 발급한 파일과 그 template hash는 유지한다.

| 실행 기록 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | 미실행 |
| 공식 버전 확인일·최신/선택·이유·링크 | 구현 착수 시 기록 |
| 명령·시험 수·시간·결과 | 미실행 |
| 캡처·실제 HTML/PDF 시각 검증 | 미실행 |
| cold review·판정·수용 수정·CM05 인계 | 미실행 |
