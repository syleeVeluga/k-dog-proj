# PR-CM02 참여쌍과 대표 설문

버전: v1.0 · 2026-10-21 · 상태: **구현·검증·cold review 반영 완료** (2026-10-21) · 직접 선행: CM01

상위: [전체 계획](K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md). 요구 CM-R03·R04·R05·R09·R10·R12. 선행: [CM01](K-DOG_PR-CM01_확정문항매핑과기준자료_v1.0_20261021.md). 브랜치 제안: `veluga/cm02-pair-survey-submissions` · PR 제목: `feat: record comparison pairs and representative surveys`

## 1 문제와 완료 결과

현재 case의 유일성은 행사 내 `(event_id, participant_id)`다. 설문 저장·Forms 등록은 새 입력 revision을 만들지만 최초 제출/정정/재방문을 구별하지 않는다. 따라서 case당 한 회차를 고르는 기존 집단만으로는 전 회차 참여쌍 중복을 제거할 수 없다.

원응답 저장·Forms import를 유지하고 **비교용 참여쌍 연결과 실제 제출 사실만 별도 원장으로 추가**한다. 최초 대표와 수정·재방문이 명시되어 CM03이 추정 없이 누적 후보를 읽을 수 있으면 완료다. 별도 보호자·반려견 master, 개인정보 수집 확대, DB 초기 이관은 필요하지 않다.

## 2 파일별 변경 계획

| 파일 | 변경·재사용 범위 |
| --- | --- |
| 신규 예정 `backend/app/cumulative_comparisons_v4.py` | 참여쌍/제출 생성·조회·기대 판본 검사·고정 입력 해석. CM03이 집계 interface 추가 |
| 신규 예정 `backend/app/domain/cumulative_comparisons_v4.py` | registry·submission·typed pointer, public 목록/상태 계약 |
| [comparisons_v4.py](../../../backend/app/comparisons_v4.py#L151) | `changes` 최신 ref·`comparisons/` 불변 파일 방식 재사용. 공통 계정 검사 유지 |
| [intake.py](../../../backend/app/intake.py#L69), [storage.py](../../../backend/app/storage.py#L276) | 현재 회차 선택·설문 저장·불변 입력·이전 입력 조회를 조사. 일반 저장을 제출로 바꾸지 않음 |
| [forms_v4.py](../../../backend/app/forms_v4.py#L624) | 기존 입력/출처 보존 회귀 확인. import 성공을 대표 확정으로 간주하지 않음 |
| [api.py](../../../backend/app/api.py) | `/comparisons-s1` 아래 필요한 pair/submission API만 추가 |
| [Survey.tsx](../../../frontend/src/pages/Survey.tsx) | 설문 상세에 작은 참여쌍·제출 상태 패널 연결, 기존 업로드 입력 방식 유지 |
| 신규 예정 `frontend/src/ComparisonParticipationV4.tsx` 및 비교 타입 | 새/기존 참여쌍 명시 연결, 최초 제출·정정·재방문·제외 기록 |
| [maintenance.py](../../../backend/app/maintenance.py#L71) | 신규 artifact의 typed 부모/원입력 참조 수집·backup/clean/restore 폐쇄 |
| 신규 예정 `backend/tests/test_comparison_participation_v4.py`, `frontend/tests/comparison-participation-v4.spec.ts` | 상태·입력불변·동시성·일반 계정·화면 문맥·유지보수 검증 |

## 3 저장 계약

### 3.1 참여쌍 상태

`pair_id`는 하나의 보호자–반려견 조합을 가리키는 opaque ID다. 같은 보호자의 다른 반려견, 다른 보호자와 같은 반려견은 다른 pair다. event·이름·견종·전화번호로 자동 병합하지 않는다.

- 신규 artifact 제안: `comparison-pair-state`. `pair_id`, 명시 연결 `case_ids`, 현재 포함/제외 상태와 사유, 대표 submission pointer, 이전 state pointer, 실제 actor·recorded_at·reason을 보존한다.
- `changes`의 `comparison.pair_state`/pair target에 최신 state pointer를 기록한다. case→현재 pair 연결도 같은 write fence에서 확인하며 한 case가 동시에 두 활성 pair에 속하지 못하게 한다. 필요하면 같은 `changes`에 case별 head projection을 기록하되 독립 DB 테이블은 추가하지 않는다.
- JSON은 기존 관리 경로 `comparisons/` 아래 배타 생성한다. actor·hash·pointer를 검증한 뒤 transaction에서 head를 채택한다. 파일 생성 후 transaction 실패로 남은 고아는 기존 clean 계약으로 처리한다.
- `expected_reference` 또는 `expected_revision`, request ID/payload digest를 받는다. 같은 요청 재전송은 같은 결과, 다른 payload는409다. 상태 없는 신규 연결도 ‘없음’을 기대한 요청으로 경쟁 검사한다.

### 3.2 설문 제출 사실

신규 artifact 제안: `comparison-survey-submission`. `submission_id`, pair/case/session, input revision·manifest ref/hash, 매핑/문항 signature·설문 정책, 제출 종류, 근거, actor·recorded_at, 교체하는 이전 submission pointer를 저장한다.

모든 제출 종류를 `changes(action="comparison.submission", target=submission_id, detail_json={reference})`에 같은 채택 transaction으로 기록한다. 재방문도 대표 head를 바꾸지 않을 뿐 제출 파일과 원입력을 가리키는 영속 참조를 가진다. 최신 pair state만을 원장 진입점으로 삼아 재방문 자료를 고아로 만들지 않는다.

| 동작 | 대표 영향 | 남기는 사실 |
| --- | --- | --- |
| 최초 제출 | 같은 기준의 첫 명시 제출을 전체 설문 대표로 지정 | 실제 제출 사실·원입력 pointer |
| 오입력 정정 | 기대한 현재 대표 한 건을 새 전체 설문으로 교체 | 교정 사유·이전 대표·새 입력 |
| 재방문 기록 | 대표 불변 | 후속 설문 pointer·방문 기록 |
| 비교에서 제외 | 원래 대표를 보존하고 누적 포함만 중단 | 제외 사유·시각·actor |
| 제외 취소/연결 정정 | 실제 근거와 기대 판본으로만 변경 | 이전/이후 상태 및 사유 |

28문항 전체가 숫자로 채워져야 ‘제출’할 수 있는 제약은 추가하지 않는다. 입력 모델이 허용한 정수/null·결측 사유를 보존하고 완전응답은 각 지표에서 판단한다. 대표의 결측을 재방문 응답으로 보완하거나 지표마다 다른 대표를 고르지 않는다. 대표 제외 시 재방문을 자동 승격하지 않는다.

기존 과거 자료에는 실제 최초 제출 시각이 없을 수 있다. 그 경우 운영자가 출처 근거를 확인해 최초 대표를 명시 등록하고 실제 과거 제출시각과 현재 기록시각을 구별한다. 근거 없는 자료는 `representative_unconfirmed`로 남긴다. case 생성일·파일 순서·input revision이 작다는 이유로 최초 제출을 추정하지 않는다. 신규 명시 제출에는 서버 기록시각을 쓰되 과거 사실을 소급 발명하지 않는다.

### 3.3 연결 정정의 최소 규칙

잘못 연결한 case를 다른 pair로 옮기는 경우 옛/새 pair의 기대 head를 한 transaction에서 검사한다. 옛 pair의 대표가 그 case에서 왔다면 새 집계에서 옛 pair를 미확정/제외 처리하고 원래 대표 pointer는 이력으로 보존한다. 새 pair의 기존 대표는 자동 교체하지 않는다. 새 대표가 필요하면 제출/정정 동작으로 명시한다. 전체 pair 자동 병합·일괄 신원 정정 기능은 추가하지 않는다.

제외 취소·재포함은 현재 case→pair 연결, 대표 submission의 pair/case 소속·원입력·signature를 다시 검증한다. 대표 case가 이미 다른 pair로 이동했거나 대표가 미확정이면 단순 포함 전환을 거절하고 올바른 대표를 명시하도록 한다. 역사 ref가 보존되어 있다는 사실만으로 현재 누적 자격을 복구하지 않는다.

## 4 고정 입력 resolver와 API

현재 `selected_session()`은 현재 선택 회차와의 일치를 요구한다. 신규 제출 resolver는 **고정 manifest 안의 명시 session_id 존재·대상·revision/hash**를 검증해 읽는다. 이후 촬영 회차를 바꾸거나 이름을 정정해도 대표 원응답이 바뀌지 않는다. 새 제출/정정 요청에는 그 시점 현재 입력 판본을 확인하고, 과거 자료 선택은 보존 입력 pointer임을 명시 검증한다.

예정 HTTP interface는 다음 정도로 제한한다. 실제 경로/DTO는 구현 후 문서와 CM03에 확정 인계한다.

| 경로 제안 | 목적 |
| --- | --- |
| `GET /comparisons-s1/pairs?case_id=...` | 해당 case 연결·대표·미확정 상태 및 기존 pair 선택 후보 |
| `POST /comparisons-s1/pairs` | 새 pair 생성 또는 명시 case 연결/정정, 기대 head 검사 |
| `POST /comparisons-s1/pairs/{pair_id}/submissions` | 최초·정정·재방문 사실 기록 |
| `POST /comparisons-s1/pairs/{pair_id}/state` | 포함/제외 및 근거 정정 |

모든 활성 업무 계정에 같은 업무 권한을 적용한다. 관리자 승인·소유자 제한·동의/삭제 metadata를 포함 조건으로 사용하지 않는다. 실제 세션/계정 활성 상태, 연결 대상, 기대 판본, 원입력·파일 hash를 write fence에서 다시 검사한다. 읽기·폴링은 제출/편집 사건을 만들지 않는다.

## 5 화면과 유지보수

설문 상세에서 ‘새 참여쌍/기존 참여쌍 연결 → 최초 제출/오입력 정정/재방문 기록’으로 이어진다. 현재 대표·미확정·제외와 근거를 보여 준다. 기존 ‘모두 응답/등록 현황’과 ‘누적 비교 제출 상태’를 별도 의미로 표시한다. UUID·64자리 hash·개발 코드 대신 대상 이름/행사/제출일·판본으로 구분하고 상세 출처에서만 기술 정보를 확인한다.

case/session/계정 전환, 늦은 요청, 연속 클릭, 응답 유실 재접속에 기존 generation/request ID 보호를 적용한다. 일반 응답 저장·Forms 등록만으로 대표가 바뀌지 않는다는 점을 동작과 화면 문구로 확인한다. 기존 `SessionV4.comparison_eligibility`는 역사 metadata이며 새 원장 결과를 입력 manifest에 역기입하지 않는다.

`maintenance.references`는 pair state와 모든 `comparison.submission` 사건을 진입점으로 삼아 이전 state/대표·재방문 submission→원입력의 실제 typed pointer만 순회한다. 원문 metadata의 ref 유사 문자열을 파일로 오인하지 않는다. 원본·이전 대표·이전 state·재방문 기록·발급 참조는 clean 대상이 아니다. 누락/변조는 삭제 전에 전체 참조 검사에서 차단하며 restore는 백업 시점 원장/입력을 그대로 복원한다.

## 6 구현·검증·완료

1. Graft로 save_survey/Forms/immutable input/maintenance 호출 범위를 재확인한다.
2. 임시 저장소에서 제출/정정/재방문·기대 판본·고정 회차 해석 시험을 작성한다.
3. 작은 registry/submission interface와 API·참조 수집을 구현한다.
4. 설문 상세 패널을 연결하고 실제 요청/응답 유실·화면 문맥 검증을 수행한다.
5. backup/restore/clean 및 원입력/평가자 bytes 보존, 독립 cold review 후 CM03에 인계한다.

| 공통 시험 | 본 PR의 구체 기대 |
| --- | --- |
| CM-T03·T07·T08 | 부분 응답도 제출, 재방문 대표 불변, 정정만 전체 대표 교체, 제외 후 자동 승격 없음 |
| CM-T11 | 최초 근거/판본 미확정 유지, 현재 설문 날짜를 구판으로 오인하지 않음 |
| CM-T16 | 같은 case의 동시 다른 pair 연결 한 요청만 성공, stale409·재전송 중복 없음 |
| CM-T18·T20 | 잘못된 case/session/manifest/hash 차단, 일반 계정 허용·비활성 거절·actor 기록 |
| CM-T21 | 이전 state/대표/입력 참조 폐쇄, metadata 오인 방지, 복원 뒤 동일 상태 |

추가 사례: 같은 이름의 서로 다른 pair, 같은 보호자·다른 개, 현재 촬영 회차 변경 뒤 대표 유지, 일반 설문 저장/Forms 재등록 뒤 대표 유지. 대표 case의 다른 pair 이동 뒤 단순 재포함 거절, 재방문 제출 후 backup/restore/clean에서도 후속 기록과 원입력 보존을 검증한다. 대표 A=1/B=3은 이후 CM03에서 평균2·n2, A 재방문5는 그대로, A 정정2는 새 평균2.5·n2가 되어야 한다.

```powershell
# backend/ — 신규 시험은 본 PR에서 작성
uv run --locked python -X utf8 -m unittest tests.test_comparison_participation_v4 tests.test_comparisons_v4 tests.test_comparisons_api_v4 -v
# frontend/
npm run test:e2e -- comparison-participation-v4.spec.ts survey-v4.spec.ts importer-v4.spec.ts
npm run build
# 저장소 루트
git diff --check
graft check
```

유지보수 시험은 신규 participation 시험에 실제 임시 backup/restore/clean을 포함한다. 기존 관련 시험 파일은 착수 시 Graft로 확인해 추가한다. 운영 DB·실제 참가자 신원으로 시험하지 않는다.

- [x] 고정 registry/submission 및 공통 업무 API·설문 패널 연결
- [x] 동시성·재전송·회차 변경·원입력/평가자 불변·참조 폐쇄 통과
- [x] 기존 자료 자동 편입 없음, 미확정 사유/건수 조회 가능
- [x] 독립 검토·수용 재검증·CM03 interface 인계

되돌릴 때 원장·원입력을 지우지 않는다. 새 제출/연결 쓰기를 중지하고 수정판을 적용한다. 신원 오류의 정정은 새 state로 남기며 과거 발급 snapshot을 다시 쓰지 않는다.

| 실행 기록 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | 브랜치 `veluga/cm02-pair-survey-submissions`(CM01 위 누적). commit·PR은 [실행 기록](K-DOG_문항매핑과누적비교구현실행기록_v1.0_20261021.md) |
| 공식 버전 확인일·최신/선택·이유·링크 | 2026-10-21 CM01 기록과 동일(새 의존성 없음, lockfile 불변). 프런트는 기존 React/Playwright 고정판 사용 |
| 명령·시험 수·시간·결과 | `test_comparison_participation_v4` 11건 OK. 관련 회귀(comparisons·api·forms·deletion_restore·intake_api·business_access·shared_outputs 포함) 107건 OK(94초). e2e `comparison-participation-v4`·`survey-v4`·`importer-v4` 4건 OK, 390px 가로 넘침 없음 |
| cold review·판정·수용 수정 | 원장/수명주기 검토 2건·화면/API 검토 3건, 5건 모두 수용: 재포함 시 문항 signature·매핑·정책 재확인, 정정은 대표와 같은 대상만, 같은 내용 재시도 시 request ID 재사용, 대표 미확정 제외 쌍의 재포함 허용(기여 없음 유지), 저장 성공 후 새로고침 실패 문구 분리. 재검증 통과 |
| 확정 API/타입·참조 action·CM03 인계 | `GET/POST /api/comparisons-s1/pairs`, `POST .../pairs/{pair_id}/submissions`, `POST .../pairs/{pair_id}/state`. changes action `comparison.pair_state`·`comparison.pair_case`·`comparison.submission`·`comparison.pair_request`. artifact `comparison-pair-state`·`comparison-survey-submission`. CM03 interface: `pair_ids`·`pair_head`·`read_state`·`representative_input` |
