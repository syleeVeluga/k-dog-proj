# K-DOG PR-AR03 공유 채점과 해석

버전: v1.1 · 2026-10-11 · 상태: 구현·검증·독립 cold review·수용 수정·문서 완료 / PR #77 병합 완료 · 선행: AR01·AR02
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.1_20261011.md). 조사 기준 `main / 7d0904e` (U08·U09 병합). 실제 착수 시 최신 호출 관계를 다시 확인한다.

## 1 목표·현재 근거

[owner/manager](../backend/app/sheets_v4.py#L26-L38), [목록 필터](../backend/app/sheets_v4.py#L223-L264), [revise/grant](../backend/app/sheets_v4.py#L495-L613), [opinions.selected_basic](../backend/app/opinions_v4.py#L100-L122), [disclosures.require/reveal](../backend/app/disclosures_v4.py#L59-L131), [judgements](../backend/app/judgements_v4.py), [final_results](../backend/app/final_results_v4.py), [attachment_runs](../backend/app/attachment_runs_v4.py)를 함께 바꾼다. U08의 `report_reader/context(read=True)`는 교수 읽기를 넓혔지만 본인 제출 시트·명시 공개·편집 제한은 남아 있다.

## 2 상세 변경

1. 본인 assigned_username·active 배정 여부·현재 소유 계정 role은 조회/수정/기본 결과 선택 조건에서 제거한다. 배정 없이 사용자가 채점 생성/시작할 수 있다. 평가자 정보는 원본 출처로 선택/표시할 수 있으나 업무 권한이 아니다.
2. 모든 시트의 현재/보존 판본을 조회하고 편집한다. 제출본 수정은 자동으로 새 draft revision을 만들어 저장하는 기존 revision 흐름으로 구현한다. 원본과 initial_submission은 보존한다. 승인·재개방 요청/manager-only endpoint는 제거하거나 공통 수정 동작으로 통합한다.
3. 타 평가/AI/기본 결과/의견/최종/리포트 해석을 제출 여부와 무관하게 바로 열 수 있다. score_grants·viewer_sheet_id·명시 reveal을 접근 조건에서 제거하고 과거 자료에서의 출처/노출 기록으로만 읽는다.
4. 타인 결과를 보기 위해 본인 시트를 먼저 생성하거나 제출해야 하는 조건을 없앤다. 명시 결과 열기는 AR02의 actor·시각·대상·필요한 판본 연결 1건으로 남긴다. 별도 공개 확인·노출 event 플랫폼·모든 영상 hash를 붙이는 추론 시스템은 만들지 않는다.
5. 최초 독립 제출본·기존 노출 이력·후속 수정 판본의 분석 의미를 유지한다. 원평가자의 사전 타 결과/AI 열람을 기록으로 확인한 경우 그 사실을 제공하되, 자료를 읽기만 했다는 이유로 시트 revision·purpose·initial_submission을 자동 변경하지 않는다. 제3자의 후행 열람으로 최초 독립본을 소급 바꾸지 않는다. 알 수 없는 과거 사실을 새 로그로 만들어 채우지 않는다.
6. original rater_id/rater_kind와 실제 저장 actor를 분리한다. AI 생성 원본 bytes는 그대로 두고 AI 결과의 사람 수정도 편집 기능으로 제공하되 새 수동 수정 판본/출처를 남겨 AI 최초 출력으로 오인하지 않게 한다. 해당 판본의 계산/최종/내보내기 연결을 함께 검증한다.
7. opinions save/reopen/withdraw, judgement 선택, final assemble, attachment 실행은 모든 업무 계정이 수행한다. 의견 withdrawn은 의견 판본의 사용 중단 사실로 보존하되 참가자 철회나 접근 차단으로 해석하지 않는다. 과거 의견도 읽고 새 의견으로 편집/재작성할 수 있다.
8. 같은 대상·회차·고정 입력/근거·원칙에 맞는 결과 선택, observation 범위, 필수 값/결측 검증, optimistic revision 충돌은 유지한다. 다른 사람의 시트라는 이유의 403은 없어야 한다.

수정 전 graft callers owner/manager/selected_basic/disclosures.require를 확인하고 basic_candidates의 403 후보 은폐, judgements.guard, report._source_access, exports._sheet까지 AR05 인계 목록에 넣는다. 과거 score_grants 읽기는 옛 bytes/history를 해석하는 데 필요한 부분만 남기고 운영 grant 경로는 제거한다.

## 3 화면과 API

채점 목록에서 '내 채점'을 강제 기본 화면으로 쓰지 않는다. 작성자/평가자 필터는 선택 사항이다. '채점 시작', '저장', '제출본 수정', '이전 판본', '기록'으로 작업하며 배정·공개 허용·재개방 승인 버튼은 제거한다. 타 결과 열기는 바로 제공하고 서버가 노출을 기록한다. 실제 단계/불완전 입력은 명확히 표시한다.

## 4 검증과 인수

A 시트를 B가 조회/편집/제출·다시 수정하고 C가 배정/시트/제출 없이 타결과를 열며 D가 최종 결과를 구성하는 실제 API 회귀를 작성한다. 소유자 비활성/옛 배정 active false/score_grants 없음에도 정상이어야 한다. AI를 사람이 편집한 결과의 actor·출처와 최초 AI bytes를 함께 확인한다.

관련 `tests.test_sheets_v4 tests.test_judgements_v4 tests.test_opinions_v4 tests.test_final_results_v4 tests.test_disclosures_v4 tests.test_attachment_ai_v4`를 갱신해 실행한다. 기존 '타평가 403', 'grant 필수', '운영자 재개방' 기대값은 허용+정확한 이력 기대값으로 바꾼다. 제거한 API만 확인하고 회귀를 없애지 않는다. UI는 scoring/opinions 관련 E2E와 동시 편집 409·미저장 입력 보존을 확인한다.

완료: 배정 없이 생성·공유 편집·바로 열람, 승인 단계 0개, 노출 분류 정확, 최초 제출/AI 원본 보존, 충돌/변조 보호 유지.

## 5 실패·복구

과거 시트·grants·exposures를 일괄 새 내용으로 쓰지 않는다. 새 기록을 앞의 판본에 연결해 소유자가 다르다는 이유 없이 추적한다. 독립성 불명확을 독립 정답으로 자동 승격하는 복구는 하지 않는다.

## 6 구현 실행 근거

2026-10-11~12에 `veluga/ar03-shared-scoring`에서 구현했다. [실행 기록](K-DOG_업무권한구현실행기록_v1.0_20261011.md#6-ar03-공유-채점과-해석)은 검증·수용 판단·최종 PR을 기록한다. 배정/공개 승인/재개방 API를 제거하고 제출본 저장을 새 초안 판본으로 연결했다. 최초 제출본·AI 원본·원평가자와 실제 수정 actor를 보존한다. 소유 계정 비활성·옛 배정 상태는 공통 접근을 막지 않으며 파일/입력/ref/hash와 revision 충돌 검사는 유지한다.

AR05 인계: `exports_v4._sheet`의 viewer/grant 접근, export/validation/cohort 본문 소유 제한, `report_runs_v4._source_access`의 자기 제출·교수 발급본 특수 경로와 발급/다운로드 공통화. AR04 인계: `_case`·Worker·첨부 해석의 동의/삭제 차단. AR03의 공유 채점 완료를 이 후속 범위 완료로 표시하지 않는다.
