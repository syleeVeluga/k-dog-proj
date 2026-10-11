# K-DOG PR-AR05 공유 산출물과 비교 기준

버전: v1.0 · 2026-10-11 · 상태: 상세 계획 / 제품 구현 미착수 · 선행: AR03·AR04
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.0_20261011.md). 조사 기준 `d6dd58a`; 진행 중인 로컬 U08 수정은 제외한다. 실제 착수 시 최신 병합 코드의 호출 관계를 다시 확인한다.

## 1 목표·현재 근거

[exports.guard/list](../backend/app/exports_v4.py#L284-L302), [validation._readable/list](../backend/app/validation_data_v4.py#L214-L219), [report._source_access/download](../backend/app/report_runs_v4.py), [comparisons 확인·활성화](../backend/app/comparisons_v4.py#L379-L441), [external_comparisons](../backend/app/external_comparisons_v4.py), [외부비교 domain](../backend/app/domain/comparisons_v4.py)를 대상으로 한다.

타인 생성 검수자료·export·리포트·집단·외부 기준을 공유하고 관리자의 연구 확인/별도 활성화 승인 절차를 제거한다. 실제 기준이 없거나 기술적으로 맞지 않는 자료는 계산할 수 없다는 조건은 남긴다.

## 2 상세 변경

1. validation actor, export snapshot.actor, 목록 WHERE actor, 시트 본인/active/grant/reveal 조건을 접근 판단에서 제거한다. 모든 업무 계정이 조회·다운로드·다음 작업에서 사용할 수 있다. 원 생성자와 실제 열람/발급자는 각자 기록한다.
   Forms 열 대응 preset의 작성자/admin 전용 삭제·can_delete와 영상 수신 `_row`의 creator=request actor 조건도 공통 업무로 바꾼다. 원 creator/request ID는 중복 식별로 보존하고 현재 재수신/연결/취소 actor·lease/claim/session 검사를 별개로 한다. 계정별 request ID 충돌이 서로의 파일을 잘못 이어 받게 해서는 안 된다.
2. 리포트 원입력/최종/의견 조회와 download의 disclosure·소유자 role·동의·삭제 검사 제거. 과거 발급본의 본문도 공개 허가 없이 제공하되 실제 ref/hash·발급 입력은 검증한다. 제출 전 타인이 만든 결과 열람도 audit/독립성 기록으로 처리한다.
3. 불변 검수 source/export/report 파일은 직접 덮어쓰지 않는다. 검수 대응표/조건 수정, 내보내기 선택 변경, 리포트 내용 변경은 모든 사용자가 새 판본/새 산출물을 만들며 이전 것은 계속 열 수 있다. 한 사람의 수정 권한으로 '타인 원본 수정 불가' 차단을 대체하지 않는다.
4. 외부 비교의 admin-only 확인자료 화면·여섯 confirmed 체크·별도 활성화 승인과 approved-only 출력 정책을 업무 승인 조건에서 제거한다. 검증된 기준 정의 저장/적용 동작 하나로 정리한다. 적용·변경·사용중단은 일반 사용자 모두 수행하며 actor/기준판본/영향 이력을 남긴다.
5. 실제 기준값·문항 대응·원척도 방향·결측 정책·산식·유효 n·대상 조건이 정의되고 S1 입력과 맞는지를 기술 검증한다. 자료 미수령/숫자 없음/틀린 문항·척도/파일 변조는 데이터 오류·기준 미준비로 표시하며 '승인 대기'로 표시하지 않는다. 없는 수치·교수 확인을 합성 승인으로 만들지 않는다.
6. 기존 confirmation/activation snapshot은 당시 기준 출처로 읽되 재승인을 요구하지 않는다. 새 기준 사용중단은 새 계산에서 선택 제외하고 과거 발급 bytes는 그대로 읽을 수 있다. 과거 리포트 전체 다운로드를 현재 승인 철회만으로 막는 정책은 제거한다. 실제 기준 손상·파일 유실은 기술 오류로 분리한다.
7. 자기 집단 n·중복 제거·유효 설문 분모·정답 독립성은 유지한다. 원 평가자 본인의 제출 전 타 결과/AI 노출과 그 이후 해당 평가자의 수정본, 타인이 편집해 만든 새 판본에 AR03의 사실 기록을 반영한다. 최초 독립 제출 뒤 제3자가 그 원자료를 단순 열람한 것은 원 평가자의 사전 노출이 아니며 최초 독립 제출본의 분모/분류/bytes를 소급 변경하지 않는다. 후속 편집본과 최초 독립본을 구별해 export/benchmark가 고른 정확한 revision으로 판단한다.
8. reference-based domain의 'approved 상태만 출력 가능' validator/ReportProfile 상태/renderer 경고/API literal을 함께 바꾼다. 옛 불변 문서의 과거 상태를 읽는 parser를 최소 유지하고 새로운 문서를 과거 승인 형식으로 위장하지 않는다.

수정 전 graft callers `exports_v4.guard`, `opinions_v4.selected_basic`, `disclosures_v4.require`, `comparisons_v4.gate`, `external_comparisons_v4.for_output`의 전체 호출 영향을 확인한다. API 응답·HTML/PDF·CSV/XLSX·report stage/worker·benchmark/usage까지 대조한다.

## 3 검증과 인수

A가 검수 source/export/report/집단을 생성, B가 즉시 목록·본문·다운로드·다음 출력 선택·수정/재생성 성공. 작성자 비활성·배정 취소·동의 미확인·삭제 flag·grant 없음은 차단 이유가 아니다. 실제 연결된 대상/판본이 다르면 기존 기술 오류를 반환한다.

일반 계정이 합성 기준 정의를 저장/적용하고 별도 confirm/activate 승인 없이 HTML/PDF/CSV/XLSX에 기대 수치를 출력한다. 같은 기준을 다른 사용자가 수정하면 새 판본이 생성되고 과거 파일 hash/열람은 유지된다. 기준 미수령·잘못된 척도는 수치를 만들지 않고 명확한 준비/오류 상태다.

독립성 인수는 두 경우를 함께 확인한다. A가 비노출 독립 제출한 뒤 B가 읽기만 하면 A 최초 판본의 독립 분모/분류/hash는 유지된다. A가 제출 전에 타 결과/AI를 보거나 B가 A 자료를 편집해 새 판본을 만들면 해당 후속 판본은 기록에 맞춰 구분하고 최초 A 독립본과 혼합하지 않는다. 실제 원 평가자의 노출 시각·저장 시각·선택 revision으로 판단하며 모든 열람/편집은 허용한다.

관련 `tests.test_validation_data_v4 tests.test_exports_v4 tests.test_comparisons_v4 tests.test_external_comparisons_v4 tests.test_external_exports_v4 tests.test_report_runs_v4 tests.test_report_validation_v4 tests.test_external_report_acceptance_v4`를 갱신/실행한다. 종전 403/승인 철회 download 차단 기대를 공유 허용+판본 추적으로 바꾼다. 변조·타 대상·유효 분모 회귀는 유지한다.

완료: 모든 자료 공유, 편집/재생성 가능, 관리자 결재·재승인 조건 없음, 실제 정의 기반 계산·불변 옛 출력·노출 분류 유지.

## 4 실패·복구

기준표 미수령을 이 PR 전체의 사용자 승인 재요청으로 바꾸지 않는다. 실제 수치 적용은 자료가 있어야 수행하며 자료 부재는 해당 기준만 미준비로 둔다. 합성 fixture 검증과 운영 기준 적용 완료는 별도 기록한다.
