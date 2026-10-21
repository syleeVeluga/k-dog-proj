# K-DOG macOS 사용자 설치형 구현·검증 기록

버전: v1.0 · 2026-10-21 · S1.1

## 범위와 사용

사용자 요청에 따라 macOS 사용자 설치형 ZIP만 추가한다. 기존 Windows portable/online ZIP 경로와 설치 방법은 유지한다. macOS 포터블, `.app`/`.pkg`, 코드 서명·공증, 자동 Windows 자료 이관은 범위에 포함하지 않는다.

`scripts/build_release.py --variant macos-online`은 현행 S1 제품 허용 목록·빌드된 화면·`pyproject.toml`/`uv.lock`·macOS 스크립트·설치 안내·고지·`Verify.py`만 포함한다. 실행 파일은 동봉하지 않는다. 고객 원본·시험 자료·운영 DB·API 키·`.venv`를 패키지에 넣지 않는다. ZIP의 두 `.command` 파일은 Unix 실행 권한 0755와 LF를 갖는다. `release.json`에 variant/platform/commit/파일별 SHA-256을 기록하고 설치 전 `SHA256SUMS`로 파일 손상을 검사한다. 외부 ZIP SHA-256과 함께 확인한다. 체크섬은 서명·공증을 대신하지 않는다.

[설치 안내](../../scripts/macos/online/macOS_설치안내.md): macOS 15 이상, Apple Silicon 기본. Intel은 해당 uv/FFmpeg가 있는 환경에서 실행 경로를 제공하지만 최신 Homebrew의 Intel 지원은 Tier 3이고 미리 빌드한 바이너리 제공이 제한되므로 실기기 검증 전 지원 완료로 표시하지 않는다. Homebrew 최초 설치는 공식 안내에 따라 사용자가 수행한다. 설치 프로그램은 PATH의 uv·FFmpeg를 확인하고 없으면 기존 Homebrew로 설치한 다음 uv-managed Python 3.14.8과 잠금 의존성을 설치한다. 업무·개발자 계정을 숨김 비밀번호로 생성할 수 있다. 계정 생성만 생략하는 `--skip-accounts`를 지원한다. Node.js 설치는 필요 없다.

`Start.command`는 `.venv/bin/python`으로 기존 launcher를 실행한다. 기본 자료는 `~/Library/Application Support/K-DOG/data`이며 `KDOG_DATA_DIR` 명시 경로가 우선한다. API·worker를 각각 POSIX 세션으로 실행하며 런처 종료와 감시 파이프 EOF 때 그 세션의 미디어 자식까지 종료한다. Windows Job Object와 DPAPI 구현은 유지한다.

macOS 키 파일은 AES-256-GCM(12바이트 난수 nonce, 고정 AAD, 판본 header) 암호문이다. 보호 키는 현재 사용자의 로그인 Keychain generic-password 항목에 저장한다. Security/CoreFoundation을 ctypes로 직접 호출하여 비밀을 프로세스 인자로 넘기지 않는다. 복호화 시 없는 키를 새로 생성하지 않으며 키체인 거부·잠김·암호문 훼손은 HTTP 409로 실패한다. 생성 경합에서 기존 항목을 덮어쓰지 않고 승자의 키를 다시 읽는다. 앱의 기존 키 주/예비 슬롯·권한·백업 제외·복원 후 재등록 계약은 유지한다.

## 공식 버전·API 확인

확인일: 2026-10-21. 새 라이브러리를 추가하지 않는다. backend/uv.lock과 frontend/package-lock.json은 변경하지 않는다. 다른 패키지 최신/선택 버전은 같은 날 기존 Windows 릴리즈의 의존성 확인 기록을 재사용하고 현재 설치형에는 기존 잠금판을 유지한다.

| 대상 | 확인한 최신 안정판 / 선택 | 근거와 이유 |
| --- | --- | --- |
| Python | 3.15.0 / 3.14.8 | [최신](https://www.python.org/downloads/release/python-3150/), [3.14.8](https://www.python.org/downloads/release/python-3148/). 프로젝트 `>=3.14,<3.15`와 기존 런처 계약을 유지하고 호환 유지보수판을 고정한다. |
| uv | Homebrew 0.13.4 / 설치된 uv 또는 Homebrew 안정판 | [registry](https://formulae.brew.sh/api/formula/uv.json), [managed Python](https://docs.astral.sh/uv/guides/install-python/), [CLI](https://docs.astral.sh/uv/reference/cli/). 호스트 0.11.18에서 lock/check 및 `--managed-python` 지원을 확인했다. 설치 시 도구 자체의 버전은 `uv --version`으로 기록할 수 있다. |
| FFmpeg | 9.0.2 / 사용자가 설치한 FFmpeg 또는 Homebrew 안정판 | [registry](https://formulae.brew.sh/api/formula/ffmpeg.json). 바이너리는 동봉하지 않고 launcher에서 FFmpeg·ffprobe 실행을 검사한다. 기존 앱 CLI를 유지한다. |
| cryptography | 50.0.2 / 기존 50.0.2 | [PyPI](https://pypi.org/project/cryptography/), [AESGCM API](https://cryptography.io/en/stable/hazmat/primitives/aead/). Python 3.14·macOS 지원, 256비트 키·12바이트 nonce·인증 실패 처리를 확인했다. 기존 의존성을 재사용한다. |
| macOS Keychain | OS 제공 API | [generic-password](https://developer.apple.com/documentation/security/ksecclassgenericpassword), [SecItemCopyMatching](https://developer.apple.com/documentation/security/secitemcopymatching(_:_:)). CoreFoundation 소유 객체와 조회 결과를 CFRelease로 반환한다. |
| Homebrew | 현행 지원 정책 | [설치](https://docs.brew.sh/Installation), [지원 등급](https://docs.brew.sh/Support-Tiers). macOS 15 이상·Apple Silicon 기본 경로를 사용한다. |

## 검증

Windows 실행 결과: backend 관련 52건 중 51건 통과·네이티브 Keychain 1건 명시 skip(121.931초). frontend TypeScript/Vite 빌드 통과, settings·Gemini 키 전환·화면 문구 Playwright 8건 통과(1.3분). 두 `.command`는 Git Bash `bash -n` 구문 검사 통과. `uv lock --check`, `git diff --check`, `graft check` 통과. ZIP 회귀는 Unix 0755·LF·전 파일 SHA-256·Windows 실행 파일/내장 runtime 부재를 검사한다. Windows에서 수행한 모의·공통 회귀 결과는 macOS 네이티브 통과가 아니다.

```powershell
# backend/에서
uv run --locked python -X utf8 -m unittest tests.test_macos_distribution tests.test_packaging tests.test_settings tests.test_gemini_key_fallback -v
# 저장소 루트에서
git diff --check
uv lock --check --project backend
graft build
graft check
uv run --project backend --locked python scripts/build_release.py releases/kdog-s1-macos-online.zip --variant macos-online
```

macOS에서 설치 후 `backend/.venv/bin/python Verify.py`로 파일 해시·독립 합성 Keychain 항목·합성 MP4 오디오·API 시작·런처 강제 종료 후 API 종료를 점검한다. `backend/tests/test_macos_distribution.py`의 네이티브 Keychain 시험도 macOS에서만 실행한다. 현재 작업 환경에는 macOS 호스트가 없어 이 네이티브 항목과 Finder 더블클릭/키체인 접근 확인창/실제 영상·PDF·공급자 인수는 미검증이다.
