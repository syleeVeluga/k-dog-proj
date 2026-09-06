# K-DOG Windows 설치·파일럿 운영 안내

버전: v1.0 · 2026-09-06 · M6

## 설치

대상은 신뢰하는 Windows 10/11 x64 PC와 전용 Windows 실행 계정이다. 앱의 관리자/개발자 로그인과 Windows 실행 계정은 별개다. API와 worker, 키 등록은 같은 Windows 계정으로 실행한다. 설치에는 인터넷이 필요하며 실행 시 Node.js·npm·Git은 필요 없다.

1. 개발자가 [uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)와 [FFmpeg 공식 다운로드 안내](https://ffmpeg.org/download.html)에 따라 uv와 FFmpeg/ffprobe를 설치하고 PATH에 등록한다. 새 터미널에서 `uv --version`, `ffmpeg -version`, `ffprobe -version`을 확인한다. FFmpeg에는 H.264/AAC 디코더와 libx264/AAC 인코더가 필요하다.
2. 제공받은 ZIP과 `.sha256`을 대조하고 **새 프로그램 폴더**에 압축을 푼다. 예: `C:/K-DOG/app-m6`. `release.json`은 파일 무결성 목록이며 서명/배포자 인증을 대체하지 않는다.
3. 다른 자료 경로를 쓸 때에는 먼저 사용자 환경 변수 `KDOG_DATA_DIR`를 설정한다. 기본은 `%LOCALAPPDATA%/K-DOG/data`다. 자료를 프로그램 폴더 안에 두지 않는다. 새 터미널/탐색기가 해당 환경 변수를 읽도록 한다.
4. `Install.cmd`를 실행한다. 파일 해시를 확인한 뒤 잠금 파일에 지정된 운영 의존성과 Python 3.14 환경을 설치한다. 운영 관리자와 개발자 계정 이름을 입력하고 각각 12~256자 비밀번호를 숨김 입력한다. 기존 계정이 있으면 해당 이름 질문에서 Enter로 건너뛴다. 기본 계정이나 기본 비밀번호는 없다.
5. `Start.cmd`를 실행한다. API·worker 준비 확인 후 `http://127.0.0.1:8000`을 연다. 운영 관리자가 직원 계정을 발급하고, 개발자가 키·모델·설정을 등록한다. 설치나 시작은 공급자 연결 시험을 자동 실행하지 않는다.

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
