# PR-CM05 통합 인수와 운영 적용

버전: v1.0 · 2026-10-21 · 상태: **기술 인수 완료 · 전달표 운영 등록/운영 누적 전환 미실행** (2026-10-21) · 직접 선행: CM01~CM04

상위: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md). 요구 CM-R01~R14 전수. 선행: [CM01](K-DOG_PR-CM01_확정문항매핑과기준자료_v1.0_20261021.md)·[CM02](K-DOG_PR-CM02_참여쌍과대표설문_v1.0_20261021.md)·[CM03](K-DOG_PR-CM03_누적집계와출력고정_v1.0_20261021.md)·[CM04](K-DOG_PR-CM04_비교화면과리포트_v1.0_20261021.md). 브랜치 제안: `veluga/cm05-cumulative-comparison-acceptance` · PR 제목: `test: verify mapped cumulative comparison delivery`

## 1 목적과 완료 구분

일반 업무 계정이 설문 등록·참여쌍 연결·대표 제출·기준 등록·최종 결과 선택·발급·내보내기를 이어서 수행하는 흐름을 검증한다. 두 기준표 미수령 상태였던 기존 대장을 실제 수령/구현/운영 적용 근거로 갱신한다.

| 구분 | 필요한 근거 |
| --- | --- |
| 계획 완료 | 링크·근거·범위·독립 검토. 제품 통과와 별개 |
| 기술 구현 완료 | CM01~CM04 병합, 합성 fixture·실제 renderer/export·과거 보존 통과 |
| 전달표 적용 완료 | 실제 XLSX hash/셀·수치 전사 및 실제 기준 정의 등록 판본 확인 |
| 운영 누적 전환 | 실제 참여쌍/대표 설문 근거 확인, 미확정/제외 범위와 실제 발급 대조 기록 |
| 별도 후속 | 한국어 측정 동등성·사용 허가·실제 AI 품질·현장3PC/깨끗한OS 실측 |

위 상태를 하나의 ‘완료’로 합치지 않는다. 실제 참가자 자료가 없으면 기술 인수는 진행하고 운영 전환은 부족 자료와 함께 미실행으로 남긴다. 운영 DB 변경·배포 작업은 그 시점 사용자가 허용한 범위에서 수행하며 이 계획 문서 작성만으로 실행하지 않는다.

## 2 파일별 변경과 기록

| 파일 | 작업 |
| --- | --- |
| 신규 예정 `backend/tests/test_cumulative_acceptance_v4.py` | 두 행사·다른 pair·재방문·정정·다른 cutoff 발급·백업/restore 실제 종단 |
| 신규/기존 frontend 비교·리포트·export·일반 업무 시험 | 설정에서 발급/download까지 기본 흐름, 계정 전환·작은 화면·응답 유실 |
| [test_packaging.py](../../../backend/tests/test_packaging.py), [launcher.py](../../../backend/app/launcher.py), [build_release.py](../../../scripts/build_release.py) | 신/구 자산 포함·필수 자산·원본 XLSX 제외, 설치 실행 |
| [DEVELOPMENT.md](../../DEVELOPMENT.md), [PILOT_OPERATIONS.md](../../PILOT_OPERATIONS.md) | 초기 등록·새 비교 판본·백업/복원·운영 한계 |
| [비교조건 설명서](../../사용설명서_20261013/K-DOG_비교조건_사용설명서_v1.0_20261013.md), [설문현황 설명서](../../사용설명서_20261013/K-DOG_설문현황_사용설명서_v1.0_20261013.md), [리포트발급 설명서](../../사용설명서_20261013/K-DOG_리포트발급_사용설명서_v1.0_20261013.md) | 참여쌍/대표 제출·지표별 n·2/3점·옛 발급 고정·실제 기준 미준비 |
| [RP06](../../archive/리포트개편_20261007/K-DOG_PR-RP06_외부비교기준표적용_v1.0_20261007.md), [리포트 실행 기록](../../archive/리포트개편_20261007/K-DOG_리포트구현실행기록_v1.0_20261007.md) | 과거 미수령 이력은 유지하고 현재 수령·적용 상태 및 본 계획의 실제 증거를 추가 |
| [추적표](../../archive/개발반영_20261003/K-DOG_요구사항추적표_v1.0_20261003.md), [인수대장](../../archive/개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md), [후속대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md) | R02/R07/R19·D06/P06/O09를 CM-R/CM-T 실제 결과에 연결 |
| 신규 예정 `K-DOG_문항매핑과누적비교구현실행기록_v1.0_20261021.md` | PR별 commit·명령/결과·버전검증·review·운영 적용을 누적 기록. 구현 착수 시 생성 |

과거 승인·동의/삭제 차단 성공을 새 업무 인수로 재사용하지 않는다. 현재 공통 업무 정책·원본 보호를 같이 검증한다. 원본·실제 신원·응답·발급 파일은 public 저장소의 문서/캡처에 넣지 않는다.

## 3 필수 종단 시나리오

1. 임시 S1 저장소에 두 행사와 서로 다른 pair를 등록한다. 28문항을 통해 9개 지표를 모두 유효하게 만들되 일부 별도 사례는 결측/미경험을 포함한다. 일반 계정A가 명시 연결·대표 제출을 기록하고 B가 같은 자료를 조회·후속 처리한다.
2. 실제 전달표와 동일한 SF/NF 수치를 기존 정의 저장 API로 등록한다. 시험 근거는 합성 파일임을 명시한다. 운영 XLSX 등록 검증은 별도 행으로 수행한다.
3. 기존 합성 최종 결과·fake AI 흐름으로 새 리포트를 접수해 실제 HTML/PDF를 생성한다. 별도 집단/외부 picker 없이 9개 비교가 연결되는지 확인한다.
4. XLSX C01·C02 수치를 대조하고 한 지표 결측·n0/1/2·같은 좌표·정확 반올림을 확인한다. SF/NF 한쪽만 유효한 발급과 기준 미등록/중단 발급도 수행한다.
5. 같은 pair의 재방문을 등록해 n 불변을 확인한다. 오입력 정정은 새 대표로 바꾸어 새 발급의 평균이 바뀌고 옛 HTML/PDF bytes/hash가 유지되는지 검사한다.
6. 같은 request ID의 재전송·Worker retry·cutoff 뒤 registry 변경에서 동일 snapshot을 확인한다. 새 request ID에서만 새로운 집계를 얻는다.
7. 보고서별 CSV ZIP/XLSX를 만든다. 서로 다른 원자료의 복수 보고서는 각 cutoff/평균/n/판본을 유지하고, 같은 원자료에서 cutoff만 다른 두 발급본은 각각 별도 export에서 값을 보존하는지 확인한다. 원자료 중복 선택 금지는 유지한다.
8. backup→격리 restore→조회/다운로드→clean으로 원장·대표 입력·외부 근거·옛/새 발급을 보존한다. 의도적으로 손상된 임시 참조는 clean 전에 오류가 나야 한다.
9. 옛 rp04 발급·연구 export·대기 실행 재시도를 별도로 확인한다. 새 optional 필드·자산 목록 때문에 옛 hash가 바뀌거나 제공이 막히지 않아야 한다.

## 4 인수 행과 명령

상위의 CM-T01~T24를 모두 인수표에 연결하고 미실행/skip을 분리한다. 아래 묶음은 합성 기술 인수다.

| 묶음 | 주 검증 | 증거 |
| --- | --- | --- |
| 매핑·산식 | CM-T01~T03·T11~T13 | 9개 지표 기대값·잘못된 입력/판본·source 대조 |
| 대표·누적 | CM-T04~T10·T16~T18 | 대표/재방문/정정·실제n·동시성·고정 cutoff |
| 출력·업무 | CM-T14·T15·T19·T20·T23 | 실제 HTML/PDF/CSV/XLSX·390px/인쇄·다른 업무 계정 |
| 수명주기 | CM-T21·T22 | backup/restore/clean·옛 bytes·옛 대기 실행 |
| 전달표/운영 | CM-T24 | 실제 근거 hash·정의 revision·운영 자료 확인 여부, 합성과 구별 |

```powershell
# backend/ — 신규 시험은 앞 PR 및 본 PR에서 작성
uv run --locked python -X utf8 -m unittest tests.test_cumulative_acceptance_v4 tests.test_cumulative_outputs_v4 tests.test_external_exports_v4 tests.test_report_runs_v4 tests.test_packaging -v
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check
# frontend/
npm run build
npm run test:e2e
# 저장소 루트
git diff --check
git diff -- docs/
graft check
```

초기 실패→수정→집중 재검증을 전체 성공으로 합산하지 않는다. 최종 전체 실행 결과·소요시간·정당한 source-dependent skip을 정확히 남긴다. 실패나 새 변경이 없는 한 같은 전체 시험을 이유 없이 반복하지 않는다. 릴리스 작성은 깨끗한 commit에서 [개발 안내](../../DEVELOPMENT.md)의 현재 build/verify 명령을 그대로 사용하고 실제 명령·ZIP hash·검증 결과를 실행 기록에 남긴다. 이 계획 단계에서 ZIP을 만들거나 운영 배포하지 않는다.

## 5 실제 기준·운영 적용 절차

1. 전달 XLSX의 hash·판본 차이·고정 수치/문항을 CM01 자산과 대조한다. 원본 파일 자체는 로컬 보존한다.
2. 실제 활성 업무 계정이 SF/NF 기준에 근거를 업로드해 저장·적용한다. 실제 정의 revision·actor·시각·근거 hash를 기록하고 별도 승인/자동 seed는 추가하지 않는다.
3. 운영 자료의 case→pair 연결과 최초 대표 출처를 확인한다. 근거 미확정 자료는 추정 편입하지 않고 건수·사유를 남긴다. 재방문·카메라·복제 파일이 표본이 되지 않는지 확인한다.
4. 적용 범위 안의 자료로 새 발급을 만들어 각 지표 포함 설문·원평균/n·외부값·기준일·판본을 대조한다. 기존 운영 발급본의 bytes/hash를 확인한다.
5. 실제 자료 또는 실행 권한이 없어 수행하지 못한 부분은 기술 완료와 구별해 후속 대장에 남긴다. 기준표 자체가 허가/측정 동등성 검증 완료의 증거라는 표현은 쓰지 않는다.

## 6 완료·복구·최종 기록

- [x] CM-R01~R14와 CM-T01~T24의 담당/결과 전수 연결 (아래 인수표)
- [x] 최종 관련/전체 회귀·frontend build/E2E·실제 HTML/PDF 시각 확인 (병합 후 전체 e2e 156/156, 서버 PDF는 pypdfium2로 래스터화해 패널·눈금·표식 확인)
- [x] 과거 bytes/자산·backup/restore/clean·패키지 원본 제외 확인 (병합 commit에서 포터블·사용자 설치형 ZIP 생성·`verify_release` 통과, 원본 XLSX 미포함)
- [x] 실제 전달표 등록·운영 자료 적용을 각각 실제 상태로 기록 (둘 다 미실행으로 기록)
- [x] 독립 cold review·수용 수정/재검증·링크/문구·PR commit 정리

문제가 있으면 신규 발급·누적 원장 쓰기를 중지하고 저장된 자료를 보존한 채 수정판을 적용한다. 잘못된 registry는 명시 정정으로, 잘못된 기준은 새 정의 판본으로, 잘못된 발급은 새 request로 바로잡는다. 현재 운영 DB를 새 형식 미지원 옛 앱으로 열거나 snapshot/원본을 삭제해 복구하지 않는다.

| 실행 기록 항목 | 결과 |
| --- | --- |
| 최종 commit·PR/병합 | 브랜치 `veluga/cm05-cumulative-comparison-acceptance`(CM04 위 누적). PR·병합 상태는 [실행 기록](K-DOG_문항매핑과누적비교구현실행기록_v1.0_20261021.md) |
| 공식 버전 확인일·최신/선택·이유·링크 | 2026-10-21 PyPI: openpyxl 3.1.5(최신=고정), reportlab 5.0.1(최신=고정), pydantic 2.14.1(고정 2.13.5), fastapi 0.156.4(고정 0.141.1). <https://pypi.org/project/openpyxl/> <https://pypi.org/project/reportlab/> <https://pypi.org/project/pydantic/> <https://pypi.org/project/fastapi/>. 새 의존성·lockfile 변경 없음, 무관한 업그레이드를 섞지 않음 |
| 전체/집중 시험 명령·건수·시간·초기 실패/재검증/skip | 전체 backend `unittest discover` 835건 OK(1,434초, skip 4: 기존 원본 의존 역사 시험. `KDOG_COMPARISON_DELIVERY`로 로컬 전달표 셀 대조 포함). 이후 cold review로 추가한 종단 시나리오 포함 `test_cumulative_acceptance_v4` 2건 OK(54초). `import_catalogs --spec 20261002 --customer-dir <로컬 원본> --check` 통과, `git diff --check`·`graft check` 통과 |
| 실제 HTML/PDF·작은 화면/인쇄·패키지 검증 | frontend build 후 전체 e2e 156건 중 155건 통과(573초), copy-guard 1건이 화면의 내부 표기 ‘S1’을 지적해 ‘미연결 대상’으로 수정 후 copy-guard·참여쌍·리포트 spec 10건 재통과. CM04 HTML 1100px·390px 캡처·브라우저 인쇄 PDF 확인. 병합 후 서버 PDF 래스터 확인·설치 ZIP 생성/검증 완료(아래 ‘병합 후 최종 검증’), 원본 XLSX 미포함 |
| 실제 전달표 등록·운영 pair/대표/발급 대조 | 미실행. 로컬 XLSX hash·셀 대조(CM-T24 원본 부분)는 시험으로 통과했으나 운영 DB의 SF/NF 정의 등록, 운영 참여쌍·대표 확인, 실제 발급 대조는 운영 계정·운영 자료 접근이 필요해 수행하지 않았다. [후속대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)에 남김 |
| cold review·수용/보류·남은 후속 | CM05 검토 발견 7건 모두 수용: 실패 실행→참여쌍 변경→명시 재시도 snapshot 불변, 누적 기록 이전 대기 rp04 실행의 이후 처리, 같은 원자료 중복 export 거절, 발급 snapshot 손상 시 clean 중단을 종단 시험에 추가, 실행 기록·인수표 CM-T 전수 연결, 개발 문서의 API 기본값·설명서 화면 문구·포함 범위 정정. 별도로 전체 e2e copy-guard 지적 1건 수정. 전체 PR 누적 cold review: CM01 5·CM02 5·CM03 4(+회귀 2)·CM04 6·CM05 7, 보류·거절 0 |

### 인수표 (합성 기술 인수)

| ID | 결과 | 근거 시험 |
| --- | --- | --- |
| CM-T01 | 통과 | `test_comparison_mapping_v4` t01, `test_cumulative_report_v4` 9패널 |
| CM-T02 | 통과 | `test_comparison_mapping_v4` t02_t03 (0/0·0/null·5/1·0.5/1·문자열) |
| CM-T03 | 통과 | `test_comparison_mapping_v4` t02_t03, `test_comparison_participation_v4` 부분응답 제출 |
| CM-T04 | 통과 | `test_cumulative_outputs_v4` C01, `test_cumulative_acceptance_v4` |
| CM-T05 | 통과 | `test_cumulative_outputs_v4` C02(1.50·1.75, n4)·옛 발급 bytes 불변 |
| CM-T06 | 통과 | `test_cumulative_outputs_v4` MissingAnswer, `test_cumulative_report_v4` 결측 패널 |
| CM-T07 | 통과 | `test_cumulative_outputs_v4` t07, `test_comparison_participation_v4` 재방문, 종단 인수 |
| CM-T08 | 통과 | 정정·제외 후 n 변화·재방문 자동 승격 없음(참여쌍·출력·종단) |
| CM-T09 | 통과 | `test_cumulative_outputs_v4` 10+90쌍 1.90, 83/100 n83 |
| CM-T10 | 통과 | n0/1/2 단위 시험, 단일 쌍 렌더링 |
| CM-T11 | 통과 | 매핑 변조 거절, 판본 불일치 제출 거절·미확정 유지 |
| CM-T12 | 통과 | 9/8→1.13(이진 float 1.12와 구별) |
| CM-T13 | 통과 | 표시값 비교 `equal_display` |
| CM-T14 | 통과 | NF 누적·개별 같은 x좌표·다른 줄(HTML 좌표·e2e 좌표) |
| CM-T15 | 통과 | SF만/NF만/둘 다 미등록, 중단·전달 기준 불일치 사유 |
| CM-T16 | 통과 | 접수 중 참여쌍·기준 변경 409, 동일 request 재사용, 참여쌍 재전송 |
| CM-T17 | 통과 | 접수 뒤 정정·Worker 실행은 같은 snapshot, 새 요청만 재집계 |
| CM-T18 | 통과 | snapshot 부모 손상 409, 잘못된 입력·회차 차단, 기준 손상은 기술 오류 |
| CM-T19 | 통과 | API·HTML·PDF 텍스트·CSV 행 같은 값·snapshot hash |
| CM-T20 | 통과 | 일반 업무 계정 교차 처리·비활성 거절·실제 actor |
| CM-T21 | 통과 | backup→격리 restore→다운로드→clean, 손상 시 clean 중단 |
| CM-T22 | 통과 | 옛 출처/설문 자산 hash, rp04 계약·bytes, 발급본은 자기 판본으로 열기 |
| CM-T23 | 통과 | `cumulative-comparisons-v4.spec.ts` 390px·1100px·인쇄·오프라인, 내부 ID 미노출 |
| CM-T24 | 원본 대조만 통과 | 로컬 XLSX hash·셀 대조 시험 통과. 운영 실제 등록·적용은 미실행 |
