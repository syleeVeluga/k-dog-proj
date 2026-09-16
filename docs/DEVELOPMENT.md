# K-DOG 개발 실행 안내

> 2026-09-16 기준. 도메인 층(카탈로그·계약·계산)·입력 계약·화면은 42항목 판(2026-09-13)이고, 55항목 판 분석 파이프라인의 화면·라우트는 제거됐으며 남은 모듈은 P2에서 대체된다. 방향·범위·일정은 [변경 검토](K-DOG_변경검토_v1.0_20260915.md)를, 고객 요구사항은 `docs/최종 고객 문서/`를 따른다. 이 문서는 개발 환경과 검증 명령만 다룬다.

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

42항목 판 원본은 고객이 보낸 `docs/최종 고객 문서/03_행동_채점표_42항목_20260913.xlsx`(행동 채점표)와 `04_보호자_설문지_28문항.pdf`(설문)다. 원본을 수정하지 않는다. 이관기는 03 엑셀의 구조(4행 헤더, 시트별 9·24·9행, AD 영역코드, AY 척도)와 04 설문지의 구조(영역 A~E 머리, 1~28 번호, 7~9의 「해당 없음」 칸)를 검증하는 전용 도구이며 범용 업로드 처리기가 아니다.

```powershell
# backend/에서 실행: 파생 JSON을 재생성한다.
uv run --locked python -X utf8 -m app.import_catalogs
# 다른 읽기 전용 위치의 원본을 대조할 경우
uv run --locked python -X utf8 -m app.import_catalogs --customer-dir "D:/reference" --check
```

출력은 `resources/catalogs/behavior-v2.json`과 `survey-v2.json`(둘 다 `catalog-20260913-v2`)이다. 행동 항목마다 원본 시트·행·라벨 셀 좌표, 영역코드, 축, 척도구분(BI/ONE), 자료형(`scale`·`count`·`phase_count`·`auto_ratio`), 허용 점수를 기록하고, 파일 전체의 SHA-256을 남긴다. 참고 항목의 자료형은 B열 문구(`※횟수`·`※0~6`·`※자동 계산`)로 판정하며, 허용 점수는 C~G열에 라벨이 있는 값만이다 — 근거와 고객 확인 사항은 [P0 구현 계획](K-DOG_P0_구현계획_v1.0_20260916.md) 1·2장. 설문 문항은 `s01`~`s28`(번호·영역·「해당 없음」 허용·쪽)이며, 역채점(26~28)·분리 유형 규칙은 설문지에 없으므로 계산 규칙 파일(PR-4)에 둔다. 옛 30문항과의 대응은 `survey-v1-to-v2.json`(문장이 같은 쌍만 연결)에 있다. 설문지 PDF를 읽는 `pypdf`는 개발 의존성이며 런타임은 JSON만 읽는다. 참가자 답안이나 개인정보는 가져오지 않는다. 원본이 개정되면 기존 버전을 덮어 배포하지 말고 이관기와 항목집 버전을 함께 갱신하고 다시 검증한다.

옛 55항목 판의 `resources/source/` 엑셀과 `behavior-v1.json`·`survey-v1.json`은 저장된 옛 run을 읽는 코드가 남아 있는 동안 유지한다. 두 v1 JSON은 더 이상 재생성하지 않으며 `tests/test_catalog_import.py`가 원본 엑셀과 직접 대조한다.

## 데이터 계약 사용

42항목 판 계약은 `app.domain`에 있다. `catalog.py`(행동 42·설문 28 카탈로그), `contracts.py`(3상태 항목 점수 `ItemScore{score,status,reason}`, 채점자별 `ScoreSheet`, 8구간 `SessionSegments`, `SurveyAnswers`, 계산 결과 `ScoreResult`·`SurveyResult`), `validation.py`(카탈로그 대조: 채점 대상 41항목 정확히, 라벨 있는 점수만, 「해당 없음」 허용 문항만, 구간 시각이 영상 길이 안). `model_validate_json()`으로 구조를 검증한 뒤 `validation`의 문맥 검증을 호출한다. 구조 검사만으로 카탈로그 일치·영상 길이를 검증했다고 간주하지 않는다. 카탈로그는 서버가 제공하는 신뢰된 파일만 사용하며 사용자 업로드를 `excel_verified`로 받아들이지 않는다. 총점·등수 필드는 계약에 없고, 유형 라벨은 우리말 이름만 허용한다(Ainsworth 용어 거절).

## 계산 규칙

`app.scoring`은 03 엑셀 `여러쌍비교!D6:Z6` 수식과 01 §4를 그대로 옮긴 계산이다. 임계값·항목 역할·무효 규칙·설문 규칙은 코드가 아니라 `resources/rules/scoring-v2.json`에 있고, 고객 회신으로 해석이 바뀌면 그 파일만 고친다. `behavior_scores(sheet, catalog)`는 영역 6개(평균은 BI 항목, 폭은 BI·ONE, 정도는 ONE), 지표 4개(적응·회복·낯선 진정·동조율 — 3에서의 거리 차), 유형 2개(애착·사회성—사람), 기준 각성을 낸다. 무시 지시 준수·걷기 시행 유효성이 3이면 그 시행의 항목을 집계에서 빼고 관련 지표·유형을 `invalid`로 표시한다(계획 R5·R6). `survey_scores(answers, catalog)`는 26~28 역채점, 영역 A·B·C·E 평균(응답 문항만, 응답 수 기록), D 분리 유형 4종을 내며 총점은 없다. 반올림은 엑셀이 ROUND하는 자리(영역 평균·기운·정도·설문 평균)에서만 소수 2자리 half-up이다.

`tests/test_scoring_golden.py`가 05 예비촬영 6쌍의 입력으로 위 수식을 손으로 계산한 값과 프로그램 출력을 대조한다. 이것이 42항목 판 계산의 기준선이며, 규칙 파일을 바꾸면 이 시험의 기대값도 함께 바꿔야 한다.

## 전처리 (FFmpeg)

확정한 8구간으로 기준 영상을 잘라 채점 단계가 읽을 불변 클립을 만든다. 규칙은 `resources/rules/preprocess-v2.json`(자극 창 4곳 5초는 8 fps, 나머지 2 fps, 오디오 유지, 해상도·360 크롭은 07 장비 문서 뒤 결정)에 있다. 촬영에서 네 자극 시각을 기록한 뒤 전처리 메뉴 또는 CLI로 명시적으로 실행한다. Excel C8·C10의 사건 이후 5초를 기준으로 4개 창에 임시 적용하고, 해당 구간 끝에서 자른다. 미지정/구간 밖/끝과 같은 사건 시각은 보완 후 실행한다. 교수 회신은 별도 확인 요청에 대기 상태로 보존한다.

```powershell
# backend/에서 실행. --actor는 활성 운영자·관리자 계정.
uv run --locked python -X utf8 -m app.manage --data-dir "D:/kdog-data" preprocess <case_id> --actor manager
```

산출물은 `clips/<case>/<session>/<batch>/`의 mp4와 `clips.json`(원본 해시·길이·클립별 구간·fps·해시)이며, `changes`의 `preprocess.complete` 기록이 이 파일들을 참조해 백업·정리 대상에 포함시킨다. 구간이 기준 영상 길이를 넘으면 422, 확정 전이면 409로 거절한다.

## 패키징·리허설

릴리즈 ZIP은 커밋된 깨끗한 작업 트리에서 만든다. `git ls-files`의 `backend/app/**/*.py`와 `resources/` JSON·폰트, `frontend/dist`, 설치 스크립트, 루트 `README.md`·`pyproject.toml`·`uv.lock`·`PILOT_OPERATIONS.md`만 담고 자료·키·테스트·개발 문서는 넣지 않는다. `app.launcher.REQUIRED`가 실행 전 확인하는 파일은 42항목 판 카탈로그(`behavior-v2`·`survey-v2`)·`scoring-v2.json`·`preprocess-v2.json`·폰트·화면 빌드다.

```powershell
# 저장소 루트에서 실행
python -X utf8 scripts/build_release.py "releases/kdog-v0.2.0-windows-x64.zip"
python -X utf8 scripts/verify_release.py "releases/kdog-v0.2.0-windows-x64.zip"
```

`verify_release`는 ZIP을 새 한글·공백 경로에 풀어 손상 파일 거절, 새 가상환경 설치, HTTP 로그인·접수·재시작 후 재조회, 감독 프로세스 종료를 확인한다. 현재 Windows 호스트에서의 검증이며 깨끗한 OS·별도 PC 검증을 대체하지 않는다.

촬영 당일 흐름 리허설은 합성 영상 72쌍으로 접수 가져오기 → 설문 가져오기 → 영상 파일 2개 등록 → 8구간 확정·합성 자극 시각 기록 → 전처리를 끝까지 돌리고 단계별 시간·용량·클립 수·해시를 JSON으로 낸다. 임시 폴더(또는 `--data-dir`로 지정한 새 빈 폴더)만 쓰고 운영 자료는 열지 않는다. `tests/test_rehearsal.py`가 2쌍으로 같은 코드를 시험한다.

```powershell
# backend/에서 실행 (httpx는 개발 의존성)
uv run --locked python -X utf8 ../scripts/rehearsal.py --pairs 72 --report "D:/tmp/rehearsal.json"
```

## legacy

옛 55항목 판 계약·문맥 검증·계산·입력 형태는 `app.legacy`(`contracts_v1`·`validation_v1`·`scoring_v1`·`input_models_v1`)에 읽기 전용으로 있다. 55항목 분석·리포트·내보내기·평가 설정의 API 라우트와 화면은 제거됐고(PR-10), 그 백엔드 모듈(`analysis`·`worker` 단계·`evaluation`·`reporting`·`exports` 등)은 P2 채점 파이프라인이 대체할 때까지 worker 참조용으로만 남아 있다. 저장된 옛 run 행은 DB에 그대로 있다. 입력 계약은 `intake-2.0`(설문 `s01`~`s28`·「해당 없음」·촬영 메모 `note`·카메라 구분 없는 영상 파일 목록·기준 영상 위의 8구간 시작·끝 시각 `segments`와 확정 여부)이며, 접수 항목으로 순번(행사 안에서 유일)·동의 확인·보호자명·반려견 정보(`cases.dog_profile_json`: 견종·성별·나이·크기·함께 산 기간·입양 경로)를 받되 연락처는 받지 않는다(01 §7). 참가자 CSV/XLSX 양식의 접수 열은 생략할 수 있다(빈칸=미기재). DB `user_version`은 6이다. 설문은 CSV·Excel 가져오기로만 등록하고, 옛 `intake-1.0` 자료 폴더는 `Store` 첫 실행 때 자동 이관된다(`migration_note`에 버린 응답 기록). 자세한 범위는 [P1 구현 계획](K-DOG_P1_구현계획_v1.0_20260916.md) §2. 저장된 옛 run을 읽는 worker·리포트가 아직 이를 import하며, 각 모듈이 42항목 판으로 교체되는 PR에서 함께 삭제한다. legacy에 기능을 추가하지 않는다.

저장 계층은 검증 후 직렬화한 JSON을 불변 입력 파일로 저장하고 수정 시 새 revision을 만든다. 기본 도메인 검증은 새 run 자체의 관찰만 허용하며, `app.analysis`가 같은 참가자·세션·관련 입력/설정 해시와 명시적 reuse manifest를 확인한 경우에만 이전 관찰의 근거 ID를 연결한다. 이 원칙(불변 산출물·점유 토큰·삭제 상태 재확인·revision 고정·관찰 부족과 규칙 미정의 구분)은 42항목 판에서도 유지한다.

실제 데이터·영상·키·운영 로그는 저장소 밖에 둔다. 테스트 fixture는 가상 자료이며 실 AI 검증을 대체하지 않는다.
