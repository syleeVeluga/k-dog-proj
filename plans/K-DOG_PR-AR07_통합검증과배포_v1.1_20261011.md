# K-DOG PR-AR07 통합 검증과 배포

버전: v1.1 · 2026-10-11 · 상태: 구현·전체 검증·독립 cold review·수용 수정·문서 완료 / 병합 대기 (2026-10-12) · 선행: AR01~AR06
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.1_20261011.md). 조사 기준 `main / 7d0904e` (U08·U09 병합). 실제 착수 시 최신 호출 관계를 다시 확인한다.

## 1 목표와 통합 범위

상위 AR-R01~R12의 최종 상태를 하나의 릴리스로 검증한다. 계획 작성·문서 병합, 제품 코드 완료, 합성 종단, 실제 공급자/현장 검증을 구별한다. U08의 리포트 기록·U09의 라벨/짧은 ID/화면 폭 개선은 재사용 검증 기준이며 권한 단순화 완료 근거는 아니다.

## 2 잔존 검사

graft find_all로 role/manager/owner/assigned_username/score_grants/viewer_sheet_id/403, consent_confirmed/consents/declined/deletion_requested/deletion.record/purge/withdrawn, approval/approved/activate/confirmation을 backend/frontend/scripts 전역 검색한다. 경로마다 '제거', '과거 metadata 읽기', '개발자 설정', '로그인 식별', '자료 기술 검증/출처'로 분류한 근거표를 남긴다. 문자열 잔존 0만으로 완료하지 않는다. 실제 호출 관계와 live/frozen/worker/download/restore 효과를 확인한다.

계정 비활성/세션 만료는 요청 actor 인증만 제한한다. 작성자 비활성·배정 취소·동의 상태·삭제 flag로 타 사용자의 자료가 막히는 경로는 0개다. AR-R05의 연구 정답 분류와 의견/기준 사용중단은 접근 허가로 다시 연결하지 않는다.

## 3 필수 검증

1. backend 전체: `uv run --locked python -X utf8 -m unittest discover -s tests -v`.
2. S1 추출: `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`. 실제 원본 없는 검사·역사 v3 skip는 별도 표기한다.
3. frontend: `npm run build`, `npm run test:e2e`. A/B/개발자 대표 공통 업무·교차 편집·미제출 시트의 즉시 리포트 열람·동의 없는 Forms 입력·대상별 최근 기록·동시 편집을 확인한다. 역할 조합의 API 동등성은 backend에서 검사해 UI의 같은 흐름을 불필요하게 4번 복제하지 않는다. U09 이름·짧은 ID·중간 폭 회귀를 유지한다.
4. 합성 백업/복원에서 source·S1 score·report·export·changes를 backup snapshot과 대조한다. clean의 기존 사건 보존, 삭제대장 purge 없음, 백업 이후 사건이 복원됐다는 허위 주장 없음, 유실 자료 허위 복구 없음. 폴링·Range·기록 조회의 사건 폭증과 기존 event 중복이 없어야 한다.
5. worker 응답 유실/재사용/lease/stop/과금 미확인·최대 호출 예산·input pin 회귀와 개발자 설정 우회 방지.
6. scripts/build_release·issue_release·windows installer·verify_release의 현재 CLI로 ZIP 설치·기존 자료 경로 재설치·공통 계정 업무·개발자 설정을 검증한다. 기존 bootstrap/`--admin` 문자열 호환은 유지 가능하며 새 정책 marker/전환 서버/로그 병합 도구는 만들지 않는다. 기존 잠금 의존성을 유지하고 최신판 확인·호환 근거를 기록한다.
7. `git diff --check`, 문서/이미지 committed 링크 검사, 릴리스에 고객 원본·키·운영 로그·실자료 없는지 확인.

계획 작성 시점(2026-10-11)에 제시한 명령은 미래 실행 계획이었으며 당시 문서 작업에서 앱 시험이나 ZIP 검증을 수행하지 않았다. 2026-10-12 실제 명령·통과/skip/실패·수정 후 재검증·commit/hash는 [구현 실행 기록 §10](K-DOG_업무권한구현실행기록_v1.0_20261011.md#10-ar07-통합검증과릴리스)에 기록한다.

## 4 기준·운영 문서 갱신

[AGENTS](../AGENTS.md)의 'deletion state re-check'·소유/배정 보호 문구, [개발 안내](../docs/DEVELOPMENT.md), [운영 안내](../docs/PILOT_OPERATIONS.md), [확인사항](../docs/개발반영_20261003/K-DOG_확인사항과적용경계_v1.0_20261003.md), [요구사항 추적표](../docs/개발반영_20261003/K-DOG_요구사항추적표_v1.0_20261003.md), [인수 대장](../docs/개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md), 리포트 개편의 공통 정책과 UIUX 현재 안내를 새 결정을 우선하는 현행 규칙으로 갱신한다.

과거 구현·시험 통과 사실은 날짜·기준판을 유지한다. 삭제/권한 차단을 검증한 옛 시험을 현재 인수 성공 근거로 재사용하지 않는다. 운영 안내는 로그인→자료 작업→기록 조회로 작성하고 동의 확인·배정·공개 허용·재개방·매 발급 승인·삭제 요청 실행 지침을 현행 작업 순서에서 제거한다.

## 5 cold review·배포·복구

독립 reviewer가 사용자 새 결정과 실제 최종 diff/인수 기록을 직접 읽어 잔존 차단·누락 기록·가짜 독립성·옛 purge 재발·불변 bytes 재작성·설정 승격을 검토한다. 발견별 수용/보류/거절·근거를 적고 수용 건만 수정한다. 최종 관련 회귀 후 PR head/check/mergeable을 확인해 해당 commit을 병합한다.

기존 배포 절차대로 검증된 S1 백업, 앱/worker 정지, 통합 릴리스 설치, smoke test, 대상별 기록 확인 순서로 전환한다. 제품 자료 초기화/삭제·유료 공급자 호출은 자동 실행하지 않는다. 같은 운영 DB에 옛 삭제정책 앱을 다시 실행하지 않는 안내를 남기고 실패 복구는 격리된 백업+호환 앱으로 한다. 별도 downgrade 차단 시스템을 신설하지 않는다.

완료: AR01~AR06 구현 병합·전체 검증·수용 수정·설치/복원 증거·문서 정합성·최종 PR/릴리스 근거 모두 기록. 실제 provider 품질·교수 판단 적절성·물리 3PC 실측은 기존 후속 대장에 사실대로 남기며 권한 승인 절차로 다시 확장하지 않는다.


## 6 실제 완료 체크

- [x] AR01~AR06 구현·검증·독립 검토·수용 수정·문서·PR #75~#80 병합.
- [x] 잔존 조건 exhaustive 분류·실제 retry actor 수정·원본/고정 bytes 보존.
- [x] backend 전체723개: 721통과·역사 원본 부재2skip, 1195.231초.
- [x] frontend build·전체 E2E112개 통과(7.6분), S1 source/hash 검사 통과.
- [x] 12상태 원자료/점수/PDF/export/changes backup snapshot·반복 restore·유실 진실성 검증.
- [x] 실제 포터블/온라인 ZIP 설치·sealed 발행·일반 설정403·개발자 업무·재설치 보존.
- [x] 독립 cold review P2 수용·204 수정·조회 대기 검토·설치/hash/문서 대조, 추가 actionable0.
- [x] 현행 기준·운영·추적/인수·리포트/UIUX 정책·실행 기록 갱신, 링크/차이/그래프 확인.
- [ ] 최종 PR head·mergeable 확인 및 실제 병합 SHA 기록.

실제 결과·수정 이력·검증판 ZIP hash는 [실행 기록 §10](K-DOG_업무권한구현실행기록_v1.0_20261011.md#10-ar07-통합검증과릴리스)에서 확인한다. Windows 격리 경로 설치까지 인수했으며 실제 운영 DB 전환·유료 호출·물리3PC는 이번 실행 범위로 표시하지 않는다.
