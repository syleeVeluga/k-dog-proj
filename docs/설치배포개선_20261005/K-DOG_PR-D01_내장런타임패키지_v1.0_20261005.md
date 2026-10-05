# PR-D01 내장 런타임 패키지

버전: v1.0 · 2026-10-05 · 상태: 계획 · 선행: D00 · 기준: main `6376311`

상위: [설치·배포 개선 계획](K-DOG_설치배포개선계획_v1.0_20261005.md). 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치 제안: `veluga/d01-bundled-runtime` · 권장 PR 제목: `release: Python·FFmpeg 내장 포터블 패키지`

## 문제와 결과

현재 ZIP은 사용자 PC에 `uv`·FFmpeg가 설치되어 PATH에 있어야 하고, 설치할 때 인터넷으로 Python과 의존성을 받는다 (`scripts/windows/install.ps1`). 이 PR 이후에는 **ZIP 안에 실행에 필요한 것이 모두 들어 있어** 압축을 풀고 `Start.cmd`만 실행하면 된다. 평문 ZIP의 설치 단계(`Install.cmd`/`install.ps1`)는 없어진다. 고객용 발행 패키지에는 D03에서 키 입력 전용 `Install.cmd`가 새로 생긴다.

이 PR의 산출물은 평문 포터블 ZIP이다. 내부 검증과 담당자 설치에 쓰고, 고객 전달은 D03 발행물로 한다.

## 패키지 구조

```
K-DOG\
  Start.cmd
  release.json                 ← 전체 파일 SHA-256 manifest (runtime 포함)
  runtime\python\              ← CPython 3.14 공식 embeddable + 잠금 의존성
     python.exe, python314.zip, python314._pth, Lib\site-packages\...
  runtime\ffmpeg\              ← D00 빌드 결과: ffmpeg.exe, ffprobe.exe, licenses\, source\, build.json
  오픈소스고지.txt              ← 한국어 오픈소스 고지
  backend\app\  resources\  frontend\dist\  docs\  README.md
```

`python314._pth`는 다음 경로만 허용한다. embeddable은 `._pth`가 있으면 `PYTHONPATH`·사용자 site를 무시하므로 사용자 PC의 다른 Python 설정과 섞이지 않는다.

```
python314.zip
.
Lib\site-packages
..\..\backend
```

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `scripts/build_release.py` | 수정 | ① 고정 URL·SHA-256으로 embeddable Python을 받아 `releases/.cache/`에 보관하고 해시 확인 ② `runtime/python`에 풀고 `._pth` 작성 ③ `uv export --locked --no-dev` 결과를 hash 필수·wheel 전용으로 `Lib/site-packages`에 설치 ④ D00 빌드 결과를 `build.json` 해시로 확인한 뒤 `bin`·`licenses`·`source`·`build.json`을 `runtime/ffmpeg`에 복사 (결과가 없거나 해시가 다르면 빌드 중단) ⑤ `오픈소스고지.txt` 동봉 ⑥ manifest에 runtime 파일 포함 ⑦ `Install.cmd`/`install.ps1` 대신 새 `Start.cmd`를 넣음 |
| `scripts/windows/오픈소스고지.txt` | 신설 | FFmpeg(GPL 2+, libx264·zlib 포함)가 K-DOG와 별개 프로그램이며 GPL에 따라 자유롭게 사용·수정·재배포할 수 있다는 점과 소스 위치(`runtime\ffmpeg\source`). Python(PSF), 주요 Python 패키지, `frontend/dist`에 번들된 npm 패키지(React 등), 글꼴(OFL) 등 동봉 오픈소스 목록과 라이선스 파일 위치. npm 라이선스 목록은 빌드 때 `package-lock.json` 기준으로 생성해 동봉한다 |
| `scripts/windows/Start.cmd` | 수정 | ASCII만 사용. `runtime\python\python.exe -X utf8 -m app.launcher %*` 실행. 실패 시 `pause` 유지. FFmpeg 경로는 PATH에 의존하지 않는다 (아래 `media.py`) |
| `backend/app/media.py`, `backend/app/launcher.py` | 수정 | `ffmpeg`/`ffprobe` 실행 파일을 한 곳에서 정한다: `REPO_ROOT/runtime/ffmpeg/bin/` 아래에 있으면 그것을, 없으면 지금처럼 PATH를 쓴다. `media.command`와 `preflight`가 같은 함수를 사용한다. 그래야 `Start.cmd`를 거치지 않는 진입점(D03 설치 프로그램의 `--check`, 담당자 CLI `app.manage preprocess`, PATH를 비운 `verify_release`)에서도 동작한다 |
| `scripts/windows/Install.cmd`, `scripts/windows/install.ps1` | 삭제 | 호출처(`build_release.py`, `verify_release.py`)를 확인한 뒤 제거. 매니페스트 해시 검사는 아래 `--check`로 옮김 |
| `backend/app/launcher.py` | 수정 | `--check`에서 `release.json`이 있으면 전체 파일 해시를 검사 (기존 install.ps1의 손상 거절 보호를 유지). 일반 실행은 지금처럼 필수 자산 존재만 확인. Python·FFmpeg 누락 메시지를 "프로그램을 다시 설치하세요"로 변경 |
| `scripts/verify_release.py` | 수정 | 설치 단계 제거. PATH를 Windows 기본 경로만 남겨 외부 uv·Python·FFmpeg가 없음을 보장한 상태에서 압축 해제 → 파일 손상 시 `Start.cmd --check` 실패 확인 → 원복 후 `--check` 통과 → 기존 HTTP 로그인·접수·재시작·종료 검증 |
| `backend/tests/test_packaging.py` | 수정 | allowlist·runtime 포함/개발 파일 제외, `--check` 해시 불일치 거절, 내장 FFmpeg 우선·PATH 대체 선택 시험 |
| `docs/PILOT_OPERATIONS.md`, `README.md`, `docs/DEVELOPMENT.md` | 갱신 | uv·FFmpeg 사전 설치 안내 제거, `Start.cmd` 실행, 담당자 CLI 경로를 `runtime\python\python.exe -X utf8 -m app.manage ...`로 변경, 빌드 명령 |

`.gitignore`의 `releases/`가 `releases/.cache/`도 포함하는지 확인한다. 내려받은 런타임은 커밋하지 않는다.

## 구현 순서

1. `graft callers`로 `install.ps1`·`Install.cmd`·`preflight`·`REQUIRED`의 사용처를 확인한다.
2. 상위 계획 §7의 버전을 다시 확인하고, Python embeddable의 고정 URL과 SHA-256을 `build_release.py` 상수로 기록한다. FFmpeg는 D00 빌드 결과만 사용한다.
3. 빌드 스크립트에 런타임 조립을 추가한다. 의존성 설치는 잠금 파일 기준·hash 필수·바이너리 wheel 전용으로 하고, 정확한 `uv` 옵션은 구현 시 공식 문서로 확인한다.
4. `Start.cmd`·`launcher --check`를 바꾸고 기존 설치 스크립트를 제거한다.
5. 패키지 안의 FFmpeg로 전처리 시험과 합성 리허설을 다시 실행한다. FFmpeg 자체의 기능 확인은 D00에서 끝낸다.
6. 문서를 갱신하고 새 ZIP으로 `verify_release.py`를 실행한다.

## 검증과 완료 조건

- backend 전체 시험, `--spec 20261002 --check`, frontend build·전체 e2e, `git diff --check`가 통과한다.
- 패키지 안의 FFmpeg로 `test_preprocess_v4`, `test_preprocess_api_v4`, `test_report_runs_v4`, `test_rehearsal`이 통과한다.
- `verify_release.py`가 **PATH에 uv·Python·FFmpeg가 없는 상태**에서 새 한글·공백 경로 압축 해제, 손상 거절, 로그인·접수·재시작, 강제 종료 후 잠금 해제, 외부 AI 호출 0을 통과한다.
- 패키지에 시험·`.venv`·`.git`·`node_modules`·키·런타임 자료가 없다.
- `runtime/ffmpeg`의 바이너리 해시가 D00 `build.json`과 같다. `licenses/`·`source/`·`오픈소스고지.txt`가 들어 있다. Python과 각 패키지의 라이선스 파일(`dist-info`)이 남아 있다.
- 상위 계획 Q01의 법무·담당자 확인 결과와 Q05(특허) 상태를 실행 기록에 남긴다. 둘 다 기록되기 전에는 이 ZIP을 고객에게 보내지 않는다.

## 위험과 대응

| 위험 | 대응 |
| --- | --- |
| embeddable에 없는 표준 모듈을 앱이 사용 | backend 전체 시험과 HTTP 검증을 내장 런타임으로도 실행하여 import 실패를 찾는다 |
| 일부 의존성이 3.14 Windows wheel이 없음 | 바이너리 전용 설치에서 바로 실패하므로 빌드 단계에서 드러난다. 소스 빌드로 우회하지 않는다 |
| FFmpeg 버전·빌드 변경으로 전처리 결과 변화 | D00에서 먼저 확인하고, 완료 조건의 전처리·리허설 시험으로 패키지 상태를 다시 확인한다 |
| 패키지 크기 증가 | K01에서 허용함. ZIP 크기를 실행 기록에 남긴다 |

## 구현 및 검증 기록

- [ ] 구현·변경 파일 및 commit/PR 기록
- [ ] 라이브러리/도구 최신·선택 버전·확인일·근거 기록
- [ ] 시험 결과(backend/e2e/전처리/리허설/verify_release)와 ZIP 크기·SHA-256 기록
- [ ] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [ ] D02 인계 사항 기록
