# K-DOG Windows 설치·파일럿 운영 안내

버전: v1.3 · 2026-09-15 · M6

## 일반 사용자 빠른 실행

설치 담당자가 준비를 마친 PC라면 일반 사용자는 이 절만 따르면 된다. 준비물은 **K-DOG 앱 폴더**와 전달받은 **앱 계정 이름·비밀번호**다.

1. 앱 폴더에서 `Start.cmd`를 두 번 클릭한다. 별도의 Python이나 개발 도구를 열지 않는다.
2. `K-DOG 실행 중: http://127.0.0.1:8000`이 보일 때까지 K-DOG 실행 창을 닫지 않고 기다린다. 보통 브라우저가 자동으로 열린다.
3. 브라우저가 열리지 않으면 Microsoft Edge에서 `http://127.0.0.1:8000`을 입력한다. 이 주소는 현재 PC에서만 열리는 로컬 주소다.
4. 전달받은 K-DOG 앱 계정으로 로그인한다. Windows 로그인 비밀번호와 K-DOG 앱 비밀번호는 서로 다를 수 있다.
5. 사용하는 동안 K-DOG 실행 창을 열어 둔다. 브라우저 탭만 닫아도 처리는 계속된다.
6. 업무가 끝나면 K-DOG 실행 창을 선택하고 Ctrl+C를 누른다. `Terminate batch job (Y/N)?`이 표시되면 `Y`를 입력하고 Enter를 누른다. 실행 창이 닫힌 뒤에는 브라우저나 PC를 종료해도 된다.

오류가 보이면 반복해서 실행하거나 새 계정을 만들지 않는다. 첫 오류가 보이는 K-DOG 실행 창을 캡처하고 설치 담당자에게 전달한다. 화면에 참가자 자료·키·비밀번호가 보이면 가리고 전달한다.

## 지원 환경 확인

| 환경 | 지원 판단 |
|---|---|
| 최신 보안 업데이트가 적용된 Windows 11 x64 | 지원·검증 환경. 현재 배포 기본값이다. |
| Windows 10 x64 | 이번 실기 검증 대상이 아니다. [Microsoft 일반 지원](https://www.microsoft.com/windows/end-of-support)이 2025-10-14 종료되었으므로, 유효한 ESU와 조직 보안 승인이 있는 기존 PC에서만 제한적으로 사용하고 신규 배포는 Windows 11을 사용한다. |
| Windows on ARM, 32비트 Windows, Windows S 모드, Windows Server | 미검증·미지원이다. x64 기반의 일반 Windows 11 PC를 사용한다. [S 모드 해제](https://support.microsoft.com/windows/switching-out-of-s-mode-in-windows)는 되돌릴 수 없으므로 앱 사용자가 임의로 변경하지 않는다. |
| macOS·Linux | 미지원이다. Windows DPAPI 키 저장소와 Windows 실행 스크립트를 사용한다. |
| Edge·Chrome 최신 안정 버전 | 권장한다. 자동 브라우저 시험은 Chromium 계열에서 수행했다. Firefox와 다른 브라우저는 운영 검증 대상이 아니다. |

Windows의 **설정 → 시스템 → 정보 → 시스템 종류**에서 `64비트 운영 체제, x64 기반 프로세서`인지 확인한다. S 모드, 회사의 앱 실행 제한, 백신/EDR 정책으로 CMD·PowerShell·uv·FFmpeg 실행이 차단되면 사용자가 보안 설정을 우회하지 말고 IT 관리자에게 요청한다.

프로그램과 자료는 짧은 로컬 경로를 권장한다. 예: `C:/K-DOG/app-m6`, `D:/K-DOG/data`. 네트워크 공유, OneDrive 동기화 폴더, 이동식 드라이브는 운영 검증 대상이 아니므로 사용하지 않는다. 한글과 공백이 포함된 로컬 설치 경로는 패키지 검증을 통과했다.

K-DOG는 키를 등록한 **동일한 Windows 사용자 계정**으로 설치·실행한다. 다른 Windows 사용자로 전환하거나 `다른 사용자로 실행`하면 `%LOCALAPPDATA%`, 사용자 환경 변수와 암호화 키가 달라진다. 평소 계정이 아닌 관리자 계정으로 `Start.cmd`를 실행하지 않는다.

## 설치 담당자용 설치

대상 PC의 준비와 최초 계정 생성은 설치 담당자가 수행한다. 앱의 관리자/개발자 로그인과 Windows 실행 계정은 별개다. API와 worker, 키 등록은 같은 Windows 계정으로 실행한다. 최초 설치에는 인터넷이 필요하며, 설치가 끝난 앱의 실행에는 Node.js·npm·Git이 필요 없다. Python 3.14는 `uv`가 설치 과정에서 내려받으므로 별도로 먼저 설치하지 않아도 된다. `Install.cmd`는 Windows PowerShell 5.1로 검증했으며 PowerShell 7을 별도로 설치할 필요가 없다.

### 1. 전달 파일 확인

[GitHub v0.1.0 릴리즈](https://github.com/syleeVeluga/k-dog-proj/releases/tag/v0.1.0)에서 같은 이름의 ZIP과 SHA-256 파일 두 개를 받는다. 예: `kdog-v0.1.0-windows-x64.zip`, `kdog-v0.1.0-windows-x64.zip.sha256`. 둘을 같은 폴더에 둔 뒤 PowerShell에서 다음을 실행한다. GitHub의 자동 생성 `Source code` 압축 파일은 설치 패키지가 아니다.

```powershell
$zip = (Resolve-Path ".\kdog-v0.1.0-windows-x64.zip").Path
$expected = ((Get-Content -LiteralPath "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "ZIP SHA-256이 일치하지 않습니다. 실행하지 말고 파일을 다시 받으세요." }
"SHA-256 확인 완료: $actual"
```

파일명이 다르면 첫 줄만 실제 ZIP 이름으로 바꾼다. 불일치하면 압축을 풀거나 실행하지 않는다. ZIP을 신뢰하는 경로에서 받았고 해시가 일치한 뒤 Windows가 다운로드 파일을 차단할 때만 `Unblock-File -LiteralPath $zip`을 실행한다. `release.json`은 압축 내부 파일의 무결성 목록이며 ZIP의 배포자 인증이나 코드 서명을 대체하지 않는다.

### 2. 필수 도구 준비

1. [uv 공식 Windows 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 설치한다. 조직이 허용한 경우 `winget install --id=astral-sh.uv -e`를 사용할 수 있다.
2. [FFmpeg 공식 다운로드 안내](https://ffmpeg.org/download.html)의 Windows 빌드 링크에서 FFmpeg를 설치하고 `ffmpeg.exe`, `ffprobe.exe`가 있는 폴더를 PATH에 등록한다. 빌드에는 H.264/AAC 디코더와 libx264/AAC 인코더가 필요하다.
3. 설치 후 **새 PowerShell 창**을 열어 다음 세 명령이 모두 성공하는지 확인한다.

```powershell
uv --version
ffmpeg -version
ffprobe -version
```

### 3. 프로그램과 자료 경로 준비

ZIP은 반드시 빈 새 프로그램 폴더에 압축 해제한다. 압축 파일 내부에서 `Install.cmd`를 직접 열지 않는다. 예: `C:/K-DOG/app-v0.1.0`. 프로그램 폴더에는 운영 자료를 두지 않는다.

자료의 기본 위치는 `%LOCALAPPDATA%/K-DOG/data`다. 다른 위치를 사용할 때에는 설치 전에 다음처럼 사용자 환경 변수를 설정하고 새 PowerShell 창을 연다. 기존 자료를 다시 열 때 경로 철자와 드라이브가 이전 실행과 같은지 먼저 확인한다.

```powershell
[Environment]::SetEnvironmentVariable('KDOG_DATA_DIR', 'D:\K-DOG\data', 'User')
[Environment]::GetEnvironmentVariable('KDOG_DATA_DIR', 'User')
```

`KDOG_DATA_DIR`은 프로그램 폴더 밖의 로컬 경로를 지정한다. 경로를 바꾸면 앱은 별도 데이터베이스로 인식하므로, 기존 자료가 사라진 것처럼 보일 때 새 계정이나 자료를 만들기 전에 이 값을 확인한다.

### 4. 설치와 첫 실행

1. 압축을 푼 폴더의 `Install.cmd`를 실행한다. 파일 해시를 먼저 확인한 뒤 잠금 파일에 지정된 운영 의존성과 Python 3.14 환경을 `backend/.venv`에 설치한다.
2. 새 설치에서는 운영 관리자(`admin`)와 개발자(`developer`) 계정 이름을 각각 입력하고 12~256자 비밀번호를 숨김 프롬프트에 두 번 입력한다. 기본 계정과 기본 비밀번호는 없다. 기존 데이터 경로에 해당 역할의 계정이 이미 있을 때만 계정 이름 질문에서 Enter로 건너뛴다.
3. `Installation complete`가 표시되면 PowerShell에서 `.\Start.cmd --check`를 한 번 실행해 설치 파일·Python·FFmpeg 검사를 확인한다.
4. `Start.cmd`를 두 번 클릭하거나 PowerShell에서 `.\Start.cmd`를 실행한다. `K-DOG 실행 중: http://127.0.0.1:8000`이 표시된 뒤 브라우저가 열린다. 자동으로 열리지 않으면 해당 주소를 직접 연다.
5. 운영 관리자로 로그인해 직원용 `operator`/`reviewer` 계정을 발급한다. 개발자 계정으로 로그인해 Gemini 키, 사용할 모델과 단계별 설정을 등록하고 연결 시험을 수행한다. 연결 시험은 실제 공급자 호출과 비용을 발생시킬 수 있다. 설치나 시작만으로 공급자 연결 시험을 실행하지 않는다.

`Install.cmd`는 해당 PowerShell 프로세스에만 ExecutionPolicy Bypass를 적용하며 시스템 정책을 바꾸지 않는다. 조직 정책으로 차단되면 관리자가 검토한 스크립트 실행 경로를 사용한다. 반복 설치는 기존 계정을 변경하지 않는다. 업데이트는 앱을 종료·백업한 뒤 새 프로그램 폴더에 설치하여 동일 데이터 경로를 지정한다. `.venv`를 다른 폴더/PC로 복사하지 않는다.

## 실행·종료·장애

실행 창은 감독 프로세스이며 닫으면 API와 worker도 종료된다. 브라우저 탭만 닫으면 처리는 계속된다. 종료할 때 실행 창에서 Ctrl+C를 누른다. 처리 도중 종료한 요청은 다음 실행에서 점유 만료(기본 약 3분) 후 파일 검증·재개한다. 응답이 유실된 외부 요청은 이미 과금되었을 수 있다.

중복 실행, 기존 API/worker, 사용 중인 포트가 있으면 새 실행은 거절된다. 한 프로세스가 실패하면 다른 프로세스도 종료하고 실행 창에 오류를 표시한다. FFmpeg가 없거나 화면 빌드가 누락되어도 시작 전에 안내한다. 상세 실행 명령은 프로그램 `backend/`에서 다음과 같다.

```powershell
.venv/Scripts/python.exe -X utf8 -m app.launcher --check
.venv/Scripts/python.exe -X utf8 -m app.launcher --data-dir "D:/K-DOG/data" --port 8001
.venv/Scripts/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" recovery-status
```

로컬 실행기는 loopback 전용이다. 내부망·클라우드 배포를 자동 개설하지 않는다. 프로그램 폴더를 삭제해도 별도 데이터 폴더는 보존된다. 자료/백업 삭제는 별도 보관 정책을 따른다.

## 문제 해결

| 표시 또는 증상 | 확인과 조치 |
|---|---|
| Windows S 모드 또는 조직 정책 차단 | 사용자가 S 모드를 해제하거나 보안 정책을 우회하지 않는다. 이 앱은 S 모드 미지원이며 CMD·PowerShell·uv·FFmpeg 실행 허용은 IT 관리자가 판단한다. |
| `winget` 명령을 찾을 수 없음 | K-DOG 문제가 아니다. 설치 담당자가 uv 공식 Windows 설치 안내의 독립 설치 파일 또는 조직 표준 배포 방법을 사용한다. 일반 사용자가 임의 사이트에서 설치 파일을 받지 않는다. |
| `Install uv and add it to PATH` | uv 설치 후 기존 창을 닫고 새 PowerShell에서 `uv --version`을 확인한 다음 `Install.cmd`를 다시 실행한다. |
| `Install ffmpeg/ffprobe and add it to PATH` | 두 실행 파일이 같은 설치의 PATH에서 조회되는지 `ffmpeg -version`, `ffprobe -version`으로 확인한다. |
| `Release file hash mismatch` | 설치를 중단하고 ZIP을 새로 받는다. 압축 해제 후 파일을 수정한 폴더에서 설치하지 않는다. |
| `Python 3.14 환경이 필요합니다` 또는 `.venv` 누락 | 인터넷 연결과 uv 실행을 확인한 뒤 `Install.cmd`를 다시 실행한다. 회사 방화벽·프록시 환경이면 uv의 Python 배포 파일과 PyPI HTTPS 다운로드 허용을 IT 관리자에게 요청한다. 다른 PC나 폴더에서 복사한 `.venv`는 사용하지 않는다. |
| 포트 사용 중 또는 중복 실행 거절 | 이미 열린 K-DOG 실행 창에서 계속 사용하거나 그 창에서 Ctrl+C로 종료한 뒤 다시 시작한다. 다른 포트가 필요하면 PowerShell에서 `.\Start.cmd --port 8001`을 실행하고 `http://127.0.0.1:8001`로 접속한다. |
| 브라우저가 자동으로 열리지 않음 | 실행 창에 `K-DOG 실행 중`이 보이면 브라우저에서 `http://127.0.0.1:8000`을 직접 연다. 해당 문구가 없으면 먼저 `.\Start.cmd --check`의 오류를 확인한다. |
| 로그인할 수 없음 | 계정 이름·역할을 확인한다. 비밀번호 재설정은 앱을 종료한 뒤 프로그램 `backend/`에서 `.venv/Scripts/python.exe -X utf8 -m app.manage reset-password USERNAME`으로 수행한다. 별도 자료 경로이면 `--data-dir "D:/K-DOG/data"`를 `reset-password` 앞에 둔다. |
| 키 연결이 갑자기 해제됨 | 키를 등록한 Windows 사용자와 현재 `Start.cmd`를 실행한 Windows 사용자가 같은지 확인한다. 다른 사용자나 관리자 계정으로 실행했다면 종료하고 원래 계정에서 다시 시작한다. 키 파일이나 환경 변수를 다른 계정으로 복사하지 않는다. |
| 기존 자료가 보이지 않음 | 새 자료를 만들지 말고 앱을 종료한다. 이전과 같은 Windows 사용자로 로그인했는지 확인하고, 새 PowerShell에서 `$env:KDOG_DATA_DIR`과 실제 기존 데이터 폴더의 `kdog.sqlite3` 존재 여부를 확인한 뒤 올바른 경로로 다시 시작한다. |
| API 또는 worker 시작 실패 | 실행 창을 닫지 말고 첫 오류 문구를 기록한다. `.\Start.cmd --check`로 파일·Python·FFmpeg를 확인하고, 기존 K-DOG 프로세스와 포트 사용 여부를 확인한다. 해결되지 않으면 오류 문구와 `release.json`의 `commit` 값을 개발자에게 전달하되 키·비밀번호·참가자 자료는 보내지 않는다. |

## 백업·복원

관리자 화면의 자료 백업 또는 아래 명령을 사용한다. 백업에는 개인정보·영상이 있으므로 접근 권한과 보관 위치를 관리한다. 공급자 키와 로그인 세션은 백업하지 않는다.

```powershell
# 프로그램 backend/에서 실행한다. --data-dir는 하위 명령 앞에 둔다.
.venv/Scripts/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" backup "E:/K-DOG/backup-20260906" --actor manager
```

복원/정리 전에는 Start.cmd 실행 창과 별도로 시작한 API·worker를 모두 종료한다. 최신 삭제 이력이 있는 현재 DB를 `--data-dir`에 반드시 지정한다. 과거 백업만으로 빈 삭제 목록을 만들어 복원하지 않는다.

```powershell
.venv/Scripts/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" restore "E:/K-DOG/backup-20260906" "D:/K-DOG/restored-20260906"
.venv/Scripts/python.exe -X utf8 -m app.launcher --data-dir "D:/K-DOG/restored-20260906"
```

복원은 새 폴더만 허용하고 해시·DB·참조 파일·삭제 목록을 검증한다. 복원 후 키는 개발자가 다시 등록한다. 새 PC로 옮길 때도 최신 삭제 이력 DB를 안전하게 보존한다. 복원 경로 확인 후 `KDOG_DATA_DIR`를 바꿔 Start.cmd가 같은 폴더를 사용하게 한다. 삭제 요청은 제공 차단이며, 실제 정리는 종료 후 `clean --purge-deleted`로 수행한다. 기존 외부 내보내기·과거 백업을 회수하지 않는다.

## 사용량·비용 측정

신뢰하는 로컬 관리자가 실행하는 CLI다. 운영 DB의 삭제되지 않은 참가자에 대해 행사/참가자/run/단계/시도별 예약 호출·원래 token 계량값·상태·run 접수부터 최종 갱신까지 시간을 JSON으로 출력한다. 이름·영상·프롬프트·키·공급자 오류 원문은 포함하지 않지만 참가자 ID가 있으므로 출력은 자료 폴더처럼 관리한다. 개발자 합성 시험 이력은 별도이며 운영 합계에서 제외한다.

```powershell
.venv/Scripts/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" usage-report --event-id EVENT-01
.venv/Scripts/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" usage-report --event-id EVENT-01 --prices "D:/K-DOG/prices.json"
```

선택적 단가 파일의 구조는 다음과 같다. 아래 수치는 **계산 예시용 가상 단가**이며 실제 모델 가격이 아니다. `models`의 키는 사용량 보고서에 기록된 정확한 `provider/model` 문자열이다. 단가는 해당 계량 필드 **백만 단위당** 입력 통화 금액이다. 원화 환산을 원하면 운영자가 확인한 환율로 환산한 단가를 넣고 source에 단가 출처와 환율을 기록한다.

```json
{
  "currency": "TEST",
  "as_of": "2026-09-06",
  "source": "가상 계산 예시; 운영 사용 전 공식 단가·환율 확인 필요",
  "models": {
    "example/model": {"input_tokens": "2", "output_tokens": "4"}
  }
}
```

`known_meter_cost_estimate`는 계산 가능한 호출의 부분 합계이고 `complete_meter_cost_estimate`는 모든 예약 호출의 지정 계량값이 있고 미계측 단계가 없을 때만 값이 있다. 단가/계량값 누락, 실행 중·중단·응답 유실 호출은 미확인으로 남는다. 재시도는 매번 포함하며 재사용 산출물은 `reused_ai_steps`로 구분하고 원본 usage를 다시 과금 합산하지 않는다. 예약 표시가 없는 M5 이전 단계 등은 `unreserved_ai_steps`에 포함하고 비용 집계에서 제외하며 전체 추정도 null로 둔다.

이 값은 **사용자가 지정한 계량식의 추정**이며 실제 청구액·모든 과금 항목의 완전성·통화 예산 차단을 보장하지 않는다. total/input/output·캐시·추론 계량값은 서로 중첩될 수 있으므로 무조건 모두 더하지 않는다. 모델별 장문 구간·미디어·캐시 할인·추론·기타 과금의 계산식은 공식 가격표와 청구서로 대조해야 한다. 기존 앱의 한도는 호출 횟수/출력 토큰 한도다. 확인되지 않은 가격을 기본값으로 넣지 않는다.

## 파일럿 순서와 완료 수준

1. 해당 PC의 설치 확인 → 로그인·직원/개발자 권한 → 키 연결 시험 → 허용된 실제 샘플 1명으로 관찰·평가·설명과 근거 품질을 확인한다. 공급자 시험 버튼은 실제 비용이 발생할 수 있다.
2. 20명·카메라 2대·각 3분을 계획 시나리오로 입력하고 참가자별 첫 결과 시각, 전체 종료 시각, 영상 바이트, 사용량/청구액, 오류·재시도, PDF/XLSX/CSV 누락을 기록한다. 이 수치는 등록 상한이나 처리 시간 보장이 아니다.
3. 업무가 없는 시간에 백업 → 종료 → 새 폴더 복원 → 키 재등록 → 결과/내보내기 재조회 → 미완료 작업 재개를 확인한다.
4. 실제 촬영의 음성·가림·짧은 반응, 미정 계산 규칙, 장비 성능·저장 공간·절전·자료 보관 정책을 책임자가 확인한 뒤 현장 사용 준비 여부를 판단한다.

M6 자동 부하 검증은 합성 640×360 10fps H.264/AAC 영상의 전체 디코딩과 실제 DB·점수·리포트·내보내기·복원을 사용한다. AI는 테스트 코드에서 주입한 가상 공급자이며 실제 API 지연/제한/과금/품질과 현장 영상 비트레이트를 대표하지 않는다. 운영 패키지에는 가상 공급자·테스트 도구가 없다. 새 폴더/새 가상환경 시험은 별도 물리 PC 또는 깨끗한 Windows VM 검증을 대체하지 않는다.
