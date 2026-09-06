# K-DOG M2 관찰 처리 구현 기록

> 이 문서는 당시 구현·시험 이력이다. 2026-09-06 후속 변경으로 동의 입력·저장·철회·동의 기반 차단 기능을 제거했다. 현재 운영은 [동의 관리 제거 기록](K-DOG_동의관리제거_v1.0_20260906.md)을 우선하며, 자료 삭제·권한·작업 중지 검사는 유지한다.

버전: v1.0

작성일: 2026-09-06

범위: 구현 지시서 M2, AI 파이프라인 S0–S3의 최소 관찰 흐름

## 구현 결과

M1 입력 자료에서 실행을 접수하고, 별도 Python worker가 미디어 검사 → 카메라별 Gemini 관찰 → 근거 검증·통합을 수행한다. 목록에 현재 실행 상태가 표시되고 상세에서 실행 이력·부분 관찰·원본 시간의 영상 재생·실패 단계 재시도·중지를 사용할 수 있다. 설문이 미등록이어도 영상 관찰은 가능하다. 항목 평가·점수·설명·내보내기는 M3 이후다.

실제 참가자 샘플과 공급자 키를 사용하는 시험은 사용자 요청에 따라 생략했다. **Gemini 실 API와 실제 행동·음성 관찰 품질은 미검증**이다. 테스트에서 생성한 색상 영상·사인파 오디오와 가상 관찰은 실제 평가 결과가 아니다.

## 실행

[개발 안내](DEVELOPMENT.md)의 잠금 의존성 설치와 프런트엔드 빌드를 먼저 수행한다. FFmpeg와 ffprobe가 PATH에 있어야 한다. 이번 환경은 Python 3.14.2, Node.js 24.13.0, FFmpeg/ffprobe 8.1.1에서 확인했다.

서버와 worker는 같은 자료 폴더를 사용하는 별도 프로세스다. 기본 자료 폴더는 기존 M1과 같으며 소스 저장소 안에는 둘 수 없다. 각 터미널은 `backend/`에서 실행한다.

```powershell
# 터미널 1: 개발자가 사용 승인된 모델 ID를 지정한 환경에서 웹 서버 시작
# KDOG_GEMINI_MODEL은 두 프로세스에서 같은 값이어야 한다.
uv run --locked python -X utf8 -m app.manage serve

# 터미널 2: 개발자가 GEMINI_API_KEY와 KDOG_GEMINI_MODEL을 공급한 실행 환경
uv run --locked python -X utf8 -m app.manage worker

# 대기 실행 하나만 처리하고 종료하는 점검 명령
uv run --locked python -X utf8 -m app.manage worker --once
```

`KDOG_GEMINI_MODEL`에는 Gemini 영상·구조화 출력 지원 모델 ID를 지정한다. 기본 모델을 임의 선택하지 않는다. `GEMINI_API_KEY`는 프로세스 환경에서만 읽으며 DB·manifest·결과·설정 파일에 저장하지 않는다. 키를 명령 인수나 셸 이력에 입력하지 말고 개발자가 관리하는 실행 환경으로 공급한다. 모델은 API가 접수할 때 고정하고 키는 worker가 호출할 때 읽는다. 웹 서버와 worker 환경이 다르면 화면의 설정 안내는 웹 서버 기준이며 실제 키 유효성은 worker에서 확인한다.

자료 폴더를 변경할 때는 두 명령 모두 `python -X utf8 -m app.manage --data-dir "D:/K-DOG-data" serve` 또는 끝에 `worker`를 사용한다. 서버 종료와 별개로 worker는 계속 동작한다. worker가 없으면 작업은 대기 상태를 유지한다.

운영자는 영상·외부 AI 전송 동의를 기록하고 상세의 **관찰 시작**을 누른다. 같은 입력의 진행 작업은 중복 접수하지 않는다. 완료 후 다시 시작하면 새 run이며 비용이 발생할 수 있다. 키 누락·401/403은 ‘개발자 설정 필요’로 중단하며 가상 공급자나 다른 모델로 전환하지 않는다. 누락 키를 설정한 뒤 실패 단계 재시도가 가능하다. 접수 당시 모델 설정이 없었거나 모델을 바꾸었다면 설정 후 **새 관찰 실행**을 만들어야 한다. 기존 run의 설정은 바뀌지 않는다.

## 처리·저장 계약

- S1: 등록 파일 크기·SHA-256, 길이·코덱·해상도·오디오 트랙을 ffprobe로 확인하고 FFmpeg 전체 디코딩으로 파손을 검사한다. 로컬 허용 컨테이너와 프로토콜만 읽는다. 호환 H.264/AAC 파일은 원본을 사용하고 다른 지원 입력은 오디오를 유지한 MP4 사본을 만든다. 최소 계획 3분으로 자르지 않는다. 원본 길이 기준 시간과 오디오 유무를 RunInput에 고정한다.
- 일부 파일 파손은 해당 영상의 오류로 남기고 유효 카메라는 계속 처리한다. 유효 영상이 없으면 공급자를 호출하지 않는다. 파손 입력은 새 입력/촬영 세션으로 보완한다. 저장된 성공 미디어 검사를 무조건 다시 실행하지 않는다.
- S2: Files API의 resumable 등록 → 준비 상태 조회 → generateContent → 구조 검증 순서다. 카메라 하나에 전체 영상·오디오와 항목 원문·동선 메모만 제공한다. 설문 응답·참가자 ID·이름·다른 평가 점수는 요청 문맥에 넣지 않는다. 근거 ID와 참가자·run·영상 연결은 서버가 부여한다.
- 관찰은 사실·시간·대상·구간·후보 항목·품질 플래그와 미확인 조건만 포함한다. 점수·선택지·진단·미정 규칙을 생성하지 않는다. 1fps 샘플링을 고정 기록하며 빠른 행동의 시간 해상도 한계를 표시한다. 오디오 트랙이 있다는 것은 음성의 사용 가능성을 보장하지 않으므로 잡음·발성 출처는 모델의 불확실성으로 남긴다.
- S3: 구조·시간·참가자·세션·카메라·항목·무음의 오디오 근거를 검사한다. 55개 항목별 근거 ID와 미관찰 항목, 통합 근거 파일을 저장한다. 현재 카메라 보정값 입력이 없으므로 동기화 미확인으로 보존하며 사건 그룹·횟수를 임의로 합치지 않는다. 주 카메라 지정·동기화 편집과 행동 수치 집계는 후속 단계다.
- 5개 테이블을 유지하며 새 테이블/DB 마이그레이션은 없다. `runs.input_snapshot_json`은 intake 원본, 성공 prepare 산출물은 검사된 RunInput, `config_snapshot_json`은 키 없는 모델·프롬프트·항목·관련 해시다. 원본 입력·설정은 기존 불변 트리거를 유지한다.
- 모든 산출물은 `runs/<run_id>/<step_id>/output.json`에 저장한다. 임시 파일 flush/fsync 후 덮어쓰기 없는 원자적 링크로 게시한다. envelope에 run·step·점유 토큰·입력/설정 해시가 있고 DB가 채택한 경로·해시만 조회한다. 통합 단계는 `runs.result_ref/result_hash`에 연결된다. 재생 API는 검사된 원본 또는 호환 사본의 해시와 현재 접근 상태를 확인한다.

## 점유·철회·재사용

F-01: run 점유는 180초, heartbeat는 30초다. 미디어·네트워크 처리는 DB 트랜잭션 밖에서 수행한다. 산출물 채택과 완료 상태 변경은 짧은 쓰기 트랜잭션에서 현재 토큰·상태·만료·동의를 다시 검사한다. A 점유 만료 → B 성공 → A 응답 도착 시 A 파일은 별도 미채택 파일이며 B 참조를 바꾸지 못한다.

중단 복구는 최신 미완료 시도의 완성 파일에 한해 envelope와 출력 계약을 검증하고 새 점유 아래 채택한다. 완성 파일이 없거나 잘못되면 이전 시도를 abandoned로 남기고 다음 시도를 만든다. 새 시도가 생긴 뒤 도착한 이전 파일은 채택하지 않는다. 임시·미채택 파일의 자동 정리와 전체 백업 복구는 M5/M6 대상이다.

F-02: 대기·실행·재시도에 현재 동의/삭제 상태를 적용한다. 원격 등록·영상 전송·준비 조회·추론 요청 직전, 산출물 채택과 영상 제공 직전에 재확인한다. 철회/삭제 접수는 점유를 무효화하고 새 호출과 결과 재노출을 막는다. 이미 전송한 요청의 취소·환불은 보장하지 않는다. 원격 파일 삭제는 자료를 추가 전송하지 않는 정리 요청으로 철회 후에도 수행한다. 삭제 실패는 `remote_cleanup_pending`으로 남기며 원격 등록 응답 자체를 받지 못한 경우의 정리는 공급자 보관 정책에 의존한다.

F-03: 상세에서 이전 실행을 선택하고 **선택 실행의 성공 관찰 재사용**을 지정한다. 같은 case·session·영상/카메라·촬영 방식·동선·관찰 설정/항목 해시일 때만 원본 run·step·경로·해시를 새 run의 불변 reuse manifest에 등록한다. 원래 근거 ID와 run ID를 보존하며 명시적 허용 목록 검증에서만 연결을 허용한다. 설문 변경은 재사용을 막지 않지만 다른 참가자·재촬영·영상·관련 설정은 거절한다. 첫 구현은 원본 성공 관찰을 직접 참조하며 재사용된 실행을 통한 연쇄 재사용은 제공하지 않는다. S4 평가 재사용은 M3 대상이다.

F-04: 접수 시 현재 입력 revision의 `display_run_id`를 지정하고 완료 시에는 교체하지 않는다. 이전 입력의 늦은 완료가 현재 결과를 밀어내지 않는다. 입력이 바뀌면 표시 연결을 해제하며 과거 실행은 이전 버전으로 열람한다. 전체 내보내기 snapshot은 M4 대상이다.

## 실패·한도

429·일시 네트워크/5xx는 Retry-After와 10/20초 증가 지연 중 긴 값으로 재시도한다. 단계당 최초 포함 최대 3회이며 네트워크 재시도와 구조 수정이 같은 예산을 사용한다. 구조/시간 오류는 수정 재요청 최대 1회다. 수동 재시도도 이 한도를 초기화하지 않는다. 성공 카메라는 재호출하지 않는다. 인증/키 오류는 다른 카메라 호출도 멈춘다. 요청/응답 유실과 worker 중단 시 과금 불확실성을 남긴다.

출력 한도는 추론당 16,384 토큰, 영상 준비 대기는 300초, HTTP 요청은 120초, ffprobe는 60초, 디코딩/변환은 각 900초다. 길이 제한을 새 평가 기준으로 쓰지 않는다. 전송·사용량을 완전한 금액 상한으로 보장하지 않는다. 실제 요금·최대 입력 제한·참가자/전체 금액 및 토큰 예산 편집·비밀 저장소 UI는 후속 개발 설정 단계에서 다룬다.

## 검증

Python 전체 **56개**(M0/M1 39 + M2 17), 브라우저 **4개**, production build, 원본 항목집 55/30개 대조가 모두 통과했다. M2 시험은 다음을 포함한다.

- 실제 로컬 FFmpeg로 생성한 무음 H.264와 유음 MKV 검사, 오디오를 유지한 MP4 변환, 원본 해시 보존·파손 거절.
- 가상 관찰 2카메라의 독립 저장/부분 조회, 중복 클릭, 서버 저장 결과 재조회, 항목·시간·무음 오디오 거절, 재시도/수정 한도·사용량 보존.
- 대기 철회 시 호출 0회, 진행 중 삭제의 늦은 응답 거절, 영상 재생 접근 철회, 직원/개발자 권한 분리.
- 완성 파일 게시 직후 DB 기록 전 중단 복구, 만료 A/B 경합, 오래된 입력 완료의 표시 run 보호, 손상 결과 재사용 거절.
- 설문 수정 시 공급자 재호출 없는 명시적 관찰 재사용, 타 참가자/재촬영/동선 변경 거절, 설정 스냅샷 유지.
- HTTP 모의 전송으로 등록·준비 조회·구조화 요청·원격 삭제 순서, 요청 전 guard, 오류 비밀 비노출, 비공급자 업로드 URL 거절.
- 실제 브라우저에서 테스트 전용 worker의 가상 관찰 저장·새로고침·재생 시간 링크·철회 후 근거 숨김, 데스크톱/360px 배치 확인.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
# frontend/
npm run build
npm run test:e2e
# repository root
git diff --check
```

브라우저 테스트 전용 서버만 가상 observer와 probe를 주입하며 `GEMINI_API_KEY`를 환경에서 제거한다. 운영 API/CLI에는 가상 공급자 선택 경로가 없다. 테스트 스크린샷은 무시되는 `frontend/test-results/intake-M2-*/`에 생성한다. 실제 공급자 요청, 사용자 영상의 근거 품질, 20명 부하, 실제 PC 강제 종료·백업 복원 시험은 이번 결과에 포함하지 않는다.

검증 화면: [데스크톱 관찰 상세](images/m2-observations-desktop.png), [360px 관찰 상세](images/m2-observations-mobile.png). 모두 가상 참가자·가상 관찰이다. 화면의 설정 필요 안내는 실제 키를 제거한 테스트 서버 상태를 표시한다.

## 의존성·공식 문서 확인

확인일: **2026-09-06**. 새 Python/JS 라이브러리를 추가하지 않았다. 공식 PyPI JSON과 npm latest 메타데이터에서 다음 최신 안정 버전과 런타임/peer 조건을 재확인했고 기존 정확한 버전·lockfile을 유지했다.

| 도구 | 최신 안정 = 선택 버전 | 확인 출처 |
|---|---|---|
| Pydantic / FastAPI | 2.13.5 / 0.141.1 | [Pydantic PyPI](https://pypi.org/pypi/pydantic/json), [FastAPI PyPI](https://pypi.org/pypi/fastapi/json) |
| Uvicorn / openpyxl / httpx | 0.52.4 / 3.1.5 / 0.28.1 | [Uvicorn](https://pypi.org/pypi/uvicorn/json), [openpyxl](https://pypi.org/pypi/openpyxl/json), [httpx](https://pypi.org/pypi/httpx/json) |
| React / React DOM | 19.2.8 / 19.2.8 | [React npm](https://registry.npmjs.org/react/latest), [React DOM npm](https://registry.npmjs.org/react-dom/latest) |
| Vite / TypeScript | 8.2.2 / 7.0.2 | [Vite npm](https://registry.npmjs.org/vite/latest), [TypeScript npm](https://registry.npmjs.org/typescript/latest) |
| Playwright Test | 1.63.0 | [Playwright npm](https://registry.npmjs.org/@playwright/test/latest) |
| React / DOM type definitions | 19.2.18 / 19.2.7 | [React types](https://registry.npmjs.org/@types/react/latest), [DOM types](https://registry.npmjs.org/@types/react-dom/latest) |

Vite는 Node ^20.19 또는 >=22.12, Playwright는 >=20, TypeScript는 >=16.20이며 로컬 Node 24는 조건을 만족한다. React DOM peer는 React ^19.2.8, DOM types는 React types ^19.2.0이다. Python 직접 의존성의 최소 지원은 3.8–3.10이며 프로젝트의 기존 3.14 고정을 유지한다. Starlette TestClient의 기존 httpx 사용 중단 예정 경고는 남아 있지만 테스트는 통과하며 관련 없는 테스트 클라이언트 교체는 하지 않았다.

FFmpeg의 [공식 다운로드](https://ffmpeg.org/download.html)는 최신 안정 **9.0.1**을 표시한다. 이번 선택은 이미 설치된 **8.1.1**로, 공용 시스템 실행 파일의 별도 업그레이드를 피하고 사용하는 검사/변환 CLI가 호환됨을 합성 미디어로 검증했다. [ffprobe 공식 옵션](https://ffmpeg.org/ffprobe.html), [FFmpeg 공식 문서](https://ffmpeg.org/ffmpeg.html)를 확인했다. 시스템 실행 파일은 저장소/lockfile에 포함하지 않으며 위 버전을 재현 기준으로 기록한다.

Gemini SDK는 설치하지 않고 Python 표준 라이브러리로 공식 REST 계약을 구현했다. [Files API](https://ai.google.dev/gemini-api/docs/files), [generateContent 영상 이해](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding), [구조화 출력](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)의 등록 헤더·준비 상태·fileData·videoMetadata·responseFormat을 확인했다. [FastAPI 별도 무거운 작업 안내](https://fastapi.tiangolo.com/tutorial/background-tasks/), [Pydantic 모델](https://docs.pydantic.dev/latest/concepts/models/), [React effect 정리](https://react.dev/reference/react/useEffect)도 확인했다. 실제 선택 모델의 비용·권한·품질은 샘플 시험 시 다시 확인한다.

코드 탐색은 codebase-memory의 list_projects → index_repository → graph/snippet/search를 먼저 사용했다. 재인덱싱 후에도 M1 파일이 누락되어 해당 코드와 새 코드의 분석은 파일/테스트 도구로 보완했다. 원본 명세 4개·Excel·AGENTS.md는 수정하지 않았다.

## 다음 단계

M3: 저장된 관찰/허용 근거 목록을 사용하는 반려견·보호자 병렬 평가, Gemini/GPT/Claude 어댑터와 확정 규칙의 프로그램 집계, 부분 결과 조회. q23·4영역·②④·애매한 시간 경계는 계속 미정으로 보존한다. 실제 영상·키가 제공되면 M2 실 API/근거 시간·오디오 품질 검증을 별도로 수행한다.
