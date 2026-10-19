# K-DOG 아키텍처 개선 적용 계획

버전: v1.0 · 2026-10-20 · 조사 기준: `main / bdc526f4b27fa5817e07b0f398ac78f62b29b705` · 상태: **AC01~AC05 구현·전체 회귀·독립 검토 완료**

최초 계획 문서 브랜치: `veluga/architecture-plan-20261020`(문서 PR #106). 이후 사용자 `/goal`로 AC01~AC05 전체 구현·완료 검증을 수행했다. 최초 문서 작성의 검증과 제품 실행 결과를 구별하며, 현재 근거는 [제품 실행 기록](K-DOG_아키텍처개선실행기록_v1.0_20261020.md)을 따른다. 배포·실제 공급자/현장 인수는 별도다.

## 1 근거와 적용 방향

2026-10-20 구조 검토 보고서 `architecture-review-20261020-002217.html`의 세 후보를 모두 계획 대상으로 삼는다. 보고서 SHA-256은 `f14a8d13696fbe448ddf6ae1736a4f707e6c89cc8cbc333541b6f15f889d1deb`이다. 보고서는 OS 임시 폴더의 검토 산출물이므로 이 문서에 근거와 결정을 재기록하며, 구현에 보고서 파일의 존속을 요구하지 않는다.

| 후보 | 관찰한 구조 | 적용 방향 | 담당 |
| --- | --- | --- | --- |
| 구간 CSV → 촬영 초안 | `segmentsCsv.ts`의 해석 뒤 구간 병합·미실시 보존·영상 offset 연결·출처 중복 방지가 화면에 남음 | 순수 계산 module의 interface를 초안 결과까지 깊게 함 | AC01 |
| 실행 추적·응답 복구 | AI 분석과 전처리 화면이 pending 보존·접수 복구·늦은 응답 무효화·타이머를 각각 관리 | 두 실제 흐름에 공통인 시간 규칙을 한 module로 모음 | AC02 |
| 점유한 실행의 내구 기록 | 쓰기 트랜잭션마다 현재 claim·running·lease·실제 실행 계정을 재검사 | 기존 `analysis.py`에 점유 검증과 쓰기 트랜잭션 수명을 함께 소유하는 module 동작을 추가 | AC03·AC04 |

세 후보는 보고서에서 모두 `Worth exploring`이었다. 계획의 성공 기준은 파일 수나 줄 수 감소가 아니라, 호출자가 알아야 할 순서·불변조건을 줄이면서 관찰 가능한 동작을 보존하는 것이다. 첫 적용은 순수 계산으로 범위를 제한할 수 있는 AC01로 한다.

우선순위 근거는 최근 90개 커밋의 변경 집중도와 실제 호출 관계다. `RecordingPanelV4.tsx`, `AiRunsV4.tsx`, `PreprocessingPanelV4.tsx`, `run_v4.py`, `report_runs_v4.py`가 반복 변경되었다. 변경 횟수는 결함 수나 리팩터링 효과의 측정값이 아니다.

## 2 선행 결정과 보존 조건

아래 문서는 요구사항을 정하는 근거다. 과거 문서의 소유·동의 차단이나 제거된 360 실행 경로를 복원하지 않는다.

- [S1 개발 반영 계획](../../archive/개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md), [인수 검증 대장](../../archive/개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md), [실측 및 확인 후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md).
- [업무 권한 단순화 계획](../K-DOG_업무권한단순화계획_v1.1_20261011.md): 모든 활성 업무 계정의 공유 작업, 실제 행위자, 원평가자·최초 독립 제출·불변 판본 보존.
- [4카메라·구간 CSV 계획](../4카메라구간CSV전환_20261014/K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md)과 [VC03](../4카메라구간CSV전환_20261014/K-DOG_PR-VC03_구간CSV가져오기_v1.0_20261014.md): 최소 형식 검증, 초안 채우기, 기존 저장·확정 경로.
- [Gemini 예비키 전환 계획](../Gemini주키예비키_20261013/K-DOG_PR-GK02_Gemini예비키자동전환_v1.0_20261013.md)과 [실행 기록](../Gemini주키예비키_20261013/K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md): attempt별 예약·선택·사용량·미확인 과금·정리 출처.
- [10월 17일 수용 수정](../K-DOG_추가점검수용수정_v1.0_20261017.md): 정상 `attachment_v4` 시작·초기화 보존과 호출별 설치 staging 보호.

계획의 가정은 **현재 업무 동작을 보존하는 내부 구조 개선**이다. S1 문항·산식·결측·관찰창, CSV 지원 범위, DB schema, 저장 JSON, HTTP 경로/응답, 실행 상태와 예산, 모델·프롬프트 판본을 변경하지 않는다. 예외를 발견하면 리팩터링 안에 섞지 않고 원인·영향·별도 조치를 기록한다.

원본 영상·고객 입력 workbook·실제 공급자 호출은 구조 개선의 선행 조건이 아니다. 합성 fixture와 현재 잠금 환경에서 검증한다. 미수령 평가 기준·교수 검토·물리 3PC·실제 공급자 품질의 후속 상태를 이 작업으로 완료 처리하지 않는다.

## 3 설계 원칙과 현행 근거

`codebase-design`의 module은 interface와 implementation을 가진 책임 묶음이며 반드시 새 파일을 뜻하지 않는다. interface에는 타입 외에도 호출 순서·오류·판본·문맥 조건이 포함된다. depth는 그 interface가 숨기는 동작의 가치다. locality는 규칙과 검증이 모이는 정도다. seam은 동작을 교체하는 위치, adapter는 그 위치의 실제 구현이다.

각 PR에서 deletion test를 수행한다. 새 module을 지웠을 때 보호 규칙이 여러 호출자에 다시 퍼지는지 확인한다. 조건식 이름만 바꾸거나 설정 callback을 늘린 경우에는 완료로 보지 않는다. 테스트도 같은 interface의 관찰 결과를 검증하며 내부 ref·SQL 순서의 복제를 목표로 하지 않는다.

| 확인 위치 | 현재 사실 | 계획에 반영할 내용 |
| --- | --- | --- |
| [segmentsCsv.ts](../../../frontend/src/segmentsCsv.ts#L32), [RecordingPanelV4](../../../frontend/src/RecordingPanelV4.tsx#L89) | parser는 의미가 있고 초안 병합은 화면에 있음 | parser를 삭제하지 않고 초안 반영까지 한 module의 책임으로 확장 |
| [AiRunsV4](../../../frontend/src/AiRunsV4.tsx#L15), [PreprocessingPanelV4](../../../frontend/src/PreprocessingPanelV4.tsx#L28) | 두 화면 모두 pending·sequence·generation·timer 관리 | 공통 시간 규칙과 각 업무 조회 해석을 분리 |
| [Preprocessing 페이지](../../../frontend/src/pages/Preprocessing.tsx#L22), [ScoreSheetsV4](../../../frontend/src/ScoreSheetsV4.tsx#L52) | 계정·대상·회차와 지정 실행의 React key로 재생성 | 기존 key와 입력 revision 변경의 효과를 구분해 시험 |
| [Store.connect](../../../backend/app/storage.py#L226) | `BEGIN IMMEDIATE`, 정상 종료 commit, 예외 rollback, 항상 close | 새 module이 이 수명 전체를 소유, 중첩 write 연결 금지 |
| [analysis.guard](../../../backend/app/analysis.py#L70) | 별도 연결에서 점유 확인·선택적 lease 갱신 | 쓰기 트랜잭션 안 재검사를 대체할 수 없음 |
| [Worker.reserve_call](../../../backend/app/worker.py#L48) | credential 선택 오류를 잠시 보관해 예약 commit 후 다시 raise | 공통화 때 rollback으로 바뀌면 안 됨 |
| [Worker.once](../../../backend/app/worker.py#L201) | access 실패도 마무리해야 하므로 token 조건부 실패 기록을 수행 | 정상 작업용 공통 쓰기에 넣지 않고 별도 오류 종료 의미 유지 |
| [scoring_ai_v4.publish](../../../backend/app/scoring_ai_v4.py#L402) | 기본 결과·시트·감사 기록도 같은 점유 재검사로 보호 | 보고서의 후보 목록을 보완하여 AC04에 포함 |

`Worker.stage`와 `gemini_keys`는 이미 여러 호출자에 동작을 제공한다. 새 범용 실행 엔진·provider router·DB repository·상태 관리 라이브러리를 도입하지 않는다. 리포트 화면의 추적 공통화, 전처리 서버/업로드의 다른 점유 체계, heartbeat·claim 획득은 이번 세 후보의 적용 대상 밖이다.

## 4 PR 분할과 순서

| PR | 개별 상세 계획 | 직접 선행 | 완료 결과 |
| --- | --- | --- | --- |
| AC01 | [구간 CSV 초안 module](K-DOG_PR-AC01_구간CSV초안통합_v1.0_20261020.md) | 없음 | parser와 순수 초안 계산을 같은 module로 모으고 촬영 화면 연결 |
| AC02 | [실행 추적 module](K-DOG_PR-AC02_실행추적통합_v1.0_20261020.md) | 없음 | AI·전처리 두 adapter가 같은 시간 규칙 사용 |
| AC03 | [점유 쓰기와 Worker](K-DOG_PR-AC03_점유쓰기와Worker_v1.0_20261020.md) | 없음 | 실제 write 수명과 점유 검사를 소유, Worker 네 쓰기 구간 적용 |
| AC04 | [산출물 채택·게시](K-DOG_PR-AC04_산출물채택과게시_v1.0_20261020.md) | AC03 | adopt·세 실행 완료·AI 결과 게시의 같은 트랜잭션 보호 |
| AC05 | [통합 회귀·인수 기록](K-DOG_PR-AC05_통합회귀와인수기록_v1.0_20261020.md) | AC01·AC02·AC04 | 전체 회귀·대상별 증거·후속 한계·코드 탐색 갱신 |

권장 실행 순서는 **AC01 → AC02 → AC03 → AC04 → AC05**다. AC01/02/03 사이의 직접 코드 선행은 없지만 하나씩 완료·검토해 기준을 고정한다. AC03만 병합된 상태에서도 Worker는 정상 동작해야 하며 AC04의 미전환 경로는 기존 보호를 유지한다. AC05는 제품 구조를 뒤늦게 수정하는 통합 PR가 아니라 앞선 PR들의 전체 회귀와 잔존 점검을 마무리한다.

각 PR은 `veluga/acNN-...` 한 브랜치로 구현 → 관련 시험 → 독립 cold review → 발견사항 수용/보류/거절 근거 → 수용 수정·재검증 → 기록 → push/PR 순서를 따른다. 실제 원격 생성·병합·배포는 해당 작업 지시에 따른다. 지금 만드는 파일의 PR 번호는 계획 식별자이며 GitHub PR 번호가 아니다.

## 5 요구사항 추적

| ID | 요구 | 담당 | 검증 |
| --- | --- | --- | --- |
| AC-R01 | CSV 해석·초안 병합의 단일 책임, 입력 불변 | AC01 | AC-T01~T03 |
| AC-R02 | CSV 비동기 충돌·UTF-8·원 bytes hash·기존 저장/확정 보존 | AC01 | AC-T04~T05 |
| AC-R03 | 실행 문맥·입력판 변경에서 늦은 응답 차단 | AC02 | AC-T06·T10 |
| AC-R04 | 접수 응답 유실·재진입을 같은 request로 조회 복구, 자동 재POST 없음 | AC02 | AC-T07·T09 |
| AC-R05 | poll/제어 순서·단일 타이머·정리·각 업무 상태 해석 보존 | AC02 | AC-T08~T10 |
| AC-R06 | 한 write 트랜잭션 안 점유·현재 실행 계정 재검사 | AC03·AC04 | AC-T11·T16 |
| AC-R07 | 예약·예비키 선택·실패·상한·미확인 과금의 commit 의미 보존 | AC03 | AC-T12~T14 |
| AC-R08 | 산출물/hash/stamp·최신 attempt·불변 경로·회복 의미 보존 | AC04 | AC-T15~T17 |
| AC-R09 | 결과·발급·감사 기록의 원자성, 실제 actor·중복 생성 방지 | AC04 | AC-T18~T19 |
| AC-R10 | 같은 보호가 아닌 claim/heartbeat/오류종료/업로드 경로를 혼합하지 않음 | AC03·AC05 | AC-T14·T21 |
| AC-R11 | 공유 업무·원평가자·판본·attachment 시작/보존 유지 | 전 PR | AC-T20·T22 |
| AC-R12 | 제품 계약·의존성·저장 형식 보존, 검증과 미실측 구분 | 전 PR | AC-T20~T22 |

시험별 입력·예상 결과·실행 파일은 각 PR에 둔다. 동일 ID의 소유자는 한 PR이며 AC05는 새 ID로 통합 결과를 검증한다. 변경한 interface로 충분히 검증된 구현 종속 시험만 정리하고, 회귀 fixture·사례는 중복처럼 보여도 임의 삭제하지 않는다.

## 6 구현 시 환경과 확인 절차

계획 작성에서 라이브러리 설치나 제품 라이브러리 실행은 하지 않았다. 새 패키지는 계획하지 않는다. 구현 시작 전에 공식 문서·릴리스·registry에서 **그 시점 최신 안정판, 선택 잠금판, runtime/peer, breaking change와 사용 interface**를 확인하고 해당 PR 실행 기록에 확인일·링크·선택 이유를 남긴다. 기존 잠금판을 유지할 때에도 이 확인을 생략하지 않는다.

대상은 AC01/02의 React·React DOM·TypeScript·Vite·Playwright, AC03/04의 Python 3.14 `contextlib`/`sqlite3`와 기존 FastAPI·Pydantic 및 해당 시험 의존성이다. 기준 manifest는 [frontend/package.json](../../../frontend/package.json), [backend/pyproject.toml](../../../backend/pyproject.toml), 잠금은 `frontend/package-lock.json`·`backend/uv.lock`이다. 구조 개선을 이유로 무관한 업그레이드를 섞지 않는다.

착수 시 `git status --short`, 기준 commit, 선행 PR 병합 상태, `graft check`를 확인한다. wiring이 낡았을 때 `graft build` 후 확인한다. 의미 요약 미생성만으로 wiring이 낡았다고 판정하지 않는다. Graft `callers`의 Python 동적 호출·JSX 누락은 `graft grep`으로 보완한다. 변경 후 호출자·잔존 경로를 다시 확인한다.

## 7 통합 완료·되돌림

- AC01~04 각각 해당 요구·시험 통과와 cold review 조치 근거가 있어야 한다. 화면의 레이아웃·문구를 바꾸는 경우 캡처를 PR에 첨부한다.
- AC05에서 전체 backend, 프런트 build와 전체 E2E를 한 번 수행한다. 통과 후 새 코드 변경·실패가 없으면 같은 전체 시험을 반복하지 않는다.
- 자동 시험은 합성 공급자/transport·임시 데이터만 사용한다. 실제 공급자 비용·참가자 원본·운영 DB는 사용하지 않는다.
- DB migration·저장 JSON 변경이 없어 이전 호환 코드로 되돌릴 수 있어야 한다. AC04 적용 뒤에는 AC04→AC03 역순으로 되돌리며, 이미 기록한 결과·usage·감사를 수정하거나 삭제하지 않는다. 개별 PR의 실패 처리 계획을 따른다.
- CLI 재시작·attachment 보존·기존 발급 bytes와 공유 접근도 회귀 대상으로 둔다. ZIP 발행·고객 배포·현장 검수는 별도 실행 지시와 실제 증거가 필요하다.

## 8 작성 시점 상태

| 구분 | 상태 |
| --- | --- |
| 보고서 세 후보 → PR별 범위·보존 조건·시험 계획 | 작성 |
| 현재 코드·기존 계획·실행 대장과 대조 | 수행; 상세는 [계획 검증 기록](K-DOG_아키텍처개선계획검증_v1.0_20261020.md) |
| 제품 구현·새 시험 작성·제품 회귀 | 미착수 |
| 계획 문서 cold review·PR·병합 | 후속 사용자 지시로 진행; [검증 기록](K-DOG_아키텍처개선계획검증_v1.0_20261020.md)에서 조치와 통합 이력 관리 |
| 제품 AC01~AC05 PR·배포 | 미실행 |

실행 결과는 각 PR 문서 마지막 표에 증거를 넣어 갱신한다. 미래 명령·예상 결과를 통과 기록으로 바꾸지 않는다.

## 9 2026-10-20 제품 구현 후속

§8은 최초 계획 작성 당시 상태다. AC01 순수 초안, AC02 두 화면 추적, AC03 Worker 네 쓰기, AC04 다섯 채택/게시 쓰기의 구현·국소 검증·독립 cold review를 완료했다. AC05에서 backend795(역사 원본2skip)·build·전체E2E150+추가3·최종 캡처/링크 검증을 완료했다. PR별 최종 통합은 [제품 실행 기록](K-DOG_아키텍처개선실행기록_v1.0_20261020.md) 및 [AC05](K-DOG_PR-AC05_통합회귀와인수기록_v1.0_20261020.md)에 실제 결과를 기록한다. 초기 계획 검증 기록의 “미착수” 표현은 당시 이력이다.
