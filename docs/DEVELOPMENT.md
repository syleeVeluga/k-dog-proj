# K-DOG 개발 실행 안내

## 현재 실행 범위

M2까지 인증·입력·영상 검사·Gemini 관찰·근거 조회를 실행할 수 있다. React 빌드를 FastAPI에서 제공하며 SQLite와 별도 worker를 사용한다. 실제 Gemini 호출·영상 품질은 샘플 제공 후 검증할 예정이다. Python 3.14, Node.js 24, `uv`와 npm, FFmpeg/ffprobe를 사용한다. 명령은 저장소 루트에서 시작한다.

## 앱 최초 실행

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked
# 처음 한 번만 실행한다. 비밀번호는 숨김 프롬프트로 두 번 입력한다.
uv run --locked python -X utf8 -m app.manage create-user manager --role admin
uv run --locked python -X utf8 -m app.manage serve
```

`http://127.0.0.1:8000`에서 접속한다. 기본 계정은 없다. 운영 관리자로 직원 계정을 발급한다. 데이터는 기본 `%LOCALAPPDATA%/K-DOG/data`에 저장하며 코드 저장소 안의 데이터 경로는 거절한다. 서버를 종료해도 같은 데이터 폴더를 사용하면 다시 조회할 수 있다. 자세한 입력 순서·계정·다른 데이터 위치·개발 서버·제약은 [M1 구현 기록 및 운영 안내](K-DOG_M1_구현기록_v1.0_20260906.md)를 따른다.

## 검증

M2는 서버와 별도로 `backend/`에서 `uv run --locked python -X utf8 -m app.manage worker`를 실행한다. 모델·키 환경 설정, FFmpeg 버전, 재시도·재사용·복구와 실 API 미검증 범위는 [M2 실행·검증 기록](K-DOG_M2_구현기록_v1.0_20260906.md)을 따른다. 키가 없을 때 가상 결과로 자동 전환하지 않는다.

저장소 루트에서 시작한다.

```powershell
cd backend
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
```

첫 명령은 `backend/.venv`에 잠금 의존성을 설치한다. 테스트는 원본 이관·데이터 계약·M1 API·실제 서버 프로세스 재시작을 검증한다. `--check`는 기존 JSON과 원본을 대조하며 어떤 파일도 변경하지 않는다. Python `-X utf8`은 Windows의 한글 입출력 인코딩을 고정한다.

```powershell
# frontend/에서 실행
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

브라우저 테스트는 8765 포트에 임시 서버와 테스트 전용 가상 worker를 실행하고 저장소 밖 임시 폴더·가상 계정·가상 영상 바이트를 사용한다. 운영 데이터는 열지 않는다. 종료 후 서버는 정리하며 스크린샷은 무시되는 `frontend/test-results/`에 둔다. 실제 영상·AI 정확도 검증이 아니다. Python M2 테스트는 FFmpeg로 생성한 색상 영상·사인파의 실제 검사/변환과 가상 공급자 계약 시험을 구분한다.

## 원본 항목집 이관

원본은 `docs/큐브_행동채점표_최종양식_55항목_20260904.xlsx`, `docs/큐브_통합설문_최종양식_20260904.xlsx`다. 원본을 수정하지 않는다. 현재 템플릿의 구조를 검증하는 전용 이관기이며 범용 업로드 처리기가 아니다.

```powershell
# backend/에서 실행: 파생 JSON 2개를 재생성한다.
uv run --locked python -X utf8 -m app.import_catalogs
# 원본의 다른 읽기 전용 위치를 사용할 경우
uv run --locked python -X utf8 -m app.import_catalogs --source-dir "D:/reference" --check
```

출력은 `resources/catalogs/`의 버전 있는 JSON 2개다. 행동 A:I 중 항목 정보와 비어 있지 않은 C:G 선택지만 이관한다. 설문은 A2 안내와 A6:E35 문항 메타데이터만 이관한다. 참가자 답안이나 개인정보는 가져오지 않는다. 각 결과는 원본 파일명·SHA-256·시트·행·선택지 셀을 기록한다. 원본이 개정되면 기존 버전을 덮어 배포하지 말고 이관기와 항목집 버전을 함께 갱신하고 다시 검증한다.

## 데이터 계약 사용

`app.domain.contracts`의 `model_validate_json()`으로 요청·저장 파일을 검증한 뒤 `app.domain.validation`의 문맥 검증을 호출한다. 구조 검사만으로 영상 소속·시간·근거 참조를 검증했다고 간주하지 않는다. 카탈로그는 서버가 제공하는 신뢰된 파일만 사용하며 사용자 업로드를 `excel_verified`로 받아들이지 않는다.

`resolve_branch_scores()`는 확정 선택지의 점수 조회만 수행한다. 행동 자동 판정, 미정 경계 해결, 영역 평균/역채점/반올림 실행기는 M3에서 구현한다. q23 원응답은 보존하고 `resources/rules/pending-v1.json`의 미정 상태를 임의 계산으로 대체하지 않는다.

RunInput의 `frozen`은 필드 재할당을 막지만 내부 dict까지 동결하지 않는다. 저장 계층은 검증 후 직렬화한 JSON을 불변 입력 파일로 저장하고 수정 시 새 revision을 만든다. M1의 `intake-1.0` manifest와 M2의 검사된 RunInput은 분리하며, 검사된 입력은 성공 prepare 산출물에 고정한다. 기본 도메인 검증은 새 run 자체의 관찰만 허용한다. `app.analysis`가 같은 참가자·세션·관련 입력/설정 해시와 명시적 reuse manifest를 확인한 경우에만 이전 관찰의 근거 ID를 연결한다.

실제 데이터·영상·키·운영 로그는 저장소 밖에 둔다. 테스트 fixture는 가상 자료이며 실 AI 검증을 대체하지 않는다. 완료 범위와 남은 작업은 [진행 기록](IMPLEMENTATION_STATUS.md)을 확인한다.
