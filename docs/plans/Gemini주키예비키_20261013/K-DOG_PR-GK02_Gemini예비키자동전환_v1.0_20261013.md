# PR-GK02 Gemini 예비키 자동 전환

버전: v1.0 · 작성 2026-10-13 · 구현/검토 2026-10-14 · 상태: 구현·검증·독립 검토 완료, PR 병합 대기 · 선행: GK01 #95 병합 `7fad053` · 브랜치: `veluga/gk02-gemini-key-fallback`

상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md). 요구 GK-R04~R09, 시험 GK-T07~T16. 제목 제안: `feat: fail over Gemini execution to the backup key`.

## 1 문제와 결과

현재 scorer는 주키 한 개만 사용하고 Worker는 같은 설정의 attempt를 재시도한다. 주키의 credential/프로젝트 문제 또는 정해진 일시 장애를 만나면 예비키로 자동 이어간다. **예비키 추론도 별도 attempt·예약·계량으로 남기고, 기존 총 상한과 불변 산출물 보호를 유지**한다. 원관찰·애착 통합/독립 실행·리포트 문장 중 한 경로도 누락하지 않는다.

## 2 대상 파일

| 대상 | 변경 |
| --- | --- |
| `backend/app/gemini.py` | 원문 제거 후 HTTP 상태·Interactions code·확인한 legacy 인증 reason 보존, 작업 단계별 전환 대상 판별에 필요한 최소 정보 |
| `backend/app/secrets.py`, `backend/app/gemini_v4.py` | 현재 활성 슬롯 선택·attempt 동안 같은 키·작업 단계/slot/reference 기록·재업로드와 정리 |
| `backend/app/worker.py` | 현재 실행의 전환 상태 확인·내구성 기록, 기존 다음 attempt/retry_wait 예약/guard와 연동 |
| `backend/app/scoring_ai_v4.py`, `backend/app/attachment_ai_v4.py`, `backend/app/report_narrative_v4.py` | 모든 실제 호출에서 run/step/attempt·actor·선택 정보를 전달. 기존 observer/fake provider 계약의 필요 변경만 적용 |
| `backend/app/run_v4.py`, `backend/app/attachment_runs_v4.py`, `backend/app/report_runs_v4.py` | 실행 재시작/명시 재시도/조회 DTO에 키 역할·전환 사유 반영. snapshot·재사용 의미 유지 |
| `backend/app/domain/runs_v4.py`, `backend/app/domain/report_runs_v4.py`, `backend/app/usage.py` | 새 attempt/조회에 optional 키 역할·전환 사유, 예약별 usage에 정확한 reference. 옛 기록은 없음으로 읽음 |
| `backend/app/reset_s1.py` | 정리 당시 reference를 현재 활성 두 슬롯에서 정확히 조회. 교체한 키/다른 슬롯의 임의 키로 삭제 금지 |
| 관련 기존 tests, `backend/tests/test_gemini_key_fallback.py` | 신설 후보: GK-T07~T16. 새 정책이 실제 Worker/transport 조립 경로에서 작동하는지 검증 |

파일 목록은 조사 기준이다. 구현 전 Graft callers와 exhaustive reserve_call 검색으로 현재 정확한 범위를 다시 확인한다. 키 전환을 위한 범용 provider router나 독립 큐를 만들지 않는다.

## 3 실행 계약과 구현 순서

1. **원인 분류:** 현재 developer_settings_required로 합쳐진 로컬 credential 실패와 외부 인증 실패를 구분한다. HTTP 상태/공급자 정규 코드/operation_phase만 정규화하고 메시지 문자열로 전환을 추측하지 않는다. [전체 오류 표](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md#42-오류-분류)를 코드와 표 기반 시험으로 고정한다. Interactions의 snake_case code와 Files 등 legacy 응답을 혼동하지 않는다. 확인하지 못한 400 인증 형식은 자동 전환하지 않는다.
2. **attempt 선택:** 새 run은 primary. 로컬 주키 미가용이면 외부 요청 전 backup을 첫 credential로 선택한다. 외부 주키 실행 후 전환 오류면 현재 attempt 실패를 저장하고 다음 attempt에서 backup을 선택한다. scorer 내부에서 두 키의 추론을 연달아 호출하는 숨은 재시도는 금지한다.
3. **run 내 유지:** 선택한 backup과 원인을 현재 run/step/attempt의 기존 changes/usage에 남긴다. 성공한 원관찰 뒤 애착 등 남은 단계도 backup을 사용한다. DB에서 현재 run의 실제 선택 사건을 읽어 재시작/재시도를 복원한다. 복사된 reuse usage 또는 다른 run의 오류를 전환 근거로 사용하지 않는다. global cooldown/자동 복귀 DB를 만들지 않는다.
4. **guard와 상한:** 선택/전환 기록·예약 직전과 외부 요청/게시 직전에 실제 actor·세션·중지·입력 revision/hash·lease/token을 확인한다. 기존 max_attempts·max_ai_calls·max_schema_repairs와 write fence를 공유한다. 주키 실패가 retryable=false인 인증 오류여도 예비키가 가용하고 다음 시도 여유가 있을 때만 전환 대기를 만든다. 예비키 없음/실패/상한 소진을 구체적으로 남기며 상한을 증액하지 않는다.
5. **재시도 기다림:** 429·일시 장애는 Retry-After와 기존 exponential backoff를 존중한다. 키 오류를 같은 주키로 반복하지 않는다. backup에서도 오류 원인별 기존 재시도 규칙만 적용하고 primary로 돌아가지 않는다. 스키마 수리는 현재 선택한 같은 슬롯과 동일 repair 상한을 사용한다.
6. **rotation 경계:** 매 새 attempt에서 선택 슬롯의 현재 활성 참조를 읽는다. 다른 직원의 교체/제거로 새 attempt가 retired ciphertext를 쓰지 않는다. 이미 시작한 attempt는 선택한 같은 원문으로 업로드/추론/정리를 마치며 중간에 다른 프로젝트로 키를 갈아 끼우지 않는다. 전체 사용 중지 후 새 attempt는 두 슬롯 모두 미가용이다. 새 run과 명시 재등록을 구분한다.
7. **미디어 경계:** backup attempt는 고정 로컬 clip/hash로 새 upload를 시작한다. primary 파일 URI나 resumable upload URL을 재사용하지 않는다. upload_started/uploaded/deleted/cleanup_failed에 step·slot/reference를 연결한다. 주키/예비키의 finally 정리와 후속 정리 모두 해당 업로드의 정확한 credential_reference만 사용한다.
8. **미확인 실패:** timeout·5xx·응답 유실 후 primary가 실제 처리/과금했을 가능성을 보존한다. upload 응답 유실의 미확인 remote 파일도 기존 대기 이력을 유지한다. backup 성공이 primary의 billing_uncertain/cleanup_pending을 지우지 않는다. 키 전환으로 외부 작업 exactly-once나 중복 과금 방지를 보장한다고 표시하지 않는다.
9. **보호된 산출물:** 기존 부분 성공 step은 다시 호출하지 않는다. 고정 모델/프롬프트/입력과 새 결과의 evidence/계산/문장 schema를 기존대로 검증한다. 기존 output/manifest/hash/config snapshot과 reuse compatibility를 일괄 변경하지 않는다. 키 역할은 새 실행 메타데이터이며 S1 점수 산식의 판본 변경이 아니다.
10. **조회/사용량:** 새 attempt에 credential_policy·slot/reference·전환 원인·실제 actor·작업 단계를 기록한다. 일반 업무 조회는 주키/예비키 역할·비밀 없는 정규 사유/시각만 표시하도록 typed DTO를 제공한다. 키 관리용 내부 reference는 개발자 상태/보호된 실행 원장에 남기고 업무 화면에서 키 일부를 노출하지 않는다. reserved_calls·실제 계량·미확인 비용·reuse 제외 의미를 유지한다.

키 원문을 run/config snapshot, stage context JSON, 저장 프롬프트, output 파일 또는 예외 문자열에 넣지 않는다. transport 반사 제거·origin 제한·redirect 금지도 그대로 적용한다. 메모리에서 실제 transport 호출에 쓰는 원문과 저장 가능한 참조를 구분한다.

## 4 인수 기준

| 시험 | 검증 방식과 기대 |
| --- | --- |
| GK-T07 | 주키 없음/유실/DPAPI 실패에서 backup 선택, 주키 external request0. 두 슬롯 없음은 설정 필요 |
| GK-T08/09 | 상태·정규 코드·작업 단계별 표 기반 fake transport. 선정 오류만 전환하고 JSON/guard/cleanup-only 오류는 전환0 |
| GK-T10 | 실제 scoring/attachment integrated·standalone/report narrative handler 각각 주키 실패→backup 성공·schema/evidence 검증 |
| GK-T11 | max_attempts1/2/3, max_ai_calls 도달·마지막 예약 경쟁·Retry-After·schema repair 공유. 같은 step 이중 예약/숨은 추론0 |
| GK-T12 | 실패/선택 기록 뒤 강제 worker 재시작, 같은 run 남은 단계 backup·새 run primary·backup 실패/폐기·rotation 경계·왕복0 |
| GK-T13 | 전환 대기/credential 선택/backup 외부 요청/늦은 게시 시점의 현재 actor 비활성·세션/중지/입력/lease/token/file hash race |
| GK-T14/15 | 프로젝트 A/B 역할을 분리한 transport, 같은 로컬 hash·서로 다른 URI, 정확한 key/reference로 업로드/삭제. 없는 옛 참조는 정리 대기 |
| GK-T16 | primary uncertain + backup 성공의 두 attempt/계량 보존, 부분 성공 무재호출·옛 output bytes 불변·명시 재사용 무호출/계량 중복0 |

핵심 회귀에서 권한·동의 삭제 관련 옛 시험명은 현행 업무 정책과 실제 기대값을 확인하고 사용한다. 이름만으로 옛 차단 조건을 되살리지 않는다.

```powershell
# backend/ — 구현 후, 신설 후보 모듈 포함
uv run --locked python -X utf8 -m unittest -v tests.test_gemini_key_slots tests.test_gemini_key_fallback tests.test_gemini_v4 tests.test_run_v4 tests.test_ai_api_v4 tests.test_attachment_ai_v4 tests.test_report_narrative_v4 tests.test_report_api_v4 tests.test_reset_s1 tests.test_execution_actor_v4
# 저장소 루트
git diff --check
graft build
graft check
```

사용량/보관의 실제 기존 회귀 모듈은 Graft로 확정하여 실행 기록에 추가한다. 예시 명령이 현재 신설 파일의 존재/시험 성공을 뜻하지 않는다. 제품 시험에서 실공급자 호출은0으로 유지하고 네트워크 실패를 fake transport로 재현한다.

## 5 인계와 완료 조건

GK03에 두 슬롯 관리 API와 실행별 키 역할·전환 원인·상한/대기/실패·옛 기록 없음 DTO를 인계한다. 단순히 GeminiScorerV4를 직접 부른 시험만으로 완료하지 않고 실제 Worker 예약·실패·재시작·게시까지 확인한다.

- [x] 모든 Gemini 경로에서 GK-T07~T16 및 GK01 회귀 통과
- [x] 원격 파일/정리·usage·옛 불변 파일/재사용·현재 actor/guard 증거
- [x] 공식 오류 형식/최신·선택 잠금판 확인, 독립 검토/triage·수용 재검증
- [ ] commit/PR/병합·GK03 DTO/화면 인계, 실공급자 검증 별도 대기 기록

## 6 2026-10-14 구현 기록

[실제 구현·검증·독립 검토 근거](K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md#gk02-자동-전환-실행)를 따른다. 공유 `gemini_keys` 선택/공개 metadata helper와 `Worker.gemini_request`를 사용하며 세 실제 호출점에 누락 없이 적용했다. DTO의 `credential_slot`, `fallback_reason`, `fallback_status`, `credential_selected_at`은 optional이다. 재사용 출처는 `source_credential_slot`/`source_fallback_reason`이고 현재 선택이 아니다. 내부 reference/원문은 일반 업무 DTO에서 제외한다. 독립 발견0으로 수용 변경도0이다.
