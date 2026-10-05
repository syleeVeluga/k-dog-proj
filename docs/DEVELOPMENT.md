# K-DOG 개발 실행 안내

버전: v1.5 · 2026-10-04 · S1.1 / 통합명세 v1.3

개발 기준은 [S00–S17 계획](개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md), 검증 근거는 [실행 기록](개발반영_20261003/K-DOG_구현실행기록_v1.0_20261003.md)과 [인수 대장](개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md)을 따른다. 실제 영상·장비 검증과 미확정 자료/정책은 [후속 대장](개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)에 있다.

## 환경과 실행

React 빌드를 FastAPI가 제공하고 SQLite·불변 파일·별도 worker를 사용한다. Python 3.14, Node.js 24, uv, npm, FFmpeg/ffprobe가 필요하다. 패키지 버전은 lockfile에 고정하며 공식 최신/선택 버전·호환성·확인일은 실행 기록에 남긴다. 새 의존성 사용 전 공식 문서와 registry를 확인한다.

저장소 루트에서 처음 한 번 실행한다.

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked
uv run --locked python -X utf8 -m app.manage create-user manager --role admin
uv run --locked python -X utf8 -m app.launcher
```

계정 비밀번호는 숨김 프롬프트로 입력한다. 기본 계정은 없다. 런처가 API와 worker를 함께 시작하므로 별도 worker를 중복 실행하지 않는다. 기본 주소는 `http://127.0.0.1:8000`, 자료는 `%LOCALAPPDATA%/K-DOG/data`다. 코드 저장소 내부의 데이터 경로는 거절한다. 기존 자료는 [운영 안내](PILOT_OPERATIONS.md)의 명시 초기화 후 실행한다. 키가 없으면 AI 요청이 실패하며 가상 결과로 자동 전환하지 않는다.

## 자동 검증

```powershell
# backend/에서 실행
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check
# frontend/에서 실행
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

브라우저 시험은 8765 포트의 임시 S1 서버와 저장소 밖 합성 자료를 사용한다. `npm run test:e2e` 한 번으로 현행 제품 전체를 실행하며 판본 환경변수나 구판 UI 실행은 필요하지 않다. 공통 권한·보안·대상 맥락·미저장 입력·새로고침·모바일·키·백업 보호를 S1 fixture에서 검사한다. 교체된 구판 UI 시험의 대응 관계는 [S15 기록](개발반영_20261003/K-DOG_PR-S15_배포와통합인수_v1.0_20261003.md)에 있으며 역사적 API fixture는 backend에 보존한다. 임시 자료와 백업은 같은 임시 상위 폴더에 격리하고 screenshot은 무시되는 `frontend/test-results/`에 둔다.

저장소 루트에서 `git diff --check`, 문서 링크·원본 hash 검사, `graft build` 후 `graft check`도 수행한다. source 탐색/호출 관계는 graft를 먼저 사용한다.

## 원본과 현행 계약

S1 고객 원본은 로컬 전용 `docs/요구사항_20261003/`이다. [원본 목록](개발반영_20261003/K-DOG_원본자료목록_v1.0_20261003.md)의 hash와 일치해야 한다. `app.import_catalogs --spec 20261002 --check`는 통합명세/계산 원본에서 S1의 8개 추출 자산을 대조한다. `--spec`의 기본값도 `20261002`이며 `app.import_catalogs_v4`에는 실행 CLI가 없다. 원본 재추출은 검토한 경우에만 `--check` 없이 실행한다. 참가자 응답·영상·빈양식 미수령분을 임의로 만들지 않는다.

`domain/*_v4.py`가 S1 계약이며 `intake-4.0`, `catalog-20261002-s1.1`을 사용한다. 행동 카탈로그 90행은 직접 수치 83·자동 4·메모 3으로 구분하고 `개59` 추가 메모를 수치 분모에 넣지 않는다. 설문 원문 Q01–Q28의 28문항을 보존하며 Q26–Q28 감정의 일관성 문항의 역채점도 반영한다. 원척도·역채점·결측 정책은 S1 설문 정책 자산을 따른다. strict 모델 검사와 출처·카탈로그·관찰창·권한의 문맥 검증을 함께 수행한다.

`docs/큐브전달_20260929/`의 역사 원본15개는 2026-10-04 저장소에서 삭제하고 로컬 전용으로 제외했다. 이전 근거는 commit `8b9c960`에 남는다. 역사 원본 대조가 필요하면 담당자가 제공한 해시 검증 전달 묶음을 별도 확보하고 `app.import_catalogs --spec 20260929 --customer-dir <로컬_원본_폴더> --check`를 실행한다. `*-v3.json`은 역사 카탈로그와 현재도 쓰는28문항 설문 근거다. 역사 원본이 없으면 원본 의존 시험2개만 명시 skip하며 원본 대조 통과로 표시하지 않는다. v1/v2/v3 코드/자산 중 공통 worker/저장/시험에서 참조하는 것만 남아 있으며 새 제품 쓰기 경로는 S1이다. 이 값들을 S1 기대값으로 사용하지 않는다. G01 빈 채점양식과 G04 정정 원본 확인 전 실제 S1 Excel 점수 가져오기는 비활성이다. 검수 참고파일 등록은 점수 가져오기와 별개다.

## 전처리와 실행

실제 8구간·사건·카메라 offset을 확정하고 명시 요청으로 실행한다. S1은 공통시각과 각 영상 시각, 원본/변환본/AI용 클립을 구분하며 AI용 1fps 실제 프레임 PTS와 hash를 고정한다. INSV 수신은 보관이며 직접 분석 지원 선언이 아니다. 규칙은 `resources/rules/preprocess-v4.json`이다.

```powershell
# backend/; 화면에서 확인한 현재 입력 revision과 새 요청 ID를 지정
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" preprocess CASE_ID --actor manager --expected-revision 7 --request-id PREPROCESS-001
```

같은 요청 재시도에는 동일 request ID를 쓴다. 다른 입력·새 처리에는 새 ID와 현재 revision을 쓴다. 성공/실패·원본 부모 hash·실제 fps·출력 hash가 batch에 고정된다. 메뉴 방문이나 입력 저장으로 자동 실행하지 않는다. AI 실행은 현재 모델/설정/예산을 고정하며 실제 공급자 호출과 재시도에는 비용이 발생할 수 있다.

## 패키지와 종단 리허설

ZIP은 커밋된 깨끗한 작업 트리에서 만든다. S1 카탈로그·계산/문장/비교 규칙·HTML/CSS 템플릿·로컬 폰트, 운영 안내·계획·후속 문서와 실행 런타임을 포함한다. 런타임은 python.org 공식 CPython embeddable(고정 SHA-256, `releases/.cache/`에 보관)에 `uv export --locked --no-dev` 결과를 hash 필수·wheel 전용으로 설치한 `runtime/python`, 그리고 [FFmpeg 최소 빌드](../scripts/ffmpeg/README.md) 결과를 `build.json` 해시로 확인한 `runtime/ffmpeg`다. FFmpeg 빌드 결과가 없거나 해시가 다르면 ZIP을 만들지 않는다. `오픈소스고지.txt`에는 고정 고지문과 동봉한 Python·npm 패키지 목록을 넣는다. 고객 원본·영상·키·런타임 자료와 개발용 시험·빌드·실측 스크립트는 제외한다. 개발 명령과 시험 근거는 `release.json`의 commit에 해당하는 소스 저장소에서 확인한다. `app.launcher.REQUIRED`가 S1 필수 자산을 검사한다.

```powershell
# 저장소 루트; 프로젝트 Python 사용
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py "releases/kdog-s1-windows-x64.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py "releases/kdog-s1-windows-x64.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/issue_release.py "releases/kdog-s1-windows-x64.zip" --customer SCHOOL-1 --admin manager --developer keyman
# 사용자 설치형(uv·FFmpeg 직접 설치): 런타임 없이 만들고, PATH에 uv·FFmpeg가 있고 인터넷이 되는 PC에서 검증
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py --variant online "releases/kdog-s1-windows-x64-online.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py "releases/kdog-s1-windows-x64-online.zip"
# backend/
uv run --locked python -X utf8 ../scripts/rehearsal.py --pairs 2 --seconds 10 --report "D:/tmp/s1-rehearsal.json"
```

`verify_release`는 PATH를 Windows 기본 경로로 제한해 uv·Python·FFmpeg가 없는 상태로 현재 Windows의 새 한글/공백 경로에 ZIP을 풀고, `Start.cmd --check`의 손상 거절, 내장 Python·FFmpeg 사용, S1 health·접수·재시작 조회·감독 종료를 검사한다. 이어서 같은 ZIP으로 합성 고객 `VERIFY` 발행 패키지(무작위 비밀번호, admin·developer)를 만들어 제품 파일 평문 노출이 없는지, 틀린 키와 헤더·본문 변조가 아무것도 만들지 않는지, 키 설치·계정·바로가기, 발행 관리자 로그인·접수, 개발자 키 설정 API 접근, 재설치 후 자료·계정 유지를 검사한다 (설치 위치·바로가기·자료는 임시 폴더). `issue_release`는 고객별 발행 패키지와 발행 키를 만든다. 사용법과 전달 규칙은 [운영 안내](PILOT_OPERATIONS.md)의 발행 절을 따른다. 패키지 안의 FFmpeg로 전처리 시험을 다시 돌리려면 풀린 `runtime/ffmpeg/bin`을 PATH 맨 앞에 두고 backend 시험을 실행한다. 깨끗한 OS와 물리 PC3대는 별도 실측이다.

`--variant online`은 S15 방식의 사용자 설치형 ZIP이다. `runtime/` 없이 `backend/pyproject.toml`·`backend/uv.lock`과 `scripts/windows/online/`의 `Install.cmd`·`install.ps1`·`Start.cmd`, 사용자 설치형 `오픈소스고지.txt`(글꼴·npm 목록)를 넣고 (npm 라이선스 전문은 `licenses/npm`. 앱은 `runtime/` 폴더가 있으면 내장 FFmpeg만 쓰므로 이 ZIP에는 `runtime/`이 없어야 한다) `release.json`에 `"variant": "online"`을 기록한다. FFmpeg 빌드 결과와 embeddable Python이 필요 없다. `issue_release`는 이 ZIP을 거절한다 (발행은 포터블 ZIP만). `verify_release`는 `variant`를 보고 이 ZIP을 따로 검증한다: 설치 전 `Start.cmd`가 `Install.cmd`를 안내하는지, 손상 시 `.venv`를 만들기 전에 거절하는지, 틀린 `UV_PROJECT_ENVIRONMENT`·`PYTHONHOME`·`PYTHONPATH`를 무시하고 `backend/.venv`(Python 3.14)와 PATH FFmpeg를 쓰는지, 로그인·접수·`Start.cmd` 재시작 조회·감독 종료를 검사한다. 이 검증은 uv·FFmpeg가 PATH에 있고 인터넷(또는 uv 캐시)이 되는 PC에서만 돈다.

리허설은 Forms 접수/설문→3개 독립 촬영 계정 동시 수신→CAM1/2/3 연결→실제 구간/offset 확정→FFmpeg 전처리→독립 사람 원자료→계산/최종결과→실제 HTML/PDF 발급과 hash 고정을 검증한다. 모든 항목의 미관찰 사유가 명시된 합성 시트를 사용하며 실제 행동 점수를 발명하지 않는다. 총 벽시계와 단계별 시간을 분리한다. 기본은 72쌍/45초이며 빈 임시 폴더만 쓴다. 외부 AI 호출은 0건, 논리 클라이언트3개이며 실제 3PC나 1GB 영상 시간의 대체 증거가 아니다.

실측 준비 CLI `scripts/benchmark_s1.py`의 `--template`, `--schema`, `--manifest ... --data-dir ... --actor ... --output ...` 사용은 [S16](개발반영_20261003/K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md)을 따른다. 읽기 전용 집계이며 실제 AI 실행이나 운영 승인 도구가 아니다.
