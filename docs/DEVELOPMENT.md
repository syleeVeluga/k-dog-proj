# K-DOG 개발 실행 안내

> 2026-09-15 기준. 현행 코드는 55항목 판(2026-09-04)으로 구현되어 있으며, 고객이 2026-09-13에 보낸 42항목 판으로 도메인 층을 다시 만드는 작업을 시작한다. 방향·범위·일정은 [변경 검토](K-DOG_변경검토_v1.0_20260915.md)를, 고객 요구사항은 `docs/최종 고객 문서/`를 따른다. 이 문서는 개발 환경과 검증 명령만 다룬다.

## 구성

React 빌드를 FastAPI가 제공하고, SQLite와 별도 worker 프로세스를 사용한다. `app.launcher`가 API·worker를 함께 시작하며, 이때 worker를 따로 시작하지 않는다. Python 3.14, Node.js 24, `uv`, npm, FFmpeg/ffprobe를 사용한다. 사용자 PC 설치·백업·복원은 [운영 안내](PILOT_OPERATIONS.md), Gemini 요청 계약은 [Gemini 영상 API 적용 계획](K-DOG_Gemini영상API_적용계획_v1.0_20260907.md)을 따른다.

## 앱 최초 실행

저장소 루트에서 시작한다.

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked
# 처음 한 번만 실행한다. 비밀번호는 숨김 프롬프트로 두 번 입력한다.
uv run --locked python -X utf8 -m app.manage create-user manager --role admin
uv run --locked python -X utf8 -m app.launcher
```

`http://127.0.0.1:8000`에서 접속한다. 기본 계정은 없다. 운영 관리자가 직원 계정을 발급한다. 데이터는 기본 `%LOCALAPPDATA%/K-DOG/data`에 저장하며 코드 저장소 안의 데이터 경로는 거절한다. worker만 따로 실행할 때는 `backend/`에서 `uv run --locked python -X utf8 -m app.manage worker`를 쓴다. 키가 없을 때 가상 결과로 자동 전환하지 않는다.

## 검증

```powershell
# backend/에서 실행
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
```

첫 명령은 `backend/.venv`에 잠금 의존성을 설치한다. `--check`는 `resources/catalogs/`의 JSON과 원본 엑셀을 대조하며 어떤 파일도 변경하지 않는다. Python `-X utf8`은 Windows의 한글 입출력 인코딩을 고정한다. 시험 명령은 반드시 `backend/`에서 실행한다. 다른 폴더에서는 `tests` 시작 폴더를 import할 수 없어 `Start directory is not importable` 오류가 난다.

```powershell
# frontend/에서 실행
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

브라우저 테스트는 8765 포트에 임시 서버와 테스트 전용 가상 worker를 실행하고 저장소 밖 임시 폴더·가상 계정·가상 영상 바이트를 사용한다. 운영 데이터는 열지 않는다. 스크린샷은 무시되는 `frontend/test-results/`에 둔다. 실제 영상·AI 정확도 검증이 아니다.

## 원본 항목집 이관

원본 엑셀은 `resources/source/`에 둔다. 원본을 수정하지 않는다. 이관기는 현재 템플릿의 구조를 검증하는 전용 도구이며 범용 업로드 처리기가 아니다.

```powershell
# backend/에서 실행: 파생 JSON을 재생성한다.
uv run --locked python -X utf8 -m app.import_catalogs
# 다른 읽기 전용 위치의 원본을 대조할 경우
uv run --locked python -X utf8 -m app.import_catalogs --source-dir "D:/reference" --check
```

출력은 `resources/catalogs/`의 버전 있는 JSON이다. 각 결과는 원본 파일명·SHA-256·시트·행·셀을 기록한다. 참가자 답안이나 개인정보는 가져오지 않는다. 원본이 개정되면 기존 버전을 덮어 배포하지 말고 이관기와 항목집 버전을 함께 갱신하고 다시 검증한다.

현재 `resources/source/`의 55항목·30문항 엑셀과 `behavior-v1.json`·`survey-v1.json`은 42항목 판 이관(`behavior-v2`·`survey-v2`)이 끝날 때까지만 유지한다. 42항목 판 원본은 `docs/최종 고객 문서/03_행동_채점표_42항목_20260913.xlsx`와 `04_보호자_설문지_28문항.pdf`다.

## 데이터 계약 사용

`app.domain.contracts`의 `model_validate_json()`으로 요청·저장 파일을 검증한 뒤 `app.domain.validation`의 문맥 검증을 호출한다. 구조 검사만으로 영상 소속·시간·근거 참조를 검증했다고 간주하지 않는다. 카탈로그는 서버가 제공하는 신뢰된 파일만 사용하며 사용자 업로드를 `excel_verified`로 받아들이지 않는다.

저장 계층은 검증 후 직렬화한 JSON을 불변 입력 파일로 저장하고 수정 시 새 revision을 만든다. 기본 도메인 검증은 새 run 자체의 관찰만 허용하며, `app.analysis`가 같은 참가자·세션·관련 입력/설정 해시와 명시적 reuse manifest를 확인한 경우에만 이전 관찰의 근거 ID를 연결한다. 이 원칙(불변 산출물·점유 토큰·삭제 상태 재확인·revision 고정·관찰 부족과 규칙 미정의 구분)은 42항목 판에서도 유지한다.

실제 데이터·영상·키·운영 로그는 저장소 밖에 둔다. 테스트 fixture는 가상 자료이며 실 AI 검증을 대체하지 않는다.
