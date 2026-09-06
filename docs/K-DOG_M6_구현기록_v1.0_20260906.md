# K-DOG M6 패키징·파일럿 준비 구현·검증 기록

버전: v1.0 · 작성일: 2026-09-06

기준: [구현 지시서 M6·T11·T13·T15](K-DOG_바이브코딩_구현지시서_v1.0_20260905.md), [PRD §11–12](K-DOG_PRD_v0.4_20260905.md). 설치·실행·백업·복원·비용 집계 명령은 [운영 안내](PILOT_OPERATIONS.md)를 따른다.

## 구현 범위

- `app.launcher`가 같은 Python·데이터 경로로 API/worker를 시작하고 실제 HTTP 인스턴스와 worker 잠금을 확인한 후 브라우저를 연다. Windows 자식 창은 숨기고 감독 창 하나를 유지한다. 중복 실행·기존 API/worker·포트 충돌·파일 누락·FFmpeg 누락을 검사한다.
- 자식 프로세스는 시작 신호를 기다려 Windows Job Object에 등록되기 전에 작업하지 않는다. 감독 창 종료/강제 종료/worker 장애 시 API·worker·미디어 하위 프로세스를 정리한다. 브라우저 탭 수명과 worker 수명은 분리한다. 미완료 작업의 복구는 기존 점유 토큰/불변 파일 검증을 따른다.
- `scripts/build_release.py`가 production UI를 빌드하고 앱 Python·잠금 파일·카탈로그/규칙·폰트/라이선스·운영 안내·Install/Start 스크립트만 ZIP에 포함한다. 파일 해시·기준 commit·작업 트리 변경 여부를 `release.json`에 기록하고 ZIP SHA-256을 별도로 생성한다. 테스트·가상 공급자·키·운영 DB·개발 가상환경·Node 도구는 패키징하지 않는다.
- `Install.cmd`는 온라인 설치 방식이다. 사전 설치된 uv·FFmpeg를 확인하고 `uv sync --locked --no-dev --python 3.14`로 패키지 자체의 `.venv`를 만든다. 관리자/개발자 비밀번호는 기존 숨김 입력 명령을 사용한다. 다른 PC에서도 Node.js·Git은 실행에 필요 없다. Python/FFmpeg를 묶은 오프라인 exe·서명된 설치 관리자는 이번 범위가 아니다.
- `usage-report` CLI로 행사/참가자/run/시도·공급자/모델/단계별 예약 호출·token 계량값·상태·시간을 집계한다. 재시도는 모두 포함하고 재사용은 이중 집계하지 않는다. 삭제 자료와 개발자 시험은 제외하고 키/오류 원문/프롬프트는 출력하지 않는다. OpenAI 등의 중첩 캐시/추론 token 계량값도 평탄화하여 보존한다.
- 선택적으로 출처·확인일·통화·정확한 모델별 계량 단가를 입력하여 부분/전체 추정을 계산한다. 미계측/응답 유실/단가 누락은 null로 유지한다. 실제 청구액이나 통화 예산 차단으로 표현하지 않는다. 기존 호출 횟수·출력 토큰 상한을 유지한다.

새 라이브러리·DB migration·프런트엔드 화면 변경은 없다. 원본 Excel·PRD·구현 지시서와 미정 계산 규칙은 변경하지 않았다.

## 검증 명령

```powershell
# backend/에서
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
uv run --locked python -X utf8 -m tests.pilot_scenario --output "$env:TEMP/kdog-m6-pilot.json"
# 다른 양수 시나리오도 선택 가능: --participants 21 --cameras 3 --seconds 180

# frontend/에서
npm run build
npm run test:e2e

# 저장소 루트에서: 새 출력 파일명만 허용
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py releases/kdog-m6.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py releases/kdog-m6.zip
git diff --check
```

`pilot_scenario`는 명시적 개발 시험으로 실제 미디어 검사, DB, 두 평가 분기, 점수, 리포트, 전체 파일 출력, 백업/복원을 수행한다. 공급자는 테스트 주입이며 운영 CLI에서 선택할 수 없다. 임시 데이터·영상은 저장소 밖에서 만들고 종료 후 정리한다. 원래 측정 JSON은 지정한 출력 경로에 남으며 기존 기록은 덮어쓰지 않는다.

## 합성 20명·2대·각 3분 최종 측정

Windows 11 10.0.26200, Python 3.14.2, FFmpeg 8.1.1. 640×360 10fps 회색 영상 + 카메라별 다른 사인파, H.264/AAC. 카메라별 파일 해시는 다르며 40개 영상 모두 실제 전체 디코딩을 통과했다. API는 실제 라우트의 in-process TestClient이고 worker는 참가자 1건씩/내부 평가 2분기 병렬이다. 네트워크 왕복·실 AI 지연·현장 비트레이트를 대표하지 않는다.

| 항목 | 결과 |
|---|---:|
| 참가자 / 영상 / 총 영상 길이 | 20명 / 40개 / 7,200초(120분) |
| 업로드 원본 바이트 | 50,067,680 |
| 입력·설문·영상·run 접수 | 3.177초 |
| worker 전체 / 참가자 중앙 / 최대 | 21.967 / 1.095 / 1.185초 |
| 전체 PDF ZIP·XLSX·CSV 생성/조회/구성 검증 | 3.380초 |
| PDF ZIP / XLSX / CSV ZIP 바이트 | 1,163,314 / 104,292 / 15,211 |
| 백업 + 새 폴더 복원 + 상태 재조회 | 4.388초 |
| 완료 데이터 폴더 바이트 | 58,897,009 |
| 가상 관찰 / 평가 / 설명 호출 | 40 / 40 / 20 |
| 실제 외부 AI 호출 | 0 |
| 실제 공급자 사용량·청구 비용 | 미측정(null) |

20명 전원 scored + ready 리포트를 확인했다. PDF ZIP에 20명 ID가 모두 있고 XLSX 요약/행동 1,100행·CSV 요약에 누락이 없음을 실제 파일 재파싱으로 확인했다. 원본 30문항 응답을 입력했으며 미정 q23/4영역/②④ 규칙은 기존 보류 계약을 유지했다. 백업 복원 후 20개 완료 run이 유지되었다. 위 시간은 20명 상한·완료 시간 보장·실 AI 성능 지표가 아니다.

## 새 설치 환경 및 회귀 검증

- 새 한글·공백 경로에 ZIP을 추출하고 새 운영 `.venv`를 설치했다. 기존 작업 가상환경을 복사하지 않았다. 패키지 Python으로 실제 loopback HTTP 로그인·참가자 저장·서버 재시작·같은 ID 재조회를 확인했다.
- 손상된 UI 파일을 설치 전에 거절하고, 외부 `UV_PROJECT_ENVIRONMENT`가 설정되어도 다른 환경을 수정하지 않는다. 설치 검증은 기존 Windows 호스트의 uv·FFmpeg·Python을 사용했다. 별도 물리 PC/깨끗한 OS VM 검증으로 표기하지 않는다.
- Python 전체 **122개**, 브라우저 **11개**, production build, 원본 행동 55/설문 30개 해시 대조가 통과했다. 신규 M6 회귀 9개는 실제 프로세스/잠금/포트/하위 프로세스와 비용 누락·재시도·삭제·재사용을 검사한다. 기존 REST 어댑터 시험에도 중첩 캐시 token 보존 검사를 추가했다.
- 기존 httpx TestClient deprecation 및 Node NO_COLOR 경고는 실패가 아니며 관련 없는 도구 교체를 하지 않았다. UI 변경이 없어 기존 360px/데스크톱 회귀를 수행했고 새 화면 스크린샷은 필요하지 않았다.

## Cold review

구현·첫 전체 검증 뒤 요구사항/변경 코드를 별도로 다시 읽고 실패 경로를 검토했다. 별도 에이전트는 사용하지 않았다.

| 발견 | 조치·검증 |
|---|---|
| 감독 프로세스 EOF 감시만으로는 FFmpeg 손자 프로세스가 남을 수 있음 | Windows kill-on-close Job Object + 등록 후 시작 신호. 실제 자식/손자 프로세스 종료와 감독 강제 종료 시 잠금 해제 회귀 통과 |
| 예약 없는 과거 호출을 재사용처럼 제외하면 전체 추정을 완전하게 보일 수 있음 | 명시적 reused와 미계측 단계를 구분하고 미계측이 하나라도 있으면 전체 추정 null. 회귀 통과 |
| 평탄한 usage 수집이 OpenAI 캐시 token 세부 계량값을 버림 | 정수 token 필드만 중첩 경로로 보존, REST 모의 응답/집계 회귀 통과 |
| 호스트의 UV_PROJECT_ENVIRONMENT로 설치 위치가 다른 가상환경을 가리킬 수 있음 | 설치 프로세스에서 패키지 `.venv`로 고정하고 새 설치 시험에서 외부 경로 미생성 확인 |

설치 검증 중 Windows PowerShell에서 `Get-FileHash` 가용성이 달라지는 문제도 발견해 내장 .NET SHA-256으로 대체했다. 정상 ZIP·손상 ZIP의 새 환경 설치 검사도 통과했다.

## 의존성·공식 문서 확인

2026-09-06 인터넷 검색과 공식 PyPI/npm 메타데이터, 공식 릴리스/API 문서를 확인했다. 앱 라이브러리 최신 안정 버전은 기존 잠금과 같아서 변경하지 않았다. Python requires-python과 React peer/Node engines도 현재 Python 3.14.2·Node 24.13.0을 허용한다.

| 패키지 | 최신 안정 = 선택 버전 | 확인 출처 |
|---|---|---|
| Pydantic / FastAPI / Uvicorn | 2.13.5 / 0.141.1 / 0.52.4 | [Pydantic](https://pypi.org/pypi/pydantic/json), [FastAPI](https://pypi.org/pypi/fastapi/json), [Uvicorn](https://pypi.org/pypi/uvicorn/json) |
| openpyxl / ReportLab / Pillow | 3.1.5 / 5.0.1 / 12.3.0 | [openpyxl](https://pypi.org/pypi/openpyxl/json), [ReportLab](https://pypi.org/pypi/reportlab/json), [Pillow](https://pypi.org/pypi/pillow/json) |
| httpx / pypdf | 0.28.1 / 6.17.0 | [httpx](https://pypi.org/pypi/httpx/json), [pypdf](https://pypi.org/pypi/pypdf/json) |
| React / DOM / types / DOM types | 19.2.8 / 19.2.8 / 19.2.18 / 19.2.7 | [React](https://registry.npmjs.org/react/latest), [DOM](https://registry.npmjs.org/react-dom/latest), [types](https://registry.npmjs.org/@types/react/latest), [DOM types](https://registry.npmjs.org/@types/react-dom/latest) |
| Playwright / TypeScript / Vite | 1.63.0 / 7.0.2 / 8.2.2 | [Playwright](https://registry.npmjs.org/@playwright/test/latest), [TypeScript](https://registry.npmjs.org/typescript/latest), [Vite](https://registry.npmjs.org/vite/latest) |

호스트 도구 uv 최신 **0.12.10**([PyPI](https://pypi.org/pypi/uv/json)), FFmpeg 최신 **9.0.1**([공식 릴리스](https://ffmpeg.org/download.html))를 확인했다. 검증에는 기존 **uv 0.11.18 / FFmpeg 8.1.1**을 유지했다. 기존 M2–M5 미디어 환경과 비교하고 호스트 도구의 관련 없는 전역 업그레이드를 피하기 위한 선택이며 패키지에 구버전 실행 파일을 재배포하지 않는다. 다른 도구 버전/실제 PC는 별도 설치·미디어 시험 대상이다.

[uv locked/no-dev 동작](https://docs.astral.sh/uv/concepts/projects/sync/), [Python subprocess](https://docs.python.org/3.14/library/subprocess.html), [FastAPI 릴리스](https://fastapi.tiangolo.com/release-notes/), [Vite 런타임 조건](https://vite.dev/guide/), [Windows Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [Job Object 제한 구조](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)를 확인했다. Windows API는 Python 표준 ctypes로 호출한다.

codebase-memory는 list_projects 후 fast/full 갱신에도 M0 196개 노드만 반환했다. search_graph/search_code로 최신 심볼이 나오지 않아 제한을 알리고 파일 탐색으로 보완했다.

## 남은 외부 검증

M6의 개발 구현·합성 시나리오·새 경로 설치 검증과 **현장 사용 준비 완료**는 구분한다. 실제 제공 영상·공급자 키를 사용한 연결/품질/사용량/청구액, 실제 PC/깨끗한 OS 설치, 현장 촬영 비트레이트·납기·저장/보관 조건은 미검증이다. 통화 예산 차단, 확정되지 않은 q23·4영역·②④ 계산은 구현 완료로 주장하지 않는다. 승인된 실사용 자료와 책임자의 규칙/목표가 주어지면 운영 안내의 실제 파일럿 절차로 확인한다.
