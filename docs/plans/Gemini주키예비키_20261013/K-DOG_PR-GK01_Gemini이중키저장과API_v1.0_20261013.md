# PR-GK01 Gemini 이중키 저장과 API

버전: v1.0 · 2026-10-13 · 상태: 구현·검증·독립 검토·수용 수정 완료, PR 병합 대기 · 선행: 계획 #94 병합 `ba8508f` · 브랜치: `veluga/gk01-gemini-key-slots`

상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md). 요구 GK-R01~R03, 시험 GK-T01~T06. 제목 제안: `feat: add protected Gemini primary and backup key slots`.

## 1 문제와 결과

현재 공급자당 한 개 키의 등록/교체만 가능하다. Gemini 주키와 예비키를 별도 DPAPI 슬롯으로 관리하고, 기존 주키와 환경 변수 사용 경계를 보존한다. 이 PR은 키 보관/관리 API를 완성하며 자동 실행 전환은 GK02에서 적용한다. GK03 전까지 기존 화면은 주키 기능으로 동작한다.

## 2 대상과 계약

| 대상 | 변경 |
| --- | --- |
| `backend/app/secrets.py` | primary/backup 최신 상태·credential 읽기·변경/시험. target gemini/gemini:backup, 활성 참조 집합과 원자적 전체 폐기 |
| `backend/app/settings.py`, `backend/app/api.py` | typed 슬롯 요청/응답·expected_reference·gemini_slots 상태·개발자 슬롯 API. 기존 provider API와 원문 미노출 유지 |
| `backend/app/maintenance.py` | 두 키 파일 백업 제외/복원 재등록 회귀. 실제 변경이 필요한 부분만 수정 |
| `backend/tests/test_settings.py` | 기존 권한·DPAPI·교체/폐기·동시성 회귀 |
| `backend/tests/test_gemini_key_slots.py` | 신설 후보: GK-T01~T06의 두 슬롯·API/보안 계약 |
| `frontend/tests/retirement-v4.spec.ts` | developer/settings의 정확한 keys-only 기대를 새 typed 확장 계약으로 수정 |

새 테이블·범용 다중 공급자 vault 프레임워크를 만들지 않는다. OpenAI/Anthropic의 키 동작/자료를 유지하고 그 공급자의 예비키 슬롯은 추가하지 않는다. 기존 ciphertext/reference는 주키로 그대로 사용한다.

후보 API와 폐기 의미는 [전체 계획 §3](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md#3-키-저장api-계약)을 따른다. 슬롯 변경은 기대 참조를 검사하고 409로 stale 편집을 거절한다. 기존 Gemini PUT/test는 주키, 기존 DELETE는 두 슬롯 전체 사용 중지다. 신규 슬롯 DELETE는 선택 슬롯만 제거한다. 전체 사용 중지는 두 폐기 상태를 한 DB 트랜잭션에서 확정한 뒤 파일을 정리한다.

## 3 구현 순서

1. Graft로 state/credential/change/connection_test와 reset_s1 정리 호출자를 다시 확인하고 기존 주키·환경 변수·다른 공급자 회귀를 고정한다.
2. 슬롯을 두 literal로 제한하고 기존 changes 기록에 두 target을 사용한다. 원문 없는 작은 상태 모델과 로컬 미가용 사유를 정의한다. arbitrary ref/path 복호화 API를 만들지 않는다.
3. 같은 write fence에서 기대 참조·현재 developer 활성/권한·다른 슬롯의 활성 참조를 확인한다. 새 파일 fsync 후 감사 commit, commit된 활성 참조 밖의 retired ciphertext만 정리한다. cleanup 실패가 폐기를 취소하거나 다른 슬롯을 삭제하지 않게 한다.
4. 키 중복을 복호화된 활성 값과 일시 비교해 거절한다. 값·키 hash를 DB/로그에 저장하지 않는다. 예비키 미등록 또는 다른 Windows 계정 복호화 실패를 정상 연결로 표시하지 않는다.
5. 등록 시험은 지정 슬롯만 호출한다. 실패해도 다른 슬롯을 시험하지 않는다. 모델 목록 조회 성공을 평가 성공으로 표시하지 않고 slot/reference/시각을 기록한다. 시험 중 교체되면 새 슬롯의 성공으로 잘못 연결하지 않는다.
6. SecretStr·길이 제한·Host/Origin·developer 접근·validation 오류 미반사·no-store를 유지한다. 백업에 두 ciphertext/세션이 없고 복원 뒤 명시 재등록이 필요한지 검증한다.

## 4 인수와 명령

- GK-T01: 기존 주키 파일/reference 불변·등록 이력 없는 환경 변수 주키·예비키 없음.
- GK-T02/03: 두 암호문 원문 부재·독립 교체·슬롯 제거·전체 폐기·실패한 unlink·환경 변수 부활 금지·명시 재등록.
- GK-T04: 익명/세 일반 역할/비활성 developer/교차 Origin·Host 및 짧음/김/잘못된 자료형 오류에서 원문 부재.
- GK-T05: primary와 backup 동시 등록/교체·worker 읽기·stale 기대 참조409·중복 원문 거절·현재 파일 보존.
- GK-T06: 각 슬롯의 연결 시험·교체 중 시험 결과 고정·원문 없는 감사·옛 성공 상태 비승계.

아래는 구현 후 실행할 명령이다. 신설 후보 모듈은 현재 존재/통과한다고 표시하지 않는다.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest -v tests.test_settings tests.test_gemini_key_slots
# frontend/
npm run build
npm run test:e2e -- tests/settings.spec.ts tests/retirement-v4.spec.ts
# 저장소 루트
git diff --check
graft check
```

시험은 임시 Store·합성 키·가짜 transport를 사용한다. DPAPI 실제 검증은 Windows에서 실행하며 타 OS skip을 통과로 세지 않는다. 실제 운영 키를 읽거나 공급자 연결 시험을 자동 실행하지 않는다.

## 5 인계와 완료 조건

GK02에 두 슬롯 상태/로컬 미가용 사유·정확한 활성 reference 조회·원자 폐기·회전 경계·API/시험 경로를 인계한다. 키 선택 후 시작한 attempt의 기존 원문을 중간에 바꾸지 않는 의미를 명시한다. GK01만 병합된 상태에서는 자동 전환이 아직 없다는 운영 경계를 유지한다.

- [x] 기존·두 슬롯 API/DPAPI/백업/동시성 회귀와 문서 링크/whitespace 통과
- [x] 공식 최신/선택 의존성·API 확인일/출처/유지 이유 기록
- [x] 독립 cold review·triage·수용 수정/재검증
- [ ] 구현 commit/PR/병합·GK02 인계 기록

## 6 2026-10-13 구현 기록

실제 구현·지정 시험·백업/복원·독립 검토 수용 수정은 [구현 실행 기록](K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md#gk01-이중키-저장api)을 따른다. 수용 수정 후 관련 26개가 통과했고 reviewer가 두 발견 해결과 신규 결함0을 확인했다. 병합 완료는 실제 PR 기록으로 확정한다.
