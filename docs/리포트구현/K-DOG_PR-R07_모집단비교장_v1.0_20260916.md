# PR-R07 「다른 분들과 나란히 놓으면」 — 설문 모집단 비교 장

버전: v1.0 · 2026-09-16 · 상태: **고객 확인 대기(Q-R1)** · 의존: [R03](K-DOG_PR-R03_HTML템플릿과그래픽_v1.0_20260916.md) · 독립 PR

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md) §5 Q-R1. 근거: 06b 04장·`00_읽어주세요` 「모집단 (2026-09-14)」 절, 04 문항근거 §1(심혜미 등 2022, n=300, 4요인)·§4 「300명 기준선은 … 우리 참가자가 특이한 집단이 아니다를 확인하는 데만」, 변경검토 N9 「모집단 34명 자료는 프로그램 밖 자료 → 범위 확인 필요」·§7 3번, 01 §6 「다른 개와 비교 없음 · 백분위·등수 없음」.

## 왜 별도 PR인가

06b의 04장은 **설문**(보호자 자기보고)을 다른 보호자들 옆에 놓는 장이다. 01 §6이 금지하는 「다른 개와 비교」와는 대상이 다르지만, 06b 본문도 「전체 보호자 중 몇 등이 아니라 비슷한 분들 사이에서 어디쯤으로 읽으셔야 합니다」라고 조심스럽게 쓴다. 그리고 자료(7~9월 설문 34명, 논문 300명 평균·표준편차)는 프로그램 밖에서 관리됐다(`AI관련자료 / 모집단 / 00_읽어주세요.md`, 저장소에 없음). 고객이 (1) 본촬영 리포트에 이 장을 유지할지, (2) 모집단 파일을 프로그램이 관리할지 답해야 만들 수 있다. 회신 전에는 `report-v2.json.chapters.population.enabled=false`로 장이 없다(R02).

## 자료 두 종류

| 자료 | 내용 | 출처·형식 | 개인정보 |
| --- | --- | --- | --- |
| 논문 규범 | 하위요인 4개(긍정교육 1~6 · 사회화 관여 7~9 · 친밀감 15~21 · 안정적 반응 26~28)의 평균·표준편차·n=300 — 06b 본문 값: 4.00/0.71, 3.42/1.02, 4.57/0.54, 4.27/0.78 | `resources/reference/survey-norms-v1.json`(저장소, 출처 DOI `10.14405/kjvr.20220011`, 인용 문구). 값은 고객이 확인한 것을 그대로 옮기고 출처 페이지를 기록 | 없음 |
| 우리 모집단 | 응답자별 하위영역 평균 7개(R02 `subscales`와 같은 정의) + 수집일 라벨(「7월 29일」…) | 운영자가 CSV로 가져와 자료 폴더 `population/<set_id>.csv`에 불변 저장 + `changes` 감사. **응답자 식별자·이름 없음**, 행 = 응답자 1명 | 익명 집계값만 |

C-BARQ 계열 3개 하위영역(사회성 10~14, 분리 22·23, 재회 24)은 논문 규범이 없으므로 「우리끼리만」(06b와 같음). 본촬영 72쌍의 설문도 승인된 뒤 모집단에 더할 수 있으나 **자동으로 더하지 않는다** — 운영자가 내보낸 익명 집계를 다시 가져오는 명시적 절차로 둔다(리포트 생성 시점에 따라 결과가 달라지는 것을 막고, 어떤 모집단으로 만들었는지 `ReportInput`에 `population_set_id`·해시로 남긴다).

## 변경 범위

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `resources/reference/survey-norms-v1.json` | 신설 | `{version, source{citation, doi, n:300, sample_note}, subscales{teaching{mean,sd}, socialising{…}, closeness{…}, consistency{…}}}` |
| `backend/app/population.py` | 신설 | `import_population(store, db, data, format, label, actor) -> PopulationSet`(열: `collected_on`, `teaching, socialising, closeness, consistency, dog_sociability, separation_distress, reunion_settle` — 빈칸 허용), `active_set(store, db)`(가장 최근 가져온 것; 운영자가 선택 가능), `summary(set) -> {subscale: {n, mean, values}}` |
| `backend/app/storage.py` · `maintenance.py` | 변경 | `population` 폴더·`MANAGED` 추가. 표는 만들지 않고 `changes` `population.import{ref, hash, label, rows}`로 참조 |
| `backend/app/report/input.py` | 변경 | `population_available` 조건: 규칙 `enabled` + 활성 모집단 존재. `Chapter("population").data = {rows: [{subscale_title, mine, norm{mean,sd,n} \| null, ours{n, mean, values}, note}], intro_note, collected_note}` |
| `backend/app/report/svg.py` | 변경 | `distribution(norm, ours, mine)` — 06b `dist` 구조: 옅은 종 모양(정규 근사 곡선, `viewBox 0 0 560 40`), 작은 점(우리 값), 진한 점(보호자), 세로선(평균). 점 위치 `(v−1)/4`. 값이 같은 점은 06b처럼 겹쳐 그림 |
| `backend/app/report/render.py` | 변경 | 04장: 06b 문구 이관(「2026년 여름부터 …」는 규칙 파일에서 날짜·인원을 채우는 템플릿), 규범 있는 4개 → 없는 3개 순서, `dist-src` 각주. 숫자는 06b처럼 소수 2자리(설문이므로 허용) |
| `resources/rules/report-v2.json` | 변경 | `population: {enabled, intro, norm_note, ours_only_note, reading_note}` 문구 |
| `backend/app/api.py` | 변경 | `POST /api/population/import`(admin), `GET /api/population`(reader: 세트 목록·n·라벨), `/api/imports/*` 종류에 `population` 추가 여부는 Importer 재사용 판단 후 결정 |
| `frontend` | 변경(최소) | 자료 가져오기에 「모집단(익명 집계)」 종류, 리포트 메뉴 준비 영역에 「모집단: {label} n={n}」 표시 |
| `backend/tests/test_population.py` | 신설 | 아래 |

## 시험

- 06b 1번의 04장 값으로 골든: 보호자 4.17/4.67/4.71/4.67, 우리 평균 4.07/3.81/4.46/4.14(n 34/19/34/34), C-BARQ 3개 우리 평균 3.335/2.845/4.325(n 25) → 합성 모집단 CSV를 만들어 넣으면 렌더 결과의 숫자·n·점 개수가 06b와 같다.
- 모집단 없음 → 장 없음, `enabled=false` → 장 없음(자료가 있어도).
- 식별자 열이 있는 CSV 거절(열 이름 허용 목록 외 거절), 이름처럼 보이는 문자열 값 거절(숫자·날짜만).
- 두 세트 가져온 뒤 리포트가 어느 세트를 썼는지 `ReportInput.population_set_id`·해시로 남고, 세트가 바뀌어도 기존 판은 그대로(불변).
- 검사기: 04장 본문(06b 문구)이 `forbidden`을 통과 — 특히 「평균보다」 금칙어와 충돌하는지 확인해 문구를 조정(06b는 「평균과 … 거의 같습니다」로 쓴다).

## 완료 조건

1. 고객이 Q-R1에 「유지·프로그램 관리」로 답한 경우에만 `enabled=true`로 병합한다. 「유지·외부 관리」면 CSV 가져오기만, 「삭제」면 이 PR은 열지 않는다.
2. 06b 1번 04장이 숫자까지 재현된다.
3. 모집단 파일에 개인 식별 정보가 들어갈 길이 없다.

권장 PR 제목: `feat: 설문 모집단 비교 장 — 논문 규범 파일과 익명 모집단 가져오기`
