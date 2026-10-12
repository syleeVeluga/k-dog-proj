# PR-D04 사용자 설치형 패키지

버전: v1.0 · 2026-10-05 · 상태: 구현 완료 (2026-10-05) · 선행: D01–D03 · 기준: main `1f67d50`

상위: [설치·배포 개선 계획](K-DOG_설치배포개선계획_v1.0_20261005.md). 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치: `veluga/d04-user-install` · PR 제목: `release: uv·FFmpeg 직접 설치형 패키지 추가`

## 문제와 결과

D01에서 Python·FFmpeg 내장 포터블 ZIP으로 바꾸면서 S15의 사용자 설치 방식(사용자가 uv·FFmpeg를 설치하고, `Install.cmd`가 인터넷으로 Python 3.14와 잠금 의존성을 받음)이 없어졌다. 2026-10-05 사용자 요청: **포터블 빌드는 그대로 두고, 기존처럼 사용자가 일부 라이브러리를 직접 설치하는 버전도 만든다.**

이 PR 이후 `build_release.py`는 두 가지 ZIP을 만든다.

| 구분 | 명령 | 내용 | 사용자 준비물 |
| --- | --- | --- | --- |
| 포터블 (기본, 변경 없음) | `build_release.py <zip>` | `runtime/python`·`runtime/ffmpeg` 내장, `issue_release` 발행 원본 | 없음 |
| 사용자 설치형 (신규) | `build_release.py --variant online <zip>` | `runtime/` 없음, `backend/pyproject.toml`·`uv.lock`, `Install.cmd`·`install.ps1`·`Start.cmd` | uv, FFmpeg/ffprobe(PATH), 최초 설치 때 인터넷 |

결정과 범위:

- 사용자 설치형은 S15처럼 **평문 ZIP**이다. 암호화·발행 키·발행 계정·바탕화면 아이콘은 없다 (D03은 내장 Python으로 설치 프로그램을 돌리므로 그대로 쓸 수 없다). `issue_release`는 이 ZIP을 명확한 메시지로 거절한다.
- 계정은 S15처럼 설치 중 관리자·개발자 이름과 숨김 비밀번호를 묻는다. Enter로 생략할 수 있다.
- 포터블·발행 흐름과 S1 기능은 바꾸지 않는다.

## 파일별 변경

| 파일 | 변경 | 내용 |
| --- | --- | --- |
| `scripts/build_release.py` | 수정 | `--variant {portable,online}` (기본 portable). online은 런타임 조립을 건너뛰고 `pyproject.toml`·`uv.lock`·online 스크립트를 넣는다. `release.json`에 `variant`를 기록하고 `python` 버전은 포터블에만 쓴다. 고지 생성은 고정 고지 파일을 인자로 받고, 동봉 Python 패키지가 있을 때만 그 목록 머리글을 넣는다 |
| `scripts/windows/online/Install.cmd`, `install.ps1`, `Start.cmd` | 신설 | S15 스크립트(D01 직전 `f8fdbbe`의 `scripts/windows/`)를 복원하고 보강: `PYTHONHOME`·`PYTHONPATH` 제거, 누락 파일 안내, 인터넷 오류 안내, `Install.cmd` 인자 전달·종료 코드 유지, `Start.cmd`는 D01/D02와 같은 제목·종료 코드 처리. 모두 ASCII |
| `scripts/windows/online/오픈소스고지.txt` | 신설 | Python·FFmpeg가 들어 있지 않음과 라이선스 위치, 글꼴. npm 목록은 빌드 때 덧붙인다 |
| `backend/app/launcher.py` | 수정 | `runtime/`이 없는 설치에서 FFmpeg가 없으면 "다시 설치" 대신 PATH 등록을 안내 |
| `scripts/issue_release.py` | 수정 | `variant`가 portable이 아니면 발행 거절 |
| `scripts/verify_release.py` | 수정 | `release.json`의 `variant`로 분기. online 검증 추가(아래). 공통 압축 해제 검사를 `unpack`으로 분리. 종료 후 잠금 확인은 venv도 시작되도록 `PYTHONHOME`·`PYTHONPATH`를 뺀 환경으로 실행 |
| `backend/tests/test_packaging.py`, `test_issued_release.py` | 수정 | PATH FFmpeg 안내, online 스크립트 ASCII·CRLF·해시 확인 순서, 고지 생성, online ZIP 발행 거절 |
| `docs/PILOT_OPERATIONS.md`, `docs/DEVELOPMENT.md`, `README.md` | 갱신 | 사용자 설치형 절(준비물·설치·계정·실행·업데이트), 빌드·검증 명령 |

## 검증과 완료 조건

- backend 전체 시험, `--spec 20261002 --check`, `git diff --check`가 통과한다. frontend는 바꾸지 않는다.
- `verify_release.py <online zip>`이 현재 Windows의 새 한글·공백 경로에서 다음을 통과한다: 설치 전 `Start.cmd --check`가 `Install.cmd`를 안내하며 실패, 손상 ZIP은 `.venv` 생성 전 거절, 틀린 `UV_PROJECT_ENVIRONMENT`·`PYTHONHOME`·`PYTHONPATH` 무시, `backend/.venv`의 Python 3.14와 PATH FFmpeg 사용, 로그인·접수, `Start.cmd`로 재시작 후 조회, 강제 종료 후 잠금 해제, 외부 AI 호출 0.
- 포터블 ZIP도 다시 만들어 기존 `verify_release.py`(포터블+발행)가 그대로 통과한다.
- 깨끗한 OS·다른 PC는 E10 범위로 남긴다.

## 구현 및 검증 기록

- [x] 구현·변경 파일 및 commit/PR 기록
- [x] 라이브러리/도구 최신·선택 버전·확인일·근거 기록
- [x] 시험 결과와 ZIP 크기·SHA-256 기록
- [x] cold review 발견사항과 수용/보류/거절·수정·재검증 기록

### 구현 (2026-10-05)

브랜치 `veluga/d04-user-install`, [PR #51](https://github.com/syleeVeluga/k-dog-proj/pull/51). 위 파일별 변경을 모두 반영했다. 계획과 다르거나 추가된 점:

- 첫 검증에서 `verify_release`가 결함을 찾았다: npm 라이선스가 `runtime/licenses/npm`에 들어가 사용자 설치형에도 `runtime/` 폴더가 생겼고, 앱은 `runtime/`이 있으면 내장 FFmpeg만 찾으므로 PATH FFmpeg를 쓰지 못한다. 사용자 설치형은 `licenses/npm`에 두도록 고쳤다 (포터블은 그대로 `runtime/licenses/npm`).
- 사용자 설치형 빌드는 `uv lock --check`로 잠금 파일이 최신인지 먼저 확인한다 (cold review).

### 버전 확인 (2026-10-05)

| 대상 | 최신 확인 | 선택 | 근거 |
| --- | --- | --- | --- |
| uv (사용자 PC 준비물) | 0.12.23 (2026-10-03) | 최신 설치 안내 | [uv releases](https://github.com/astral-sh/uv/releases/latest). 사용하는 `uv sync --locked --no-dev --python 3.14`는 개발 PC의 0.11.18에서도 동작을 확인했다. `uv.lock` revision 3을 못 읽는 오래된 uv는 설치 실패 안내에서 `uv self update`를 권한다 |
| FFmpeg (사용자 PC 준비물) | 9.0.2 (2026-09-18) | 사용자 설치본 | [ffmpeg.org download](https://ffmpeg.org/download.html). 개발 PC 검증은 PATH의 gyan.dev 8.1.1 full build로 했다. 사용자 설치형은 FFmpeg를 재배포하지 않는다 |
| Python 의존성 | `backend/uv.lock` 고정 | 변경 없음 | 설치 때 uv가 잠금 그대로 설치한다 |

### 시험과 패키지

- 사용자 설치형: `releases/d04/k-dog-v0.3.0-s1-windows-x64-online-ab5936b.zip` (git 무시 대상), 153개 파일, **1,938,591 B**, SHA-256 `58bc6e766eccb36354fd10c454f216f116c4ae50be7affa53f6908538685d172`. `runtime/`·`.venv`·시험이 없고 `pyproject.toml`·`uv.lock`·`Install.cmd`·`install.ps1`·`Start.cmd`·`오픈소스고지.txt`·`licenses/npm`이 있다.
- `verify_release.py <사용자 설치형>` 통과 (약 47초, uv 캐시 사용): 설치 전 `Start.cmd --check` 실패와 `Install.cmd` 안내, 손상 시 `hash mismatch`로 `.venv` 생성 전 거절, 틀린 `UV_PROJECT_ENVIRONMENT`·`PYTHONHOME`·`PYTHONPATH` 무시, 설치 후 손상을 `Start.cmd --check`가 "손상"으로 거절, `backend/.venv`의 Python 3.14와 PATH FFmpeg 사용, 로그인·접수, `Start.cmd`로 재시작 후 조회, 강제 종료 후 잠금 해제, 외부 AI 호출 0.
- 포터블 회귀: 같은 commit의 `k-dog-v0.3.0-s1-windows-x64-ab5936b.zip` (1,362개 파일, 74,768,470 B, SHA-256 `a4b792bd507f03c58ed049edf2edae75013efba4f8c4cb6fb4d5361a8f174fad`)로 기존 `verify_release.py`(포터블+합성 발행)가 그대로 통과했다.
- backend 전체 **601개 OK, skip 2** (역사 원본 부재로 정상 skip), `--spec 20261002 --check`(G01/G04 미수령은 기존 상태), `git diff --check` 통과. frontend 코드는 바꾸지 않았다 (빌드는 패키지 생성 때 실행됨).
- 자동 검증 범위 밖: 설치 중 관리자·개발자 계정 이름·숨김 비밀번호 입력은 콘솔 입력이 필요해 `-SkipAccounts`로 건너뛰었다. 같은 `app.manage create-user` 명령은 S15와 같다. 깨끗한 OS·다른 PC는 E10 범위다.

### cold review와 조치

독립 cold review 결과 P1·P2 없음, P3 8건. 모두 수용해 반영하고 두 ZIP을 다시 만들어 `verify_release`와 시험을 다시 통과했다.

| 등급 | 발견 | 조치 |
| --- | --- | --- |
| P3 | `catch`의 `Write-Error`가 `Stop`에서 다시 예외가 되어 긴 오류 덤프가 나옴 (S15부터 있던 결함) | 한 줄 `Installation failed: ...` 출력 후 `exit 1` |
| P3 | 손상 거절 검증이 실패 이유를 확인하지 않음 | `hash mismatch` 출력 확인 |
| P3 | 설치 후 손상을 `Start.cmd --check`가 거절하는지 검증 없음 | 사용자 설치형 검증에 추가 |
| P3 | 공통 `served()`의 잠금 확인이 포터블에서도 `PYTHONHOME`을 지운 환경으로 바뀜 | venv 인터프리터를 넘길 때만 지움. 포터블 경로는 이전과 같음 |
| P3 | 오래된 uv의 `--locked` 실패가 인터넷 문제로만 안내됨 | `uv self update` 안내 추가 |
| P3 | 사용자 설치형 빌드가 오래된 `uv.lock`을 그대로 넣음 | 빌드 때 `uv lock --check` |
| P3 | 포터블 쪽 FFmpeg 안내 분기 시험 없음, 시험 이름 과장 | 시험 추가, 이름 수정 |
| P3 | 상위 계획 §5의 "사용자 전달은 D03 발행물만"과 충돌, 일반 사용자 실행 안내 누락 | 예외 문구 추가, 운영 안내에 사용자 설치형 실행 추가 |
