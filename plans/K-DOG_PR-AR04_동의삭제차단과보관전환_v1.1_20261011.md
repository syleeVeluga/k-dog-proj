# K-DOG PR-AR04 동의·삭제 차단과 보관 전환

버전: v1.1 · 2026-10-11 · 상태: 상세 계획 / 제품 구현 미착수 · 선행: AR01·AR02
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.1_20261011.md). 조사 기준 `main / 7d0904e` (U08·U09 병합). 실제 착수 시 최신 호출 관계를 다시 확인한다.

## 1 목표·현재 근거

[Store.case](../backend/app/storage.py#L286-L294)뿐 아니라 api 목록/영상, uploads, capture_v4, preprocess_v4, run_v4, attachment_runs_v4, report_runs_v4, worker.once, comparisons_v4, external_comparisons_v4, exports_v4, validation_data_v4, forms_v4, intake, usage, progress_v4에 동의/삭제 판정이 퍼져 있다. 현재/고정 snapshot 양쪽 조건을 조사한다.

특히 [maintenance.clean](../backend/app/maintenance.py#L205-L277)은 purge_deleted=false에서도 연관 자료를 폐기하고 [restore](../backend/app/maintenance.py#L280-L337)는 현재 삭제대장을 재적용한 뒤 clean(purge_deleted=true)을 실행한다. UI/API만 지워서는 제거가 끝나지 않는다.

## 2 상세 변경

1. 참가자 동의 unknown/declined/confirmed 및 consent_confirmed boolean을 업무 입력 필수/목록/영상/분석/비교/export 제공 조건에서 제거한다. 기존 동의 값을 임의 confirmed로 바꾸지 않는다.
2. 삭제 요청 제품 API·버튼·상태, 사례 목록/검색의 deletion_requested 필터, identity 재등록 tombstone, forms source/validation source 재등록 금지를 제거한다. 과거 삭제 이력은 역사 기록으로 읽을 수 있으나 정책 판정에 사용하지 않는다.
3. worker claim/heartbeat/adopt/download/hash 후 재검사에서 동의·삭제와 자료 소유 조건만 제거한다. 실제 요청 actor의 세션/계정, stop·lease/token, 파일 hash·정확한 판본·동시 변경 검사는 유지한다. 실행 중 누군가 옛 flag를 바꿔도 새 실행이 삭제 중단으로 변하지 않는다.
4. comparisons/exports/validation에서 current/frozen manifest의 동의/삭제를 확인하지 않는다. ReferenceBinding.participation의 withdrawn/unknown도 참가자 상태만으로 자료 접근·비교 후보·연구 정답 분모를 자동 제외하는 조건에서는 제거한다. 실제 미관찰·사람 정답 미확정·AI 노출·판본 불일치 등 자료 자체의 유효성으로 분모를 정한다. 과거 참여 중단 원문은 보존하되 없는 정답을 만들어 포함하지 않는다.
5. clean/restore의 삭제 원장 재적용·연쇄 purge·deletion.record 기반 공유 결과 제거·Forms 파일 제거를 전부 제거한다. clean은 현재 참조 중인 원본·S1 결과·업무 audit를 보존하고 검증된 임시/실패 attempt의 고아파일만 기존 범위로 정리한다.
6. CLI --purge-deleted는 제거한다. 구 명령이 들어오면 삭제를 실행하지 않는 명확한 사용 오류를 반환한다. --actor는 인증/기록 식별로 검증하며 업무 역할 구분은 하지 않는다. API/worker/CLI/설치 자동 후처리 어디에도 대체 purge가 생기지 않는다.
7. remote provider 임시 파일 cleanup과 만료한 임시 수신 정리는 참가자 삭제 요청과 별개로 유지한다. 현 시트·영상·로그에 연결된 receipt 취소는 전체 참가자나 이미 연결된 참조를 연쇄 제거하지 않게 한다.
8. 기존 parser/DB의 consent/deletion 필드는 읽기 호환 metadata로 남길 수 있다. 새 정상 업무 DTO/응답은 이 상태를 작업 조건처럼 노출하지 않는다. old hash를 보존하고 일괄 점수 초기화/파일 재직렬화를 하지 않는다.

## 3 전환과 복원 계약

기존 offline 백업·앱 교체·검사로 진행한다. DB/불변 파일의 일괄 재작성, 새 정책 marker·전환 상태 머신·별도 서버 시작 차단·로그 이관 명령은 만들지 않는다.

1. 기존 절차대로 앱·worker 정지와 검증된 S1 백업·참조 검사를 수행한다.
2. 새 코드에서 옛 metadata를 접근/폐기 조건에 쓰지 않는다. 점수·영상·설문·옛 값·기존 event를 수정하지 않는다.
3. 현존 자료의 열람·실행과 clean의 hash/업무 기록 보존을 검증한다. 유실 파일은 유실로 표시하며 complete/ready로 조작하지 않는다.
4. 합성 백업 복원은 자료·기록 모두 백업 snapshot의 시점/내용과 일치해야 한다. 현재 DB의 백업 이후 event 추출·합병·actor FK 이관은 없다. 같은 백업의 반복 복원에서도 purge가 재실행되지 않아야 한다.

restore는 S1 초기화 이전 백업 거절·DB/FK/hash 검사·세션 초기화·offline·새 목적지 검사를 유지하고 삭제대장 재적용·연쇄 purge를 제거한다. [backup](../backend/app/maintenance.py#L162-L185)는 기존 DB snapshot에 `changes`를 포함한다. snapshot 이후 `backup.create` 사건이나 백업 이후 파일/결과/event까지 복원됐다고 표시하지 않는다. 같은 운영 DB에 옛 앱을 실행하지 않는 배포/복구 안내는 AR07에 적되 새 버전 차단 시스템은 만들지 않는다.

## 4 검증과 인수

합성 unknown/declined/confirmed×boolean false/true×deletion_requested 0/1 및 역사 대장 조합에서 목록→영상→전처리→AI→채점→리포트→비교→export 정상 동작을 검증한다. 자료를 실제 읽을 수 있다는 조건 외 옛 상태 때문에 후보가 빠지지 않아야 한다.

원본/결과/audit가 있는 백업과 이미 유실된 참조가 있는 fixture를 따로 사용한다. clean의 기본 모드, 옛 --purge-deleted 입력, restore 반복, 작업 중 옛 flag 변경, Forms 과거 tombstone/동일 source 재등록을 검증한다. 실제 hash 오류·잘못된 대상·lease 만료·stop은 기존대로 실패해야 한다.

관련 `tests.test_deletion_restore_v4 tests.test_settings tests.test_uploads_v4 tests.test_preprocess_v4 tests.test_run_v4 tests.test_forms_import_v4 tests.test_exports_v4`를 갱신해 실행한다. clean/restore의 실제 회귀는 기존 test_settings·test_deletion_restore_v4와 신규 정책 전환 시나리오로 확인한다. 삭제/동의만의 구 기대는 새 비차단+기록 보존 기대로 바꾸고 혼합 무결성 사례는 유지한다.

완료: 동의/삭제 판정이 모든 live/frozen/worker/CLI/복원 경로에서 업무와 보관에 영향 없음, 과거 메타데이터·원본·scores·audit 보존, 유실은 사실대로 표시.

## 5 실패·복구

전환 앱과 백업의 호환 확인 후 별도 경로로 복구한다. 이전 앱을 운영 DB에 덮어 설치하거나 deletion flag를 0으로 만들며 복구하는 우회는 사용하지 않는다. 실제 자료 제거는 이 PR의 동작에 포함하지 않는다.
