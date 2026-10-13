# PR-GK03 Gemini 키 관리와 전환 상태 화면

버전: v1.0 · 작성 2026-10-13 · 구현/검증 2026-10-14 · 상태: 구현·검증·독립 cold review·수용 수정 완료, 병합 대기 · 선행: GK02 #96 병합 `ad857d1` · 브랜치: `veluga/gk03-gemini-key-ui`

상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md). 요구 GK-R10~R11, 시험 GK-T17~T19. 제목 제안: `feat: manage Gemini backup keys and show fallback status`.

## 1 문제와 결과

현재 개발자 화면은 공급자별 한 개 키만 표현하며 업무 실행의 주키/예비키 사용을 구분하지 않는다. Gemini 선택 시 두 슬롯의 관리와 자동 전환 안내를 제공하고, 실행 상세에는 실제 사용 역할과 전환 사유를 표시한다. 기존 신판 AI 설정 패널과 다른 공급자 키 관리 기능은 유지한다.

## 2 화면 계약

- 「Gemini 주키」와 「Gemini 예비키」를 두 카드로 표시한다. 각각 등록 상태·해당 reference의 마지막 연결 시험 상태/시각·비밀번호 입력·등록/교체·선택 키 시험·앱에서 제거를 제공한다. 예비키 카드에는 「주키 문제 시 자동 사용」을 표시하고 별도 승인을 만들지 않는다.
- 입력은 type=password·autoComplete=off·기존 길이 제한이며 React 영구 초안, localStorage/sessionStorage, query/hash 또는 telemetry에 저장하지 않는다. 제출과 계정/화면 종료 시 DOM 입력을 비운다. 키 일부를 등록 확인용으로 보여주지 않는다.
- 슬롯 등록/제거에는 마지막 조회의 expected_reference를 보낸다. 409면 원문을 다시 저장/자동 재전송하지 않고 현재 상태를 조회한 뒤 재입력하도록 안내한다. 원문을 복구용 초안으로 보존하지 않는다. 늦은 시험 결과는 요청한 slot/reference에만 연결한다.
- 「주키를 앱에서 제거」는 주키만 제거하고 예비키가 남으면 계속 사용할 수 있다는 의미다. 「예비키를 앱에서 제거」는 예비키만 제거한다. 「Gemini 전체 키 사용 중지」는 기존 provider DELETE로 두 슬롯을 제거한다. 이는 공급자 콘솔의 키 취소/진행 중 원격 요청 취소와 다르다는 설명을 붙인다. 업무 실행 중지와 혼동하지 않는다.
- 주키가 환경 변수로 제공되면 「실행 환경의 주키」로 표시하고 등록/제거가 환경 변수 원문을 반환하지 않도록 한다. 앱에서 제거한 뒤 환경 변수로 자동 복귀하지 않음을 안내한다. 복원 뒤에는 두 슬롯 재등록이 필요하다.
- 연결 시험은 선택 키만 시험하며 자동 fallback을 하지 않는다. 「연결 확인」은 모델 목록 조회 결과이고 실제 평가 품질 확인이 아님을 표시한다. 같은 프로젝트의 두 키는 프로젝트 할당량을 공유한다는 짧은 안내를 둔다.

업무 화면에는 같은 run/step의 「주키 사용」, 「예비키 사용 · 주키 인증 실패 후 전환」, 「예비키 재시도 대기」, 「예비키 미등록」 또는 「시도/호출 상한 도달」을 비밀 없는 정규화 문구로 표시한다. 전체 계획·처리 단계·선택 실행/결과·부분 실패·billing_uncertain/cleanup_pending 표시를 유지한다. 과거/재사용 원장의 사용 역할과 현재 run의 선택을 구분하며 기록이 없으면 「키 역할 기록 없음」으로 표시한다.

## 3 대상과 순서

| 대상 | 변경 |
| --- | --- |
| `frontend/src/DeveloperSettings.tsx` | Gemini 두 슬롯·typed 상태/요청·409·정확한 시험/제거·원문 초기화 |
| `frontend/src/AiRunsV4.tsx`, `frontend/src/ReportRunsV4.tsx` | 해당 실행 상세의 역할·전환 원인/대기/실패 문구 |
| 실행 상세/사용량을 소비하는 실제 frontend 타입·컴포넌트 | Graft로 조회한 실제 파일만 변경. 별도 전역 키 현황/알림 메뉴를 만들지 않음 |
| `frontend/tests/settings.spec.ts`, `frontend/tests/retirement-v4.spec.ts`, `frontend/tests/scoring-ai-v4.spec.ts` | 기존 접근/키/신판 설정·실행 회귀 |
| `frontend/tests/gemini-key-fallback.spec.ts` | 신설 후보: 두 슬롯과 실제 API로 만든 실행의 전환 상태 |

1. GK02의 실제 응답 타입과 현재 UI 소비자를 Graft로 대조한다. 입력 관리와 실행 DTO를 섞지 않는다.
2. 개발자 두 슬롯을 구현하고 반응형/키보드 label·등록/시험/제거 메시지를 검증한다. 개발자 상태가 일반 직원 화면에 나타나지 않게 한다.
3. 지정 실행 ID의 역할·전환 사유를 추가한다. 기존 폴링/늦은 응답/계정·회차 전환 보호를 유지한다. 화면 조회가 AI 실행이나 연결 시험을 자동 시작하지 않게 한다.
4. 390px·1366px에서 상태/버튼·넘침을 확인하고 합성 키 입력이 비워진 뒤 화면을 캡처한다. 스크린샷·Playwright trace/영상에는 실제 키를 사용하지 않는다.

## 4 인수와 명령

- GK-T17: 주키/예비키 독립 등록·입력 초기화·올바른 슬롯 시험/제거·전체 사용 중지·409 재입력·늦은 결과 reference 고정.
- GK-T18: 입력 원문이 body text·브라우저 저장소·조회 API·validation/error 메시지·캡처에 없음. 일반 계정 관리403, 비활성/만료 세션 종료, 두 화면 폭/키보드 조작.
- GK-T19: 실제 서버/fake transport로 만든 채점·애착·문장 실행의 주키 실패→예비키 성공/실패·상한/대기·미확인 비용·옛 역할 없음 표시. UI mock은 오류/경합 재현을 보조하며 종단 인수의 대체 근거가 아님.

```powershell
# frontend/ — 구현 후, 신설 후보 spec 포함
npm run build
npm run test:e2e -- tests/settings.spec.ts tests/retirement-v4.spec.ts tests/scoring-ai-v4.spec.ts tests/gemini-key-fallback.spec.ts
# 저장소 루트
git diff --check
graft check
```

## 5 완료와 인계

실제 구현/검증과 실패·재검증 범위는 [실행 기록](K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md#gk03-키-관리와-실행-표시)에 기록한다. 두 폭의 합성 화면: [390px](assets/GK03_Gemini_keys_390_20261014.png), [1366px](assets/GK03_Gemini_keys_1366_20261014.png).

- [x] GK-T17~T19·기존 developer/신판 AI 설정/업무 접근·문맥 회귀 통과
- [x] 두 폭의 합성 캡처·키 원문/브라우저 저장소 부재 증거
- [x] 공식 frontend 최신/선택 잠금판 확인, 독립 cold review·수용 수정/재검증
- [ ] commit/PR/병합과 GK04 종단 경로·시험 fixture/후속 인계
