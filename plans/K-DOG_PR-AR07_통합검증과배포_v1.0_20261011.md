# K-DOG PR-AR07 통합 검증과 배포

버전: v1.0 · 2026-10-11 · 상태: 상세 계획 / 제품 구현 미착수 · 선행: AR01~AR06
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.0_20261011.md). 조사 기준 `d6dd58a`; 진행 중인 로컬 U08 수정은 제외한다. 실제 착수 시 최신 병합 코드의 호출 관계를 다시 확인한다.

## 1 목표와 통합 범위

상위 AR-R01~R12의 최종 상태를 하나의 릴리스로 검증한다. 계획 작성·문서 병합, 제품 코드 완료, 합성 종단, 실제 공급자/현장 검증을 구별한다. 진행 중 U08 코드의 수용 여부는 최종 동작 대조로만 처리하고 이번 계획 검증 근거에 포함하지 않는다.

## 2 잔존 검사

graft find_all로 role/manager/owner/assigned_username/score_grants/viewer_sheet_id/403, consent_confirmed/consents/declined/deletion_requested/deletion.record/purge/withdrawn, approval/approved/activate/confirmation을 backend/frontend/scripts 전역 검색한다. 경로마다 '제거', '과거 metadata 읽기', '개발자 설정', '로그인 식별', '자료 기술 검증/출처'로 분류한 근거표를 남긴다. 문자열 잔존 0만으로 완료하지 않는다. 실제 호출 관계와 live/frozen/worker/download/restore 효과를 확인한다.

계정 비활성/세션 만료는 요청 actor 인증만 제한한다. 작성자 비활성·배정 취소·동의 상태·삭제 flag로 타 사용자의 자료가 막히는 경로는 0개다. AR-R05의 연구 정답 분류와 의견/기준 사용중단은 접근 허가로 다시 연결하지 않는다.

## 3 필수 검증

1. backend 전체: `uv run --locked python -X utf8 -m unittest discover -s tests -v`.
2. S1 추출: `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`. 실제 원본 없는 검사·역사 v3 skip는 별도 표기한다.
3. frontend: `npm run build`, `npm run test:e2e`. 신규 계정별 공통업무·소유자 교차·즉시 열람·동의 없는 Forms 입력·공통 기록 조회·동시 편집 시나리오 포함.
4. 운영 백업/복원은 참가자 없는 합성 저장소에서 source·S1 score·report·export·audit hash/개수를 검사한다. 옛 삭제대장이 있어도 clean/restore에 purge 없음, 유실 자료 허위 복구 없음.
5. worker 응답 유실/재사용/lease/stop/과금 미확인·최대 호출 예산·input pin 회귀와 개발자 설정 우회 방지.
6. scripts/build_release·issue_release·windows installer·verify_release의 실제 현재 CLI를 확인해 새 ZIP 설치/계정·기존 자료 경로 재설치·새 정책 marker/앱 호환을 검증한다. 기존 잠금 의존성 유지, 최신판 확인·호환 근거를 구현 실행 기록에 적는다.
7. `git diff --check`, 문서/이미지 committed 링크 검사, 릴리스에 고객 원본·키·운영 로그·실자료 없는지 확인.

현재 미리 제시하는 명령은 미래 실행 계획이다. 이번 문서 작업에서 앱 시험이나 ZIP 검증을 수행한 것으로 적지 않는다. 실제 명령·통과/skip/실패·수정 후 재검증·commit/hash를 인수 대장에 남긴다.

## 4 기준·운영 문서 갱신

[AGENTS](../AGENTS.md)의 'deletion state re-check'·소유/배정 보호 문구, [개발 안내](../docs/DEVELOPMENT.md), [운영 안내](../docs/PILOT_OPERATIONS.md), [확인사항](../docs/개발반영_20261003/K-DOG_확인사항과적용경계_v1.0_20261003.md), [요구사항 추적표](../docs/개발반영_20261003/K-DOG_요구사항추적표_v1.0_20261003.md), [인수 대장](../docs/개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md), 리포트 개편의 공통 정책과 UIUX 현재 안내를 새 결정을 우선하는 현행 규칙으로 갱신한다.

과거 구현·시험 통과 사실은 날짜·기준판을 유지한다. 삭제/권한 차단을 검증한 옛 시험을 현재 인수 성공 근거로 재사용하지 않는다. 운영 안내는 로그인→자료 작업→기록 조회로 작성하고 동의 확인·배정·공개 허용·재개방·매 발급 승인·삭제 요청 실행 지침을 현행 작업 순서에서 제거한다.

## 5 cold review·배포·복구

독립 reviewer가 사용자 새 결정과 실제 최종 diff/인수 기록을 직접 읽어 잔존 차단·누락 기록·가짜 독립성·옛 purge 재발·불변 bytes 재작성·설정 승격을 검토한다. 발견별 수용/보류/거절·근거를 적고 수용 건만 수정한다. 최종 관련 회귀 후 PR head/check/mergeable을 확인해 해당 commit을 병합한다.

배포 전 검증된 S1 백업, 앱 정지, marker/호환 검사, 새 통합 릴리스 설치, smoke test, 기록 조회 순서로 전환한다. 제품 자료의 실제 초기화/삭제나 유료 공급자 호출은 이 계획의 자동 동작이 아니다. 새 정책 이후 옛 앱 재실행은 명확히 거절하고 지원되는 복구는 격리된 백업+호환 앱으로 한다.

완료: AR01~AR06 구현 병합·전체 검증·수용 수정·설치/복원 증거·문서 정합성·최종 PR/릴리스 근거 모두 기록. 실제 provider 품질·교수 판단 적절성·물리 3PC 실측은 기존 후속 대장에 사실대로 남기며 권한 승인 절차로 다시 확장하지 않는다.
