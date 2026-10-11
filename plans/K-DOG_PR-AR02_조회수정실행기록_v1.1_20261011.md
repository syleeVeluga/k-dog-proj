# K-DOG PR-AR02 조회·수정·실행 기록

버전: v1.1 · 2026-10-11 · 상태: 구현·검증·독립 cold review·수용 수정·문서 완료 / PR #76 병합 완료 · 선행: AR01 (PR #75 병합 완료)
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.1_20261011.md). 조사 기준 `main / 7d0904e` (U08·U09 병합). 실제 착수 시 최신 호출 관계를 다시 확인한다.

실행 근거: [업무 권한 구현 실행 기록](K-DOG_업무권한구현실행기록_v1.0_20261011.md). 아래는 원계획이며 구현·검증·수용 판단은 실행 기록을 따른다.

## 1 목표·현재 근거

[changes 테이블](../backend/app/storage.py#L77-L82), [Store.audit](../backend/app/storage.py#L330-L332)는 change_id/actor/서버 시각/target/action/detail을 이미 저장한다. U08의 [리포트 access_log](../backend/app/report_runs_v4.py#L122-L137), [download](../backend/app/report_runs_v4.py#L861-L870)는 생성·발급·중지·재시도·열람을 재사용해 화면에 표시하며 자동 manifest 조회는 기록하지 않는다. [일반 자료](../backend/app/api.py), [영상](../backend/app/api.py), [시트](../backend/app/sheets_v4.py#L238-L264), [export](../backend/app/exports_v4.py), [참고자료](../backend/app/validation_data_v4.py)는 같은 최소 패턴으로 실제 누락된 사건만 보완한다.

## 2 최소 기록 계약

사용자 구분에 필요한 최소 기록만 남긴다. `changes`와 `Store.audit`, 기존 업무 action을 재사용한다. 새 DB/필수 event 스키마/메시지 브로커는 없다.

| 행위 | 필수 기록 |
| --- | --- |
| 주요 자료 명시 상세/본문 열기 | actor·서버 시각·target·action, 판본 구분에 필요한 session/revision만 |
| 성공한 저장·제출·최종 구성·계정/기준 변경 | 기존 변경 event의 실제 actor·대상·기존 판본 연결; 이미 있으면 추가하지 않음 |
| 실행 요청·중지·재시도·발급 | 기존 run 대상 action 재사용; 입력/설정/실행 결과는 기존 run 자료로 연결 |
| 파일 제공(html/pdf/csv/xlsx/manifest) | 실제 요청 actor·대상·format; U08 `report.s1.open` 재사용 |

정확한 판본은 sheet+revision 또는 불변 run/export/reference ID와 기존 참조로 찾는다. 모든 하위 ref/hash·변경 원문·변경 필드 diff·성공 상태를 모든 event에 복제하지 않는다. 키·비밀번호·세션 token·개인정보 원문·영상 bytes는 기록하지 않는다. 기록은 서버가 자료 제공/저장을 수행한 사실이며 실제 읽음·인쇄 완료를 증명하지 않는다. 열람 전 사유·서명·확인은 없다.

## 3 상세 구현

1. 기존 저장·실행·발급 action의 actor와 transaction을 점검한다. 실제 누락한 저장 사건만 같은 DB transaction에 보완한다. 기록 insert 실패에 성공 저장을 반환하지 않으며 새 실패 사건 로그는 추가하지 않는다.
2. 주요 자료 명시 상세 열기는 인증 actor와 실제 대상/판본을 서버에서 확인한 후 `.open` 한 번을 기록한다. 같은 endpoint의 자동 갱신과 구분이 필요한 경우에만 U08 `purpose=open`과 같은 작은 표식을 재사용한다. 클라이언트 username/시각은 신뢰하지 않는다.
3. 영상은 사용자의 「영상 열기」 동작을 1건으로 남기며 반복 Range/seek/preload 요청은 제외한다. 목록·검색·탭 이동·폴링·heartbeat·자동 manifest·기록 조회는 제외한다. 새 조회 request ID/중복 방지 DB/세션 단위 읽음 집계를 만들지 않는다. 개별 재열기/파일 요청은 개별 제공 사실로 남는다.
4. 읽기만으로 시트/document revision·purpose·result hash를 바꾸지 않는다. AR03이 필요한 판본의 노출 사실을 볼 때 이 기록을 재사용하며 별도 공개 승인/중복 노출 event를 추가하지 않는다.
5. 참가자/자료 상세에서 관련 target의 최근 기록을 기존 접기 패턴으로 읽는다. 모든 업무 계정이 조회할 수 있고 고정 시간 정렬·제한된 페이지/더 보기만 둔다. 전역 감사 메뉴·기간/actor/action 다중 검색·로그 export·event 수정/삭제 UI는 없다.
6. 과거 `changes`와 target 문자열은 보존한다. clean은 기존 업무 기록을 지우지 않는다. backup/restore는 기존 DB snapshot에 포함된 자료·기록을 같은 시점으로 복원한다. 백업 이후 원 DB 기록의 추출/합병·새 actor FK 전환·사건 재실행은 하지 않는다(AR04).
7. 접수/설문/촬영/영상/채점/의견/최종/리포트/검수/export/계정/기준의 기존 action과 주요 열기 경로만 작은 대응표로 확인한다. worker 단계 완료·설정 조회·백업 진행 로그까지 새로운 사건으로 확장하지 않는다.

리포트 생성·발급·중지·재시도·파일 제공은 U08의 기존 event 1건을 그대로 쓴다. UI를 열었거나 기록이 추가됐다는 이유로 같은 동작의 새 공통 event를 추가하지 않는다.

## 4 검증과 인수

합성 A 저장→B 상세/영상/시트 열기→C 실행→D 발급/파일 요청을 API로 연결해 실제 actor·시각·대상·필요한 판본을 확인한다. 기존 수정/리포트 event 중복 없음, 목록/폴링 10회·영상 Range 반복에도 open 증가 없음, 개별 재열기 기록, 실패 저장의 성공 event 없음, audit insert 실패에 자료 채택 없음, 실제 편집자와 원평가자 분리를 검증한다.

기존 API/sheets/run/report/export tests에 실제 변경 경로 회귀를 추가한다. 신규 `tests.test_activity_v4`는 공통 조회 계약을 기존 시험에서 다루기 어려운 경우에만 만든다(현재 존재·통과를 뜻하지 않음). AR06 대상별 기록 E2E와 AR07 백업 snapshot의 사건 보존을 확인한다.

완료: 주요 열람/저장/실행/파일 제공의 실제 사용자가 대상별 이력에서 확인됨. 기존 event 중복·폴링 로그·새 승인·불필요한 감사 도구·비밀 노출·문서 revision 오염 없음.

## 5 실패·복구

기존 changes event는 소급 변환·삭제하지 않는다. 새 상세 필드는 선택적이며 옛 event는 당시 정보만 표시한다. 실사용 로그를 fixture나 공개 저장소에 넣지 않는다.
