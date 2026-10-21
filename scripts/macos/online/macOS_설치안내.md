# K-DOG macOS 사용자 설치형

버전: v1.1 · 2026-10-21

**처음 설치하는 분은 [먼저읽어주세요_macOS설치가이드.html](먼저읽어주세요_macOS설치가이드.html)을 더블클릭해 Safari에서 읽어 주세요.** Homebrew 준비부터 압축 해제·계정 생성·매일 실행·종료·오류 해결까지 순서대로 안내합니다. 아래는 간단한 설치 요약과 관리 참고사항입니다.

macOS 15 이상에서 사용한다. Apple Silicon을 기본 대상으로 하며 Intel Mac에서는 해당 아키텍처의 uv·FFmpeg 설치가 필요하다. 현재 Windows에서 패키지 구조와 공통 회귀를 검증했으며 macOS 실기기 설치·키체인·영상 처리 검증은 아직 수행하지 않았다.

1. ZIP 전체를 쓰기 가능한 영구 폴더(예: `~/Applications/K-DOG`)에 압축 해제한다. ZIP 안에서 실행하거나 설치 후 폴더를 이동하지 않는다. 인터넷 연결이 필요하다.
2. [Homebrew 공식 안내](https://brew.sh)에 따라 Homebrew를 먼저 설치한다. 이미 uv·FFmpeg·ffprobe가 설치되어 있으면 Homebrew 없이 진행할 수 있다. Intel Mac은 Homebrew의 지원 등급과 바이너리 제공 여부를 먼저 확인한다.
3. `Install.command`를 연다. 파일 손상 검사 후 없는 uv·FFmpeg를 Homebrew로 설치하고 Python 3.14.8 및 고정된 Python 패키지를 내려받는다. Node.js는 필요 없다.
4. 업무(operator)·개발자(developer) 계정 이름과 비밀번호를 입력한다. 비밀번호는 화면에 표시하지 않는다. 기존 계정이 있으면 이름 입력에서 Enter로 건너뛴다. 계정 자동 생성이나 기본 비밀번호는 없다.
5. `Start.command`를 연다. 브라우저에서 `http://127.0.0.1:8000`을 사용한다. 실행 중에는 터미널 창을 유지하고 종료할 때 Ctrl+C를 누른다. macOS에서 실행을 차단하면 시스템 설정의 개인정보 보호 및 보안에서 파일 출처를 확인하고 허용하거나 터미널에서 `bash Install.command` / `bash Start.command`로 실행한다. 이 ZIP은 서명·공증된 `.app`/`.pkg`가 아니다.

자료의 기본 위치는 `~/Library/Application Support/K-DOG/data`다. `KDOG_DATA_DIR` 환경변수로 다른 외부 폴더를 지정할 수 있다. 프로그램 폴더와 자료 폴더를 구분하며 기존 Windows 자료나 키를 자동 이관하지 않는다. 업무 자료 이전은 앱의 검증된 백업·복원을 사용한다. 복원한 자료의 공급자 키는 재등록한다.

개발자 계정에서 공급자 키를 등록한다. API 키 파일은 암호문으로 저장하며 보호 키는 현재 macOS 사용자의 로그인 키체인(`K-DOG API vault`, `aes256-v1`)에 보관한다. 첫 등록/사용 시 macOS 접근 확인이 표시될 수 있다. 키체인 접근을 거부하거나 잠긴 경우 등록·복호화가 실패한다. 오류를 해결하기 위해 해당 키체인 항목을 지우면 기존 키 파일을 읽을 수 없으므로 임의 삭제하지 않는다. 앱 계정과 macOS 로그인 계정은 별개다.

설치 재실행은 `Install.command`를 사용한다. `--skip-accounts`는 계정 생성만 생략한다. 다른 Mac·폴더로 `.venv`를 복사하지 않는다. 실제 Gemini 호출·영상 분석·PDF 출력 품질은 해당 Mac에서 별도 확인한다.

설치 뒤 패키지 폴더의 터미널에서 `backend/.venv/bin/python Verify.py`를 실행하면 파일 해시·별도 합성 키체인 항목·합성 영상/오디오·런처 시작/강제 종료를 검사한다. 실행 중인 K-DOG를 먼저 종료한다. 실제 자료·앱 키체인 항목·공급자 API를 사용하지 않는다. 검사 통과와 실제 분석·PDF 인수는 구분한다.
