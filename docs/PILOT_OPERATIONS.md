# K-DOG Windows 설치·S1 운영 안내

버전: v1.6 · 2026-10-05 · 통합명세 v1.3 / S1.1

## 일반 사용자 실행

설치 담당자가 준비한 앱 폴더의 `Start.cmd`를 실행한다. 실행 창(제목 K-DOG)이 뜨고 준비되면 브라우저가 자동으로 열린다. 열리지 않으면 창에 표시된 주소로 접속한다. 이미 실행 중일 때 다시 실행하면 새로 시작하지 않고 브라우저만 연다 (먼저 누른 실행이 준비 중이면 최대 30초 기다린다). 다른 폴더나 이전 버전의 K-DOG가 같은 포트에서 실행 중이면 안내 후 멈추므로, 그 실행 창을 닫고 다시 실행한다. 중앙 서버 운영에서는 촬영 PC마다 앱을 설치하거나 DB를 만들지 않고 담당자가 전달한 동일 HTTPS 주소를 브라우저에서 연다. 앱 계정은 Windows 계정과 별개이며 기본 비밀번호는 없다. 업무 중 중앙 서버와 실행 창을 유지하고(작업 중에는 최소화), 종료할 때 실행 창을 닫거나 Ctrl+C를 눌러 API·worker를 함께 종료한다. 브라우저 탭만 닫아도 서버 작업은 계속된다.

실제 영상·장비 품질과 시간, 실제 중앙 서버/3PC·깨끗한 OS 검수는 [후속 대장](개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md) E01–E10에 있다. 합성 시험이나 현재 Windows의 새 폴더 설치를 현장 검수 완료로 해석하지 않는다.

배포 ZIP에는 이 안내와 계획·후속 문서가 포함된다. 개발 명령·시험 근거는 [소스 저장소](https://github.com/syleeVeluga/k-dog-proj)에서 `release.json`의 commit을 선택해 확인한다. 개발용 시험·스크립트와 고객 원본은 설치 ZIP에 포함하지 않는다.

## 설치 담당자

대상은 Windows 11 x64와 Chromium 계열 브라우저다. Windows ARM/32비트/S모드·다른 OS는 검증 대상이 아니다. 프로그램·자료는 로컬 디스크에 두며 네트워크 공유·동기화 폴더·이동식 드라이브는 운영 검수 대상이 아니다. 공급자 키는 Windows DPAPI로 보호하므로 설치·키 등록·API·worker는 같은 Windows 사용자로 실행한다.

1. 개발자가 전달한 **S1 ZIP과 동일 이름의 SHA-256 파일**을 받는다. GitHub의 구판 v0.2.0 또는 자동 생성 Source code ZIP은 S1 설치물로 사용하지 않는다.
2. ZIP에는 Python 3.14와 잠금 의존성(`runtime/python`), FFmpeg/ffprobe(`runtime/ffmpeg`)가 들어 있다. uv·Python·FFmpeg를 따로 설치하거나 PATH에 등록하지 않으며 설치·실행에 인터넷이 필요 없다. FFmpeg는 GPL 2 이상이며 대응 소스는 `runtime/ffmpeg/source`에 있다. 동봉 오픈소스와 라이선스 위치는 `오픈소스고지.txt`를 본다.
3. 다음과 같이 ZIP hash를 검사하고 빈 새 폴더(예: `C:/K-DOG/app-s1`)에 푼다. ZIP 내부에서 직접 실행하지 않는다.

```powershell
$releaseZip = (Resolve-Path './kdog-s1-windows-x64.zip').Path
$expectedHash = ((Get-Content -LiteralPath "$releaseZip.sha256" -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$actualHash = (Get-FileHash -LiteralPath $releaseZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) { throw 'ZIP SHA-256 불일치' }
```

4. 자료 기본 경로는 `%LOCALAPPDATA%/K-DOG/data`다. 별도 자료 경로는 실행 전에 `KDOG_DATA_DIR`을 프로그램 밖 로컬 폴더로 지정한다. 기존 데이터 경로를 바꾸면 다른 DB가 열리므로 경로를 먼저 확인한다.
5. 계정은 프로그램 폴더에서 아래 명령으로 만든다. 비밀번호는 숨김 프롬프트로 입력한다. 최초 로그인 전에 관리자(`admin`) 계정이 반드시 있어야 하고, 공급자 키를 관리하려면 개발자(`developer`) 계정도 필요하다. 관리자가 직원용 operator/reviewer 계정을 발급한다. Node.js/npm/Git도 필요 없다.

   ```powershell
   runtime/python/python.exe -X utf8 -m app.manage create-user manager --role admin
   runtime/python/python.exe -X utf8 -m app.manage create-user key-manager --role developer
   ```

6. `Start.cmd --check`로 전체 파일 SHA-256(`release.json`)·Python·FFmpeg를 확인하고 `Start.cmd`를 실행한다. 기본 로컬 주소는 `http://127.0.0.1:8000`이다. 첫 실행으로 AI 호출이나 공급자 연결 시험을 자동 수행하지 않는다. 공급자 키 등록·연결 시험·실제 AI 분석은 명시 조작이며 비용이 발생할 수 있다.

조직 정책으로 차단되면 IT 담당자가 검토한다. `--check`가 손상을 알리면 ZIP을 새 빈 폴더에 다시 푼다. 업데이트는 앱 종료·백업 후 새 프로그램 폴더에 설치하고 같은 자료 경로를 지정한다.

## 구판에서 S1으로 전환

사용자가 승인한 전환 정책은 **기존 점수·분석·리포트·파생 결과 폐기, 원입력·원영상·접수·운영 기록 보존**이다. 구판 점수를 S1 점수로 읽거나 변환하지 않는다. 운영 앱을 종료한 뒤 아래 명령을 프로그램 폴더에서 실행한다. `--actor`는 활성 admin 계정이다.

```powershell
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" backup "E:/K-DOG/before-s1" --actor manager
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" reset-s1 --actor manager
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" reset-s1 --actor manager --apply
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" backup "E:/K-DOG/after-s1" --actor manager
```

미적용 명령은 대상 수를 보여준다. `--apply`는 원본 hash 검증과 고정 작업 계획으로 처리한다. 원격 공급자 파일 삭제 대기가 있으면 키 상태를 확인한 뒤 같은 자료 루트에서 `reset-s1 --actor manager --retry-remote`로 재시도한다. 초기화 재실행은 이미 고정한 작업만 처리하며 이후 새 S1 시트·결과를 지우지 않는다. 초기화 전 구판 백업은 S1 결과 복원용으로 허용되지 않는다. 원본 보존 백업으로 따로 관리한다.

2026-10-04 현재 로컬 운영 루트에서 백업 후 실제 전환을 수행했다. 참가자2·계정2와 원입력2·영상참조6의 hash를 보존하고 구판 run9/step111을 제거했다. 반복 초기화·초기화 이후 백업/새 폴더 복원·초기화 이전 백업 거절을 확인했다. 이 기록은 다른 PC/현장 전환을 완료한 뜻이 아니다.

## 중앙 서버와 촬영 PC3대

서버 한 대가 DB·원본·불변 산출물과 worker를 소유한다. 촬영 PC3대와 메인 조회 PC는 **같은 서버 주소**에 각 계정으로 접속한다. 각 PC의 `%LOCALAPPDATA%`에 별도 DB를 운영하도록 안내하지 않는다.

기본 `Start.cmd`는 loopback 감독 실행이다. 중앙 서버는 IT 담당자가 HTTPS 인증서·DNS·TLS reverse proxy를 준비한 후 다음 API와 worker를 각각 감독하여 실행한다. 아래 주소는 예시이므로 실제 인증서의 origin으로 바꾼다. proxy가 같은 서버이면 API는 loopback에 유지한다.

```powershell
# 중앙 서버 프로그램 폴더: 서로 별도 감독 프로세스
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" serve --host 127.0.0.1 --port 8000 --public-origin "https://kdog.example.org"
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" worker
```

proxy가 다른 호스트이면 방화벽에서 해당 proxy만 접근하도록 제한한 내부 주소에 bind하고 같은 HTTPS public origin을 지정한다. 앱은 Host와 변경 요청 Origin을 정확히 검사하고 HTTPS origin에는 Secure 세션 cookie를 사용한다. TLS proxy는 Host를 public origin과 동일하게 전달하고 `/api/`를 캐시하지 않아야 한다. 앱은 전달 IP 헤더를 신뢰해 인증을 우회하지 않는다. 개발 서버를 인터넷에 직접 공개하거나 TLS 없이 원격 접속하지 않는다.

IT 담당자는 실제 파일 크기·동시3업로드·전처리·PDF 완료를 기준으로 proxy 요청 본문/timeout·저장 공간·인증서 신뢰·방화벽을 검증한다. 약1GB 원본 세 개를 작은 합성 영상으로 대체해 대용량 검수를 통과 처리하지 않는다. 저장 공간은 원본+변환본+전처리+출력+백업을 포함해 확보한다. 부분 수신물·실패 batch를 성공으로 보지 않으며 상태 확인 후 같은 수신물의 연결을 정정해 불필요한 재전송을 피한다.

## 촬영부터 발급까지

1. **접수/설문** — 수동 접수 또는 Forms CSV/XLSX의 실제 헤더를 명시 대응하여 미리보기 후 등록한다. 행사·참가자·회차와 동의 항목을 확인한다. 설문 Q01–Q28의 28문항 원응답을 보존하며 0과 빈칸을 구별한다. Q26–Q28 감정의 일관성 문항을 포함한 원척도·역채점·유효 n을 확인하고, 부분 결측의 미정 정책을 임의 평균으로 확정하지 않는다.
2. **영상 수신/연결** — 각 촬영 계정이 파일을 수신함에 올리고 운영자가 정확한 참가자·회차·CAM1/2/3·원본 번호에 연결한다. 영상 먼저/접수 먼저 모두 가능하다. INSV는 보관할 수 있으나 대응 MP4의 변환 계보·hash·시각을 확인해야 분석한다.
3. **촬영 기록** — 실제 수행한 구간·사건·절차 이탈·미수행 사유·기준 영상과 카메라 offset을 확인한다. 예정 시각으로 실제 사건을 채우지 않는다. 새 회차와 기존 회차를 구분하고 수정하면 입력 revision이 새로 생긴다.
4. **전처리/채점** — 현재 입력을 확인해 전처리를 명시 실행한다. 사람은 본인 독립 시트에 원관찰·근거/검토메모를 구분하여 제출한다. 타인/AI 결과는 실제 공개 요청으로 노출 이력이 남는다. AI 분석은 입력·batch·설정·예산을 확인해 실행하며 중단/명시 재시도와 이전 실행 재사용을 구분한다.
5. **계산/의견/최종** — 원자료를 고정하여 계산하고 유효 수기 판정·완료 의견의 우선순위를 적용한다. 관찰 부족과 규칙 미정을 구별한다. 의견의 평가자·C31·해당 영역을 확인하며 유형 없는 문장으로 유형을 추론하지 않는다.
6. **리포트** — 최종결과 판본과 필요한 자체 비교 집단을 선택해 명시 발급한다. 상태·단계·차단 이유·재시도·이전을 조회한다. HTML/PDF/manifest는 발급 당시 고정 판본을 사용하며 입력 변경 뒤에는 이전 입력 기준임을 표시한다. 현재 삭제·동의 철회·권한 변경은 다운로드에도 적용한다. 인쇄·전달은 운영자 조작이며 고객에게 자동 발송하지 않는다.
7. **검수/연구** — 검수 자료의 XLSX 원셀·수식·저장 계산값과 평가자·판본·독립/AI노출·잠정/재확인/중단을 기록한다. 참고 등록은 현재 점수에 반영하지 않는다. 연구 내보내기는 명시 선택한 시트/결과/참고/cohort 판본을 고정한다. 알려진 식별값은 치환하지만 자유메모의 제3자 식별정보까지 자동 보장하지 않으므로 추가 제외어와 실제 연구 사용 범위를 확인한다. 독립 사람·최초 AI의 유효 항목 쌍만 비교 분모에 들어간다.

G01/G04 확인 전 실제 빈 Excel 채점양식 가져오기, D03/D04/D05의 미확정 세부 규칙, D06 확인 전 외부 평균/표준편차·국내 비교값은 보류한다. G02의 후보 문장을 교수님 확정 문장으로 표시하지 않는다. 나머지 검증된 프로그램 근거 설명과 정상 리포트 전체에 임의의 일괄 승인 의무를 추가하지 않는다.

## 백업·복원·삭제

백업에는 참가자 자료가 있으므로 접근·보관을 관리한다. 키와 로그인 세션은 제외한다. 원본·미연결 수신물·batch·시트·의견·발급물·검수 참고·비교 집단·연구 export까지 고정 참조를 검사한다. 복원/정리 전에 API·worker·전처리를 모두 종료한다.

```powershell
# 프로그램 폴더; 모든 대상은 새 폴더
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" backup "E:/K-DOG/backup-s1" --actor manager
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" restore "E:/K-DOG/backup-s1" "D:/K-DOG/restored-s1"
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" clean --purge-deleted
```

복원에는 최신 삭제 이력이 있는 현재 DB를 반드시 지정한다. 빈 DB로 삭제 목록을 대체하지 않는다. 동일 참가자의 ID 수정 이력과 삭제한 참고파일의 source hash도 다시 적용하여 옛 백업에서 되살아나지 않게 한다. 정리는 미참조 파일과 명시 삭제 대상만 제거한다. 외부에 이미 전달한 파일이나 과거 백업을 자동 회수하지 않는다. 복원 후 계정 세션은 다시 로그인하고 키는 개발자가 새 Windows 계정에 등록한다.

## 장애와 계량

같은 PC의 중복 실행은 브라우저만 다시 열고, 유지보수 작업 중이거나 다른 프로그램이 포트를 쓰거나 FFmpeg/자산이 없으면 시작 전에 거절한다. `Start.cmd --check`와 다음 명령으로 상태를 확인한다. 로그인 실패는 사용자/자료 경로를 먼저 확인하고 앱 종료 후 관리자가 `reset-password USERNAME`을 사용한다. 키 문제가 생기면 키 등록 때와 같은 Windows 사용자로 실행했는지 확인한다.

```powershell
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" recovery-status
runtime/python/python.exe -X utf8 -m app.manage --data-dir "D:/K-DOG/data" usage-report --event-id EVENT-01
```

중단 후 점유 만료·불변 파일 검증에 따라 복구하며 실패/검토필요를 성공으로 바꾸지 않는다. 응답 유실 외부 요청은 과금되었을 수 있다. 가격 미확인은 0원이 아니며 공급자 계량·재시도·재사용을 구분한다. 실측 시간/품질은 [S16 준비 도구](개발반영_20261003/K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md)로 실제 로그·동일조건·독립 정답을 고정해 기록한다. 로그 공유 시 이름·영상·키·비밀번호를 제거한다.
