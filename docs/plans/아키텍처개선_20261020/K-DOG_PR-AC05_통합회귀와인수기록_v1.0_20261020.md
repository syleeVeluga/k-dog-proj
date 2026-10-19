# PR-AC05 통합 회귀와 인수 기록

버전: v1.0 · 2026-10-20 · 상태: **통합 검증 완료** · 직접 선행: AC01·AC02·AC04 병합(AC03 포함)

브랜치 제안: `veluga/ac05-architecture-acceptance` · 제목 제안: `test: verify architecture refactors preserve S1 workflows`

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 요구 AC-R10~R12 및 AC-R01~R09의 통합 결과 확인.

## 1 목표와 범위

세 후보의 적용을 합친 코드에서 기존 업무 흐름·접수 복구·불변 결과·실제 실행 계정·호출 예산을 보존했음을 확인한다. AC01~04의 국소 시험은 각 PR에서 완료한다. 이 PR은 선행 PR의 빠진 기본 구현을 채우는 단계가 아니다.

전체 회귀·잔존 코드 검토·문서 링크와 실행 기록을 마무리한다. 새 사용자 기능·리포트 화면 추적 통합·DB 전환·설치 구조 개편은 포함하지 않는다.

## 2 대상 파일과 증거

| 대상 | 작업 |
| --- | --- |
| AC01~AC04 상세 문서와 전체 계획 | 실제 구현명·기준 commit·시험·cold review·후속을 링크 |
| 이 문서 | 통합 기준 commit, 전체 결과·실패 조치·화면 캡처·잔존 분류·한계 기록 |
| `frontend/tests/recording-v4.spec.ts`, `analysis-status-v4.spec.ts`, `preprocess-executions-v4.spec.ts`, `gemini-key-fallback.spec.ts` | 기존 시나리오를 재사용하고 연결 누락이 있을 때만 의미 있는 회귀 보완 |
| `backend/tests/test_gemini_acceptance.py`, `test_report_acceptance_v4.py`, `test_execution_actor_v4.py` | 실제 조립 경로의 합성/transport 검증 재사용 |
| `backend/tests/test_deployment_v4.py`, `test_reset_s1.py`, `test_packaging.py` | attachment 시작·초기화 보존·기존 runtime 참조가 유지되는지 전체 회귀에서 확인 |
| [docs/DEVELOPMENT.md](../../DEVELOPMENT.md) | 새 module 탐색 안내가 필요한 경우에만 최소 보완; 설치 명령·운영 정책 변경 없음 |

제품 source에서 발견한 회귀는 책임 있는 AC01~04 변경으로 원인을 추적해 수정하고 관련 시험을 다시 수행한다. 단순 예상값 변경으로 통과시키지 않는다.

## 3 통합 시나리오

| ID | 시나리오 | 인수 증거 |
| --- | --- | --- |
| AC-T20 | 합성 4영상 등록 → 구간 CSV 초안 → 수동 보완/확정 → 전처리 새 실행·재사용 → AI 분석 → 완료 의견·애착 해석 → 최종 결과·리포트 발급 | 각 단계 입력판·hash·참조 연결, 기존 저장/결과 의미, 원 request_id·불변 출력 확인. 기존 fixture를 조합하며 새 거대 시험 framework를 만들지 않음 |
| AC-T21 | 응답 유실·메뉴 이동·입력판 변경·worker 중단/회복·주키 실패/예비키 전환을 해당 기존 시나리오에 적용 | 늦은 응답 배제·자동 재POST 0·성공 step 재호출 0·예산/usage 보존. 적용/제외 쓰기 분류와 dynamic caller 목록 |
| AC-T22 | 다른 활성 업무 계정의 조회·재시도·발급, 옛 발급본 읽기, 정상 attachment 실행이 있는 저장소 재시작·반복 초기화 | 실제 actor·원평가자·독립 제출 provenance, 이전 bytes/감사 보존, CLI 시작 성공. 운영 DB를 사용하지 않음 |

각 시나리오를 반드시 한 E2E 파일에 모두 넣을 필요는 없다. 이미 검증한 fixture 연결·계약을 사용해 행별로 실제 시험 이름과 결과를 기록한다. 합성 transport 통과를 실제 공급자 품질이나 교수 인수로 기록하지 않는다.

## 4 실행 명령과 순서

선행 PR 기준 commit과 clean/미커밋 상태를 먼저 기록한다. 의존성은 구현 시점에 검증한 lockfile을 사용한다. 현재 `frontend/playwright.config.ts`는 `tests.browser_server`를 시작하므로 8765 포트에 남은 다른 시험 프로세스가 없는지 확인한다. 작업이 소유한 시험 프로세스만 종료한다.

```powershell
# backend/ — 전체 합성·계약·기존 인프라 회귀
uv run --locked python -X utf8 -m unittest discover -s tests -v
# frontend/
npm run build
npm run test:e2e
# 저장소 루트
git diff --check
git diff -- docs/
graft build
graft check
```

S1 customer source 검사는 기록된 hash로 확인한 원본이 있는 환경에서 다음 명령으로 추가한다. 없는 경우 committed 계약 시험 결과와 **원본 대조 미실행**을 구분한다. 이번 구조 개선이 고객 원본·카탈로그를 변경하지 않았음을 diff로 확인한다.

```powershell
# backend/ — 검증된 로컬 S1 원본이 있을 때
uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check
```

국소 시험 통과 뒤 전체 회귀를 한 번 수행한다. 실패를 고쳐 제품 코드가 변경되면 영향 범위와 연결된 회귀를 재실행하고, 기존 전체 결과를 다른 commit의 성공으로 옮겨 적지 않는다. 최종 상태를 판단할 수 없는 경우 전체를 다시 수행한다.

## 5 구조·잔존 검토 표

| 검토 대상 | 기대 |
| --- | --- |
| RecordingPanelV4 | 초안 merge/offset/출처 규칙이 화면에서 제거되고, bytes/hash·비동기 guard·기존 change/save는 유지 |
| AI·전처리 화면 | 새 module에 pending/응답 순서/타이머 책임이 모이고 두 adapter가 실제 사용; parent key·storage payload 보존 |
| 리포트 화면·전처리 목록 | 계획하지 않은 범용 추적 통합이 유입되지 않음 |
| Worker의 네 write 구간 | 같은 db의 현재 점유/계정 검사와 mutation, credential 실패 후 예약 commit |
| adopt·세 실행 완료·scoring publish | 다섯 구간 모두 전환, stamp·최신 attempt·감사 원자성 보존 |
| claim·guard/heartbeat·Worker.once·action | 별도 책임의 의도적 잔존 사유 기록 |
| uploads/preprocess 서버 토큰 | runs와 다른 상태/테이블임을 확인하고 공통 module에 편입하지 않음 |
| 기존 source/type/test 정리 | 이번 변경이 만든 orphan만 정리; v3 입력 참조 등 필요한 역사 계약 보존 |

Graft의 direct/transitive callers와 exhaustive 검색 결과를 함께 검토한다. 추출 결과의 줄 수 감소가 아니라 호출자가 알아야 할 불변조건 감소와 두 실제 화면의 공유 사용을 완료 근거로 삼는다.

## 6 검토·배포 범위·되돌림

독립 cold review는 프런트 응답 순서, backend commit/rollback, old attempt 회복, 실제 actor, source/stamp와 발급 bytes, 상한/usage를 중심으로 수행한다. 발견사항마다 재현·수용/보류/거절·담당 PR·재검증을 남긴다.

이번 통합 인수는 코드와 합성 시험의 인수다. 새 ZIP 발행·고객 전달·운영 DB 작업·실제 공급자 호출·물리 PC 검수는 실행하지 않은 것으로 기록한다. 패키징 회귀 통과를 실제 새 배포물 발행으로 표시하지 않는다.

문제가 있으면 해당 PR을 코드 단위로 되돌린다. backend는 AC04→AC03 순서를 지키고 데이터·출력/usage/audit는 보존한다. 오래된 동의/삭제 정책 앱으로 운영 DB를 열어 되돌리지 않는다.

- [x] 선행 네 PR의 실제 완료·검토 근거와 AC-T01~T19 추적
- [x] AC-T20~T22와 backend 전체·build·E2E 통과
- [x] 390/1440에서 CSV·AI 실행·전처리 표시와 복구 안내 확인
- [x] 잔존 분류·링크·Graft freshness·변경 범위 점검
- [x] 독립 검토 조치·최종 commit·미실측/미실행 범위 기록

## 7 실행 기록

| 항목 | 실제 결과 |
| --- | --- |
| 선행 PR·시험 기준 commit·작업트리 | [AC01 #107](https://github.com/syleeVeluga/k-dog-proj/pull/107) `f949d55`, [AC02 #108](https://github.com/syleeVeluga/k-dog-proj/pull/108) `0e01185`(저장 예외 수정 `3b75014` 포함), [AC03 #109](https://github.com/syleeVeluga/k-dog-proj/pull/109) `4bbe1f0`, [AC04 #110](https://github.com/syleeVeluga/k-dog-proj/pull/110) `78f4695`. 전체 backend는 `78f4695`, 최종 frontend는 동일 source에 `3e52379`와 CSV fixture 2줄을 적용. 정규화 SHA-256으로 17파일 고정·통합 시 동일성 확인 |
| 최신/선택 의존성 확인일·공식 링크 | 2026-10-20 공식 문서·release·registry 확인. 기존 lock 유지. [실행 기록 §2](K-DOG_아키텍처개선실행기록_v1.0_20261020.md#2-공식-버전호환성-확인) |
| backend 전체 명령·건수·시간·skip 이유 | §4 unittest discover: 795 tests / 1352.898초 / OK (skipped=2). 역사 v3 원본 2건은 로컬 별도 확보 필요로 skip; 현재 S1 source는 별도 통과 |
| 프런트 build·전체 E2E 건수·시간 | build 통과(기존 chunk 경고). 전체 150 passed / 9.8분. 후속 AC-T09 시험만 추가하여 별도 3 passed / 21.5초; 제품 변경 없음. 153개 전체 사례를 두 실행의 합집합으로 검증 |
| AC-T20/21/22 시험 이름·결과 | [실행 기록 §7](K-DOG_아키텍처개선실행기록_v1.0_20261020.md#7-ac-t01t22-실제-시험-추적)의 실제 recording/preprocess/Worker acceptance·fallback·shared/actor·deployment/reset/packaging에 연결. backend 전체 및 frontend 전체150+후속3 통과 |
| 화면 캡처·잔존 분류 | [실행 기록 §5·§8](K-DOG_아키텍처개선실행기록_v1.0_20261020.md): 9구간 전환, 12파일/44symbol/80occurrence 잔존 책임 분류. 390/1440 CSV·AI·전처리 6 PNG 최종 전체 성공 실행에서 갱신·가로 넘침 assertion/육안 확인 |
| cold review·수용 수정·재검증 | 사용자 허용 독립 프런트/백엔드 검토. AC-CR01~04 수용·수정·회귀 보강, actionable 잔여 0건. backend reviewer 6건 포함 29 tests / 10.165초 통과. AC05 문서 1차 사실 검토0건·PyPI 링크 누락 보완. 후속 T09 직접 주입 근거 누락 수용·3시험 추가 검증 |
| 원본 source check / 미실행 사유 | S1 importer exit 0, 8자산 source verified. G01/G04 실물 workbook·산식/주소는 미수령 후속 유지. 고객 원본 변경·커밋 없음 |
| commit·PR·병합 / 실제 배포 범위 | [#111](https://github.com/syleeVeluga/k-dog-proj/pull/111). 선행4PR main 병합 완료, 통합 `36218c5`에서 source/시험17파일 동결 일치. [실행 기록 §9](K-DOG_아키텍처개선실행기록_v1.0_20261020.md#9-pr-통합과-최종-고정)에 실제 PR/병합 commit 연결; 본 PR의 최종 merge는 GitHub 이력 참조. 새 ZIP·고객 배포·운영 DB·실제 공급자·현장 3PC 검수는 미실행 |
