# PR-GK04 Gemini 이중키 통합 인수와 운영

버전: v1.0 · 작성 2026-10-13 · 착수 2026-10-14 · 상태: 완료, [PR #98](https://github.com/syleeVeluga/k-dog-proj/pull/98) 병합 `43b3650` · 선행: GK03 #97 병합 `9cd4b93` · 브랜치: `veluga/gk04-gemini-fallback-acceptance`

상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md). 요구 GK-R12 및 GK-R01~R11 종단 회귀, 시험 GK-T20 및 GK-T01~T19 회귀. 제목 제안: `test: verify Gemini key fallback and document operations`.

## 1 결과와 범위

개발자 키 입력부터 실제 Worker·영상 채점·애착·최종본·리포트 문장·HTML/PDF·사용량·백업/복원까지 연결해 주키 장애 후 예비키 사용을 검증한다. fake transport를 실제 조립 경로에 연결하고 제품 인수·운영 인계의 근거를 남긴다. 기존 전체 시험을 통과했다는 이유로 실공급자 장애 회복·교수 품질·현장 실측을 완료 처리하지 않는다.

## 2 대상과 구현 순서

| 대상 | 필요한 작업 |
| --- | --- |
| GK01~03 신규 backend/frontend tests | 종단 시나리오·동시성/재시작/보안·기존 정책 회귀를 실제 구현 경로에서 확인 |
| `backend/tests/test_report_acceptance_v4.py` 등 실제 조립 시험 | 독립 원관찰/최종본/문장/발급 bytes 보호와 key fallback 연결. 기존 정상 fixture를 불필요하게 재작성하지 않음 |
| `docs/DEVELOPMENT.md`, `docs/PILOT_OPERATIONS.md` | 두 키 설정/시험·전환 조건·상한·슬롯 제거/전체 중지·재등록·콘솔 폐기·HTTPS/실행 계정 안내 |
| 이 폴더의 실행 기록 신설 후보 | `K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md`: PR/commit/실제 검증/triage/후속 |
| `scripts/build_release.py`, `scripts/verify_release.py` | 기존 allowlist가 계획/실행 문서를 포함하고 키를 제외하는지 확인. 필요할 때만 변경 |

1. GK01~03의 실제 병합 commit·시험/캡처·독립 검토 수용 결과와 미해결 발견을 확인한다. 계획에서 가정한 API/DTO와 실제 계약의 차이는 상위/PR 문서를 함께 갱신한다.
2. GK-T20: 합성 영상/사용자·fake transport로 주키 실패→예비키 원관찰→애착→최종본→리포트 문장→실제 HTML/PDF를 생성한다. 새 report run은 자기 주키부터 시작한다는 경계를 검증한다. score run에서 backup을 사용했다고 report run이 무조건 backup으로 시작하지 않게 한다.
3. 다른 프로젝트 역할의 업로드 URI/키를 분리한다. 주키 실패 attempt·예비키 성공 계량·primary의 uncertain/cleanup_pending을 함께 확인한다. 원자료/입력·고정 결과/옛 발급 bytes·명시 재사용 무호출을 검증한다.
4. worker 중단/재시작·예비키 전환 대기 중 actor/입력/lease 변경·마지막 예약 경쟁을 재현한다. 실패를 정상 결과로 게시하거나 부분 성공을 다시 호출하지 않는다.
5. 백업에서 두 ciphertext/원문/세션 부재를 확인한다. 별도 새 폴더 복원 후 과거 산출물을 읽을 수 있고 새 실행은 키 재등록이 필요함을 확인한다. 재등록된 키로 예비 전환을 수행해도 백업 이전 이력이 바뀌지 않는다. clean은 참조 보호 원칙을 유지하며 전체 DB purge를 실행하지 않는다.
6. 운영 문서에 「같은 Windows 실행 계정」·원격 접속 시 HTTPS·연결 시험과 모델/품질 인수의 차이·프로젝트 할당량 공유·app 제거와 공급자 키 취소의 차이·상한 부족·비용 미확인을 명시한다. 예비키 등록으로 비상 복구가 보장된다고 표현하지 않는다.
7. 전체 backend·frontend build/E2E, 필요한 S1 source 검사, 새 portable/online ZIP의 기존 설치 검증을 실행하고 실제 범위를 기록한다. 제품에 운영 키/환경 파일/참가자 영상을 넣지 않는다. ZIP 검증의 개발자 화면 접근403/허용과 두 슬롯 초기 미등록을 확인한다.

## 3 미래 검증 명령

구현 직전 공식 release/registry/API와 runtime/peer 호환·최신/선택 버전·선택 이유를 다시 기록한 뒤 기존 잠금 의존성을 사용한다. 새 의존성은 이번 계획의 전제 조건이 아니다.

```powershell
# backend/
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
# frontend/
npm ci
npm run build
npm run test:e2e
# 저장소 루트
git diff --check
graft build
graft check
```

S1 assets가 변경되거나 최종 통합 source 대조가 필요한 경우 고객 원본을 확보해 기록 hash를 확인한 뒤 backend에서 `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`를 수행한다. 이 기능은 평가 규칙/카탈로그 변경을 요구하지 않으며 원본 부재를 통과로 기록하지 않는다.

깨끗한 구현 commit에서 기존 [개발 안내](../../DEVELOPMENT.md)의 runtime/FFmpeg 준비와 release 절차를 따른다. 아래 ZIP 이름은 새 산출물 예시다.

```powershell
# 저장소 루트
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py releases/kdog-gk04-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py releases/kdog-gk04-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py --variant online releases/kdog-gk04-online-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py releases/kdog-gk04-online-windows-x64.zip
```

실제 제품 검증 명령이며 이 계획 작성 단계에서는 실행하지 않는다. 동일 전체 검사를 불필요하게 반복하지 않고 새 변경·실패·미해결 우려가 생긴 경우에만 재실행한다. 검증 패키지 생성과 고객 발행/배포·실운영 변경을 구분한다.

## 4 실공급자 후속과 완료 조건

기술 인수는 합성/fake transport로 완료할 수 있다. 실제 provider 인수는 승인된 시험 프로젝트/키·비식별 자료·비용 범위가 준비된 후 별도 실행 기록에 남긴다. 주키 모델 호출 불가/예비키 정상·서로 다른 프로젝트의 Files/inference/삭제·실제 계량·모델 품질을 확인한다. 장애/할당량 소진을 인위적으로 대량 호출해 만들지 않는다. 미실행이면 「실공급자 전환/품질 확인 대기」로 유지한다.

- [x] GK-T20 및 GK-T01~T19 실제 조립/보안·기존 S1/업무 접근/상태/불변 결과 회귀
- [x] 전체 backend·frontend build/E2E의 성공/실패/skip과 재검증 사유 기록
- [x] 백업/복원·원문/두 ciphertext 제외·재등록·정확한 원격 cleanup 인수
- [x] portable/online ZIP hash·설치/재시작·실제 Windows/HTTPS 검증 범위 기록
- [x] 운영 안내·공식 버전/API 근거·commit/PR/merge·독립 검토/triage·수용 수정 근거
- [x] 실제 공급자·품질/교수/현장 실측의 완료/대기 상태를 항목별로 인계
