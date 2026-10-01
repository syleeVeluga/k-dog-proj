# PR-C07B AI 채점 연결

버전: v1.0 · 2026-09-30 · 상태: 구현·검증·cold review 완료, PR #34 · 선행: C07A · 추정: 2~3개발일

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20260930.md). 선행 기능: [C07A 실행 기반](K-DOG_PR-C07A_실행기반_v1.0_20260930.md). 근거: 00 §3·§4·§7, 02 대표값·눈금, 04 관찰창, 07 판정, 기존 Gemini 전송 계약. 권장 제목: `feat: 새 AI 채점 계약과 설정 및 사용량 연결`.

## 문제와 결과

Gemini 응답 schema, settings의 기본 프롬프트, 사용량 집계는 55항목에 결합되어 있다. C07A의 실행·복구 기반 위에 새 계약과 항목군별 설정을 연결한다. 계약·합성 시험 통과와 실제 영상 판독 검증은 별도 완료 상태로 기록한다.

## 변경 파일

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `backend/app/scoring_ai.py` | 신설 | 항목군·실제 창 요청, 새 응답 검증, 계산·다중 근거 판정 단계 연결 |
| `backend/app/gemini.py` | 변경 | 명시한 새 schema·응답 모델 선택, 영상·오디오·시각·샘플링 전달 |
| `backend/app/settings.py`, `backend/app/developer_sample.py` | 변경 | 새 단계 설정·초안·활성화, 계약·provider 시험, 55항목 기본 프롬프트로 대체 금지 |
| `backend/app/run_v3.py`, `backend/app/worker.py` | 확장 | 실제 AI 단계 등록, 요청 직전 입력 검사, 예산·재시도·실패 결과 연결 |
| `backend/app/usage.py` | 변경 | 새 AI 단계의 모델·계량·예약 호출·과금 불확실성·재사용 집계 |
| `backend/app/domain/contracts_v3.py`, `backend/app/domain/validation_v3.py`, `backend/app/input_models_v3.py`, `backend/app/api.py` | 확장 | AI 근거·상태·요청 범위·설정과 결과 제공 계약 |
| `frontend/src/DeveloperSettings.tsx`, `frontend/src/pages/Scoring.tsx`, `frontend/src/types.ts`, `frontend/src/api.ts` | 확장 | 새 설정, 시작·진행·오류·중지·재시도, 입력 기준·공개 정책 표시 |
| `backend/tests/test_scoring_ai.py`, `test_runs_v3.py`, `test_settings.py`, `test_usage_v3.py` | 신설/확장 | schema·샘플링·예산·오류·복구·설정·비용 |
| `frontend/tests/settings.spec.ts`, `frontend/tests/scoring.spec.ts` | 확장 | 설정 분리, 명시적 실행, 조회·재시도, 이전 기준·AI 공개 |

## AI 계약과 관찰 범위

1. 구현 전에 공식 provider의 최신 API, 샘플링, 파일·크기·시간 제한, 구조화 출력 호환성을 온라인 확인한다. 확인일·공식 링크·선택 API revision·모델과 이유를 기록한다. 현재 Gemini의 training/play, selected_option_id, legacy status schema를 새 원코드 값에 사용하지 않는다.
2. 직접 채점·메모 109행을 구간·항목군·실제 창으로 나눠 요청한다. 각 행의 주된 시간·첫 사건·범주 우선순위·횟수·초 정의와 원라벨을 제공한다. 미사용 4행·자동 4행은 AI 입력 항목 집합에서 제외한다. 누락·중복·알 수 없는 코드, 범위 밖 근거, 기회·관찰량 누락을 검증한다.
3. 원값 0은 항목별 라벨에 맞는 정상 관찰값이다. 기회 없음·미청취·가림·미실시를 0으로 대신하지 않는다. 상태·관찰 기회·유효성은 C00의 계약을 따른다. 발성은 전체 비중을 판단할 수 있는 오디오로만 코드화하고, 꼬리의 연속 움직임·짧은 접촉은 정지 프레임 근거만으로 확정하지 않는다.
4. 로컬 클립 제작 fps와 provider 요청 fps는 별개다. 현재 settings의 기본 1fps가 8fps 클립을 다시 낮출 수 있다. 실제 API가 지원하는 항목군별 요청 fps·processing mode·media_resolution을 명시하고 제작 설정과 함께 실행·재사용 해시에 고정한다. 모든 항목을 8fps로 읽는다는 가정은 하지 않는다.
5. provider 호출 직전에 원본·전처리 manifest·실제 클립의 소속과 해시를 확인한다. 클립 내부 근거 시각이 해당 창 안에 있는지 검사하고 원본 시각으로 역추적한다. 다른 사례·세션·영상·겹친 창의 근거를 같은 관찰로 합치지 않는다.
6. 항목 채점 뒤 C06의 순수 계산을 수행하고 관계의 다중 근거 판정 단계로 연결한다. 유형·근거·반대 근거·관찰 기회·보류 사유를 같은 계약으로 저장한다. LLM이 자동 4항목이나 배점 비율을 직접 재작성하지 않는다. 개별 근거 부족에 따른 보류와 요청·계약 오류를 구분하며, 실패한 구간을 추정값으로 채우지 않는다.

## 설정·계량·실행 연결

1. 새 실행 종류에 필요한 설정을 별도로 검증한다. 설정이 없으면 55항목 프롬프트나 legacy pipeline으로 대신 처리하지 않는다. API 키 등록, 모델·프롬프트 설정, 새 판본 설정 활성화를 구분한다. 기존 설정 초안·활성 버전은 구판 실행 이력으로 보존한다.
2. 활성화한 설정의 내용·해시를 접수 시 고정한다. 실행 중 활성 설정을 바꿔도 기존 실행의 요청은 바뀌지 않는다. 항목군·창별 계획 호출 수와 재시도 상한을 확인할 수 있게 하되 확인되지 않은 가격을 기본값으로 넣지 않는다.
3. 새 AI 단계 모두 call_reserved, max_ai_calls, max_attempts, 스키마 수리 상한, billing_uncertain을 적용한다. `worker.py`와 `usage.py`의 구판 단계 열거·모델 선택을 함께 갱신한다. 프로그램 계산·병합은 외부 호출로 과금 집계하지 않으며 재사용 원본의 사용량을 다시 더하지 않는다.
4. 호출 예약 후 종료·timeout·불완전 응답은 과금 여부를 미확인으로 남긴다. 계량·단가 누락을 0원으로 표시하지 않는다. 오류 코드는 동작 상태로, 원래 provider의 token 계량값은 사용량으로 보존한다.
5. 기존 비밀값 redaction, 원격 파일 삭제, 삭제 실패 기록을 유지한다. 영상·메모·의견은 지시가 아닌 입력 자료다. 연구용 독립 AI 실행에는 전문가 점수·판정·행사 의견을 넣지 않는다. AI 결과의 제공에는 C05의 공개 정책을 적용한다.
6. C07A의 명시적 생성·중지·재시도 API와 프론트를 연결한다. 상태 조회·메뉴 재방문은 enqueue하지 않는다. 입력이나 설정이 바뀐 뒤 재생성은 새 실행이며, 이전 실행 결과는 이력으로 남긴다. 실제 provider 호출은 Q11의 적용 범위를 확인한 운영 설정에서 활성화한다.

## 검증과 완료 조건

- 합성 provider 응답의 새 schema, 정확한 항목 집합, 원값·사유·창, 음수·0·99·빈값, 중복·오류·자동값 입력 거절과 55항목 대체 처리 차단을 검증한다.
- 로컬 제작 fps·provider 요청 fps 전달, media_resolution, 설정 변경 후 재사용 차단, 원본 시각 역추적과 실제 클립의 동일 크기 변조 검출을 시험한다.
- 음성 누락·미접촉·복지 신호 뒤 배점 제외·대표값 근거와 구간별 실패를 검증한다. 일부 구간 실패가 다른 원자료를 삭제하거나 실패 구간을 정상 점수로 만들지 않는다.
- 호출 상한·수리 상한, 429·timeout·불완전 응답, 원격 삭제 실패, 키 비노출, 신규 단계의 모델별 사용량, 재사용 중복 과금 제외를 시험한다.
- 설정 변경 중 실행, 중지·재시도·점유 만료·옛 token·삭제 요청은 C07A 보호장치를 통과한다. 프론트와 API의 AI 공개 제한이 일치한다.
- 실제 영상이 없으면 ‘계약·합성 검증 완료, 실제 판독 미검증’으로 기록한다. 항목 정확도·대표값 일치·꼬리·음성·거리·처리시간은 C15의 실자료 검증에서 평가한다.

## 추가 확인과 인계

Q02·Q06~Q08·Q11·Q12. C07A와 C07B 합계는 기존 C07의 4~6개발일 추정이며 실제 판독 검증 기간은 별도다. 새 구현과 관계없는 55항목 reporting/export 모듈은 호출 경로 확인 없이 삭제하지 않는다. C10에서 실제 대체물이 들어온 호출 경로만 정리한다.

## 구현 및 검증 기록 — 2026-10-01

- [x] 직접109행을 같은 원본 관찰창 집합의36군으로 요청한다. 원코드·라벨·대표값·첫사건·횟수·초 정의를 제공하고 자동4/미사용4행·누락·중복·범위 위반을 거절한다. 미실시 창은 호출 없이 null/사유로 병합한다.
- [x] `domain/scoring_ai_v3.py`의 클립 내부 계약을 검증해 앱이 원본 video/SHA/시각으로 변환한다. 실제 기회·유효성·확인량·요청 클립/창을 검사한다. 발성6행은 원항목 전체 실제 오디오 창·전체 청취/누적 발성량·원코드 비중이 일치해야 한다.
- [x] 채점 → 프로그램 계산 → 같은 AI 원자료의 기본 판정 → 게시로 연결한다. C06의 원본 유형·다중 근거·반대 근거·관찰 기회·실제 사용 배점 근거 검사를 공유한다. 다른 평가자의 채점/판정·행사 의견은 프롬프트에 넣지 않는다.
- [x] 실패한 항목군은 null/요청 오류 사유이며 나머지 원자료·계산을 보존한다. 판정 요청 실패는 보류다. 수리 대기 중 계산 attempt를 만들지 않는다. 게시된 부분 결과는 `partial_failed`로 잠그며 재생성은 새 실행이다.
- [x] AI 원자료는 로그인 불가 기록 전용 계정의 제출된 시트다. 운영자도 직접 원값/기본 결과 조회·수정은 불가하다. 같은 고정 입력의 독립 제출본에 C05 명시 공개 허용 → 실제 열람/노출 이력 저장 뒤 해당 완료 revision의 AI 원자료·계산·판정만 제공한다.
- [x] `settings_v3.py` 및 `/developer/settings-v3`를 신설했다. 구판 `settings.py`/`developer_sample.py`를 덮어쓰지 않고 별도 초안/hash/차이/활성화/계약·provider 합성 시험을 제공한다. 초기 Q11은 미확인이며 확인 설정만 운영 활성화할 수 있다.
- [x] 접수 시 모델·프롬프트·schema·제작native/요청fps·processing/resolution·상한·활성 설정 판본/내용SHA256/Q11 확인을 고정한다. 계획 외부37회(36군+판정), 프로그램2단계로 총39단계다. 미실시·명시 재사용은 호출을 줄인다. 최대 시도3·수리1·전체 호출 상한은 공통 예약 fence를 적용한다.
- [x] 사용량 집계에 `score_v3`/`judge_v3` 모델·예약·원래 중첩/배열 계량을 포함한다. 복사한 상위 계량과 원래 계량, 프로그램 계산/병합, 예약 없는 재사용을 중복 과금하지 않는다. 단가/응답 유실은 미확인이며 키 보호/redaction/원격 삭제 실패 감사 기록을 유지한다.
- [x] `AiSettings.tsx`/`AiRuns.tsx`를 개발자/독립 채점 화면에 연결했다. 조회·메뉴 재방문은 enqueue하지 않는다. 안정된 요청ID로 응답 유실 후 동일 요청을 재접수하며 명시 생성·중지·고정 입력 재시도·새 재생성·명시 재사용·이전 기준·실패/과금 미확인을 표시한다.
- [x] C06의 발성창 오류(개49 걷기/개50 낯선 사람)를 원본 카탈로그의 개49 낯선 사람/개50 퇴장으로 교정했다. `scoring-20260929-v3-app-2`로 판본을 올리고 다른 길이의 창 회귀를 추가했다. 저장된 `app-1` 결과는 다시 쓰지 않는다.
- [x] 최초 전체 backend223건300.914초, AI/실행22건78.691초, 추가2건36.356초, 마지막 AI/계산/실행32건112.423초 통과. frontend build, 관련 Playwright4건34.2초, 360px 가로 넘침, 원본8개 `app.import_catalogs --spec all --check` 대조 통과. cold 수정 후 전체 backend227건363.897초, 마지막 파일크기/provider1건1.338초와 build 재확인 통과.
- [x] 독립 cold review 완료 → 발견 수용 여부 기록 → 수용건 반영/재검증 → 완료 표시·푸시.

화면: [설정desktop](검증자료/C07B_설정_desktop.png), [설정360px](검증자료/C07B_설정_360.png), [실행360px](검증자료/C07B_실행_360.png). 시험 영상은 생성한 회색 화면/신호음이며 실제 반려견 평가가 아니다.

### 공식 판본·호환성 확인 — 2026-10-01

| 대상 | 최신 확인 / 선택 | 근거·이유 |
| --- | --- | --- |
| Gemini 모델 | stable `gemini-3.8-flash` / 동일 | [공식 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [목록](https://ai.google.dev/gemini-api/docs/models). 영상/오디오/JSON·thinking low/medium/high, minimal 제외. SDK 설치 없이 기존 REST 사용. |
| Interactions | stable v1 존재 / v1beta | [stable 참조](https://ai.google.dev/api/interactions-api-v1)는 선택 모델3.8/영상processing을 열거하지 않고 [beta 참조](https://ai.google.dev/api/interactions-api)는 해당 모델·정적fps/agentic·VideoContent name/resolution을 명시한다. 확인한 호환성 제약 때문에 beta를 선택했다. 해상도는 비디오 입력 resolution이며 generation_config에 미지원 media_resolution을 넣지 않는다. |
| 응답 revision | steps 계약 / migration header2026-05-20 | [공식 migration](https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026). 6/8부터 header는 무시되므로 provider 계약 고정 보장으로 해석하지 않는다. 앱 schema/hash·응답 검증을 적용한다. |
| 영상 | static 명시fps/agentic / 초안4·8fps | [영상](https://ai.google.dev/gemini-api/docs/video-understanding), [해상도](https://ai.google.dev/gemini-api/docs/media-resolution). native 제작과 요청fps를 구분하고 agentic에는 고정fps를 넣지 않는다. 기본1fps/내부오디오 처리의 빠른 행동·발성량 정확도는 미검증이다. |
| Files | 파일당2GB 안내 / 2,000,000,000바이트 상한 | [Files](https://ai.google.dev/gemini-api/docs/files). GB/GiB 단위 불명확성에 더 작은 십진 상한을 사용한다. 요금제별 영상 안내의 더 큰 한도에 의존하지 않고 임시 업로드 후 직접 삭제, 실패를 기록한다. |
| Node/uv/FFmpeg | 26.10.0 current·24.21.0 LTS / 24.13.0, uv0.12.21 / 0.11.18, FFmpeg9.0.2·8.1.3 / 8.1.1 | [Node](https://nodejs.org/en/about/previous-releases), [uv](https://github.com/astral-sh/uv/releases/tag/0.12.21), [FFmpeg](https://ffmpeg.org/download.html). 기존 설치·lock/Windows 빌드를 유지한다. Node24는 Vite/Playwright engine을 충족하고 이번 변경과 무관한 runtime 교체는 하지 않는다. |
| Python/FastAPI/Pydantic | 3.14.7/0.142.2/2.13.5 / 3.14.2/0.141.1/2.13.5 | [Python](https://www.python.org/downloads/release/python-3147/), [FastAPI 릴리스](https://fastapi.tiangolo.com/release-notes/), [FastAPI registry](https://pypi.org/project/fastapi/), [Pydantic registry](https://pypi.org/project/pydantic/). 기존 lock/runtime 제약 유지, 무관한 업그레이드 없음. |
| React/ReactDOM/Vite/TypeScript/Playwright | 19.3.0/8.3.1/7.0.2/1.63.0 / 19.2.8/8.2.2/7.0.2/1.63.0 | [React](https://registry.npmjs.org/react/latest), [ReactDOM](https://registry.npmjs.org/react-dom/latest), [Vite](https://registry.npmjs.org/vite/latest), [TypeScript](https://registry.npmjs.org/typescript/latest), [Playwright](https://registry.npmjs.org/%40playwright%2Ftest/latest). C04 확인과 같은 기존 lock/호환 runtime 유지, 신규 의존성 없음. |

### Cold review 수용 검토

| 발견 | 수용 여부·반영 | 검증 |
| --- | --- | --- |
| P2 외부guard 뒤 게시writer 전 동의철회/계정권한 변경 경합 | 수용. 최종 게시writer에서도 현재manifest 분석동의와 요청 계정 활성 운영권한을 재검사 | 해당 시점 동의철회/계정비활성화·provider필드3건25.786초 통과 |
| P2 AI 재개방 후 재제출 불가로 공개가 막힘 | 수용. API에서 AI save/submit/reopen을 거절하고 요약의 평가종류로 UI 재개방을 제외. 취소/재활성화는 원자료가 같음을 확인해 원래 계산참조 공개 | AI 재개방403·재활성화r3 공개/계산input r1 유지1건14.141초 통과 |

독립 reviewer가 두 수용 수정의 해결을 확인하고 관련3건을 재검증했다(45.891초 통과). 추가 P1/P2는 없었다. 수정 후 build 및 관련 Playwright4건37.8초 통과. 최종 전체 backend227건363.897초 통과, 파일상한 십진2GB/provider 회귀1건1.338초 및 마지막 build 재확인 통과. 구현·검증·독립 cold review·수용 수정·문서 갱신 후 PR #34로 푸시했다.

### 검증 한계 및 인계

필수 codebase-memory MCP는 도구 목록에 없어 알린 직접 소스 fallback을 사용했다. 합성 응답/HTTP 주입·생성 영상·worker 없는 브라우저 검증이다. 실제 provider 호출0회, 고객 영상/독립 전문가 채점·실증 환경은 미확보로 ‘계약·합성 검증 완료, 실제 판독 미검증’을 유지한다. sampling 성능·대표값/꼬리/청취/거리/처리시간·실제 응답 일치는 C15 대상이다. Q02·Q06~Q08·Q11·Q12 고객 확인 대기는 유지한다.
