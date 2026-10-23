# K-DOG 설치 계정 생성과 발행 키 유효 기간 계획

버전: v1.0 · 2026-10-23 · 기준: `main / cd139c6` (v0.3.1) · S1.1 · 상태: 구현·검증 완료, 현장·물리 PC 실측 별도 ([실행 기록](K-DOG_설치계정과발행키기간_실행기록_v1.0_20261023.md))

## 배경과 결정

현재 발행 패키지([issue_release.py](../../scripts/issue_release.py))는 업무 계정 1개와 선택 개발자 계정 1개를 scrypt 해시로 봉인해 넣고, 설치 프로그램([kdog_install.py](../../scripts/windows/kdog_install.py))이 `provision-accounts`로 만든다. 운영자·교수가 앱에서 직접 가입할 방법은 없고, 로그인한 업무 계정이 「직원 계정」에서 추가하는 방식만 있다. 발행 키는 PC·기간 제한이 없어 ZIP과 키를 받은 사람은 언제든 어느 PC에든 설치할 수 있다.

2026-10-23 사용자 결정:

| 항목 | 결정 |
| --- | --- |
| 설치 구조 | 중앙 서버 없이 **PC마다 설치**한다. 발행은 **기관별 1개**다. |
| 첫 업무 계정 | 발행 때 미리 넣지 않고 **설치 창에서 담당자가 직접 입력**한다. 이후 사용자는 「직원 계정」에서 추가한다. |
| AI 공급자 키 | 변경 없음. 개발자 계정으로 PC마다 「개발 설정 → 공급자 키 관리」에서 등록한다 ([운영 안내](../PILOT_OPERATIONS.md#ai-키-등록과-비밀번호-분실)). |
| 발행 키 | **유효 기간을 지정**할 수 있어야 한다. 기간이 지난 패키지는 설치되지 않는다. |
| 구현 원칙 | 최소 변경. 새 화면·새 서비스·온라인 활성화 서버를 만들지 않는다. |

설치 대수를 기술적으로 제한하는 것은 범위 밖이다. 발행 키 유효 기간은 "설치할 수 있는 기간"을 좁혀 ZIP·키가 늦게 유출되어도 설치되지 않게 하는 통제이며, 이미 설치된 앱의 실행은 막지 않는다. AI 분석은 개발자가 키를 등록한 PC에서만 가능하므로 무단 설치본에서는 로컬 업무만 된다.

## 범위

1. 발행 키 유효 기간(`expires`) — 발행·헤더 검증·설치 거절.
2. 설치 시 첫 업무 계정 입력 — 발행 패키지의 업무 계정을 선택 항목으로 바꾸고 설치 프로그램이 없을 때만 묻는다.
3. 문서·검증 갱신.

제외: API 키 동봉, PC별 바인딩, 설치 횟수 제한, 앱 실행 시 기간 검사, 첫 로그인 비밀번호 강제 변경, 「직원 계정」 화면 변경, macOS·사용자 설치형(online) 패키지(발행 대상이 아니므로 변경 없음).

## 설계

### 1. 발행 키 유효 기간

- `issue_release.py`에 `--expires YYYY-MM-DD`(선택)를 추가한다. 생략하면 기존처럼 무기한이다. 과거 날짜는 발행 전에 거절한다.
- `kdog_install.seal()`의 헤더에 `"expires": "YYYY-MM-DD"`를 넣는다. 헤더 전체가 AES-GCM 연관 데이터이므로 **기간만 지우거나 늘리면 키가 맞아도 인증에 실패**해 아무것도 설치되지 않는다. 별도 서명·서버가 필요 없다.
- `read_header()`는 `expires`가 있으면 `YYYY-MM-DD` 형식만 허용하고, 없으면 기존 패키지로 본다(기존 발행 패키지 호환).
- 설치 프로그램은 헤더를 읽은 직후·키를 묻기 전에 `date.today() > expires`이면 "이 설치 패키지의 유효 기간(YYYY-MM-DD)이 지났습니다. 아무것도 바꾸지 않았습니다." / "새 설치 패키지를 요청하세요. 문의처: …"를 출력하고 종료한다. 디스크에 아무것도 쓰지 않는다. 기간 마지막 날까지 설치할 수 있다(시간 없이 날짜만 비교, 설치 PC 현지 날짜 기준).
- 발행 기록 JSON과 콘솔 출력에 유효 기간을 남긴다.
- 한계(문서에 명시): 오프라인 PC의 시계를 신뢰하고, 설치 프로그램은 ZIP 안에 평문으로 있다. 키를 가진 사람은 시계를 되돌리거나 설치 프로그램을 고쳐 기간 뒤에도 설치할 수 있으므로 이 기간은 늦게 유출된 ZIP·키의 정상 설치를 막는 수단이지 강제 수단이 아니다. 앱 실행은 기간과 무관하다.

### 2. 설치 시 첫 업무 계정 입력

- `issue_release.py`: `--user`/`--admin`을 선택 항목으로 바꾼다(기존 호환 유지). `--developer`만으로 발행할 수 있다. 업무·개발자 계정은 각각 최대 1개이고 둘 다 없으면 거절한다. 개발자 없이 발행하면 그 패키지로는 AI 키를 등록할 수 없다.
- `auth.provision_accounts()`: 업무 계정 "정확히 1개" 조건을 "0개 또는 1개"(개발자도 최대 1개)로 완화한다. 나머지 검증(형식·역할·중복·기존 계정 보존)은 그대로다.
- 예약 이름(`builtin-reference`, `kdog-ai-service`)은 앱이 나중에 비활성 기록용 계정으로 넣으므로 `auth.reserved_username()`으로 발행(`issue()`)·`provision_accounts`·첫 계정 모두에서 거절한다.
- `app.manage`에 `create-first-user` 하위 명령을 추가한다. 표준입력 JSON `{"username","password"}`를 읽어 **활성 업무 계정(operator/reviewer/admin)이 하나도 없을 때만** `operator` 계정을 만들고 `user.local_create`(`source: installer`)로 감사 기록한다. 이미 있으면 아무것도 바꾸지 않고 그 사실만 출력한다. 이미 있는 아이디(개발자·비활성 계정 포함)와 예약 이름은 거절한다. 기존 `create_user`·비밀번호 규칙(12~256자)을 재사용한다. `--check`는 읽기 전용으로 `needed` 또는 `exists`만 출력한다.
- `kdog_install.main()`: `provision-accounts` 뒤에 `create-first-user --check`로 활성 업무 계정 유무를 판단한다(설치 프로그램이 DB를 직접 열지 않는다). 확인 자체가 실패하면 오류(종료 코드 1, 바로가기 없음)로 끝나며 프로그램 파일과 발행 계정은 남는다.
  - 없으면 "이 PC에서 처음 쓸 업무 계정을 만듭니다"라고 안내하고 아이디(영문·숫자·`_-`), 비밀번호(콘솔이면 getpass, 두 번)를 묻는다. 비밀번호는 명령 인자가 아니라 표준입력 JSON으로 넘긴다. 형식·확인 불일치·거절이면 다시 묻는다.
  - 아이디에서 Enter만 누르면 건너뛰고 "로그인하기 전에 Install.cmd를 다시 실행하면 다시 묻습니다"를 안내한다. 같은 버전 재실행은 파일 확인만 하고 이 단계로 돌아온다. 예약 이름 검사를 우회하는 수동 명령은 안내하지 않는다. 프로그램 파일 설치는 성공으로 둔다.
  - 재설치·업그레이드처럼 이미 업무 계정이 있으면 묻지 않는다.
- 설치 완료 문구에 "다른 운영자·교수 계정은 로그인 후 「직원 계정」에서 추가합니다."를 넣는다.

### 3. 문서

- [PILOT_OPERATIONS.md](../PILOT_OPERATIONS.md) 발행·사용자 설치 절: `--expires`, 개발자만 발행, 설치 중 첫 계정 입력, 기간 만료 시 재발행, 「직원 계정」 안내.
- [설치안내.txt](../../scripts/windows/설치안내.txt): 4번 뒤에 "첫 업무 계정 만들기" 단계와 "유효 기간이 지나면 설치되지 않으니 새 패키지를 요청" 문구.
- [DEVELOPMENT.md](../DEVELOPMENT.md) 발행 예시 명령.

## 변경 파일

| 파일 | 변경 |
| --- | --- |
| `scripts/issue_release.py` | `--expires`, `--user/--admin` 선택화, 기록 JSON에 `expires` |
| `scripts/windows/kdog_install.py` | `seal`/`read_header`의 `expires`, 설치 전 기간 검사, 첫 계정 입력 |
| `backend/app/auth.py` | `provision_accounts` 업무 계정 0~1개 허용, `reserved_username`, `first_user_needed`, `create_first_user` |
| `backend/app/manage.py` | `create-first-user` |
| `scripts/verify_release.py` | 합성 고객 `VERIFY`를 개발자만으로 발행, 설치 입력에 첫 계정 응답 추가, 만료 패키지 거절 확인 |
| `backend/tests/test_issued_release.py` | 아래 시험 |
| `docs/PILOT_OPERATIONS.md`, `docs/DEVELOPMENT.md`, `scripts/windows/설치안내.txt`, `README.md`, `docs/archive/README.md` | 절차·안내 |

## 검증 (성공 기준)

`backend/tests/test_issued_release.py`에 추가:

1. 헤더 `expires` 왕복: 발행 시 지정한 날짜가 헤더에 있고, 날짜를 바꾸거나 지운 헤더는 올바른 키로도 `WrongKey`다.
2. `read_header`는 `expires` 없는 기존 헤더를 받고, 형식이 틀린 값은 `PackageError`다.
3. 설치 프로그램은 만료된 패키지에서 키를 묻기 전에 종료하고 설치 폴더·바로가기·자료를 만들지 않는다. 마지막 날은 `expired()`가 거짓(날짜 주입)이고, 오늘이 마지막 날인 패키지는 `main()`에서 키 입력 단계까지 진행한다.
4. `issue()`는 개발자만으로 발행하고, 계정 0개·과거 `--expires`는 쓰기 전에 거절한다. 기록 JSON에 `expires`가 있고 키·비밀번호는 없다.
5. `provision_accounts`는 개발자만 있는 문서를 받고, 업무 계정 2개는 거절한다.
6. `create-first-user`: 활성 업무 계정이 없으면 만들고 감사 기록을 남긴다. 있으면 바꾸지 않는다. 비밀번호 길이·아이디 형식 위반은 거절한다.
7. 설치 프로그램 흐름(fixture 서브프로세스): 첫 계정 입력 → 생성, Enter 건너뛰기 → 수동 명령 안내, 재설치 → 묻지 않음.

명령: `uv run --locked python -X utf8 -m unittest tests.test_issued_release tests.test_packaging -v`, `git diff --check`. `scripts/verify_release.py`의 발행 검증을 실제 포터블 ZIP으로 1회 실행해 결과를 실행 기록에 남긴다. 깨끗한 OS·물리 PC 실측은 별도다.

## PR

브랜치 `veluga/install-first-user-20261023` 하나로 구현 → 시험 → 독립 검토 → 수정 → 푸시한다. 실행 기록은 같은 폴더에 `K-DOG_설치계정과발행키기간_실행기록_v1.0_<날짜>.md`로 남긴다. 발행 패키지 형식은 `kdog-provision-1`·헤더 `format`을 유지하므로 이미 발행된 패키지는 새 설치 프로그램 없이도 그대로 설치된다.
