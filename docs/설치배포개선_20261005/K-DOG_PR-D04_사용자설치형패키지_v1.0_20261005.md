# PR-D04 사용자 설치형 패키지

버전: v1.0 · 2026-10-05 · 상태: 구현 중 · 선행: D01–D03 · 기준: main `1f67d50`

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

- [ ] 구현·변경 파일 및 commit/PR 기록
- [ ] 라이브러리/도구 최신·선택 버전·확인일·근거 기록
- [ ] 시험 결과와 ZIP 크기·SHA-256 기록
- [ ] cold review 발견사항과 수용/보류/거절·수정·재검증 기록
