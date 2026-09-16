# K-DOG v0.2.0 시험 릴리즈

K-DOG는 반려견·보호자 평가 자료를 접수하고 촬영 당일 자료를 정리하는 로컬 앱입니다. 이 릴리즈는 **Windows 11 x64에서 42항목 판(2026-09-13 사양)의 촬영 당일 절차를 시험**하기 위한 버전입니다. 접수(순번·동의·보호자명·반려견 정보), 보호자 설문 28문항 CSV/Excel 가져오기, 영상 파일 여러 개 등록, 기준 영상 위 8구간 시각 확정, 확정 구간으로 클립을 만드는 전처리 명령이 들어 있습니다. AI 채점·검수·리포트는 다음 판에서 제공하며, 이 판에는 옛 55항목 분석 화면이 없습니다. 실제 참가자 자료 대신 가상 이름과 ID로 먼저 확인하세요.

## 내려받아 설치하기

1. [GitHub v0.2.0 릴리즈](https://github.com/syleeVeluga/k-dog-proj/releases/tag/v0.2.0)에서 `kdog-v0.2.0-windows-x64.zip`과 같은 이름의 `.sha256` 파일을 받습니다. GitHub의 자동 생성 `Source code` 압축 파일은 설치 패키지가 아닙니다.
2. [uv Windows 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 `uv`를 설치하고, [FFmpeg 다운로드 안내](https://ffmpeg.org/download.html)의 Windows 빌드에서 `ffmpeg`와 `ffprobe`를 설치해 PATH에 등록합니다. 새 PowerShell 창에서 `uv --version`, `ffmpeg -version`, `ffprobe -version`이 모두 성공해야 합니다. 첫 설치에는 인터넷이 필요합니다.
3. ZIP과 해시 파일이 있는 폴더에서 아래 명령으로 다운로드를 확인합니다. 해시가 다르면 설치하지 않습니다.

   ```powershell
   $zip = (Resolve-Path '.\kdog-v0.2.0-windows-x64.zip').Path
   $expected = ((Get-Content -LiteralPath "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
   $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
   if ($actual -ne $expected) { throw '다운로드 파일의 SHA-256이 일치하지 않습니다.' }
   ```

4. ZIP을 **빈 로컬 폴더**에 압축 해제합니다. 예: `C:\K-DOG\app-v0.2.0`. 압축 해제한 폴더에서 `Install.cmd`를 실행하고 관리자(`admin`) 계정 이름과 비밀번호를 만듭니다. 개발자(`developer`) 계정은 공급자 키를 미리 등록해 둘 때만 필요합니다. 기본 계정이나 비밀번호는 없습니다.
5. 같은 폴더의 `Start.cmd`를 실행합니다. `K-DOG 실행 중`이 보이면 자동으로 열린 브라우저 또는 `http://127.0.0.1:8000`에서 관리자 계정으로 로그인합니다. 사용 중에는 실행 창을 열어 두고, 종료할 때 그 창에서 Ctrl+C를 누릅니다.

v0.1.0 자료 폴더를 그대로 지정하면 첫 실행 때 42항목 판 입력 형식으로 자동 이관됩니다. 옛 30문항 설문 가운데 새 설문지에 없는 문항은 버려지고 참가자 화면의 이관 메모에 기록됩니다.

## 키 없이 기본 동작 시험하기

「접수」 메뉴의 참가자 등록에서 `행사 ID`에 `TRIAL`, `참가자 ID`에 `0001`, `반려견 이름`에 `가상 시험견`을 입력하고 `참가자 저장`을 누릅니다. 목록에서 해당 참가자를 열어 입력 내용을 확인하고, 브라우저를 새로고침해도 자료가 남는지 확인합니다. 「설문」 메뉴에서 양식 CSV를 내려받아 가상 응답을 채운 뒤 가져오기로 등록하고, 「촬영」 메뉴에서 짧은 영상 파일을 등록해 8구간 시각을 확정할 수 있습니다. 이 단계에는 AI 키나 실제 개인정보가 필요하지 않습니다. 촬영 당일 절차 전체와 전처리 명령은 [설치·파일럿 운영 안내](docs/PILOT_OPERATIONS.md)를 따르세요.

자료는 기본적으로 `%LOCALAPPDATA%\K-DOG\data`에 저장되며 프로그램 폴더를 지워도 남습니다. 시험 자료를 별도로 관리하려면 설치 전에 `KDOG_DATA_DIR`을 프로그램 폴더 밖의 로컬 경로로 설정하세요. 지원 환경, 문제 해결, 백업·복원 절차는 [전체 운영 안내](docs/PILOT_OPERATIONS.md)에 있습니다. 개발자 빌드와 자동 시험은 [개발 실행 안내](docs/DEVELOPMENT.md)를 참고하세요.
