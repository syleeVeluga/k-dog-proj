# K-DOG 발행 .env 계정·AI 키 사전 등록 계획

버전: v1.0 · 2026-10-23 · 기준: `main / 972afea` (v0.3.2) · S1.1 · 상태: 계획 (구현 전)

## 배경과 결정

[설치 계정과 발행 키 기간 계획](K-DOG_설치계정과발행키기간_v1.0_20261023.md)(v0.3.1)은 첫 업무 계정을 설치 창에서 입력하고 AI 공급자 키는 동봉하지 않기로 했다. 2026-10-23 사용자는 운영 편의를 위해 이 결정을 **뒤집었다**.

| 항목 | 2026-10-23 변경 결정 |
| --- | --- |
| 계정 | 발행 때 **개발자 계정 1개와 고객 마스터(업무) 계정 1개**를 고정해 넣는다. 이후 사용자는 로그인 후 「직원 계정」에서 추가한다. |
| AI 공급자 키 | Gemini 주키(선택: 예비키)를 **발행 때 같이 봉인**하고 설치 프로그램이 그 PC의 DPAPI로 등록한다. |
| 입력 방식 | 대화식 프롬프트 대신 기관별 **`.env` 파일**을 발행 스크립트가 읽는다. |
| 적용 단계 | **`issue_release.py`(기관별 발행)에서만** 읽는다. `build_release.py`(평문 포터블 ZIP)는 바꾸지 않는다. |
| 구현 원칙 | 최소 변경. 새 화면·서비스 없음. 기존 `provision-accounts`·`create-first-user` 경로는 호환 유지. |

"고객 마스터 계정"은 일반 `operator` 업무 계정이다. [업무 권한 단순화 정책](K-DOG_업무권한단순화계획_v1.1_20261011.md)에 따라 모든 활성 업무 계정은 동등하므로 특권은 없고, 이름만 고정된 첫 계정이다.

### 왜 빌드가 아니라 발행 단계인가

- 평문 포터블 ZIP은 모든 고객 공통이며 암호화가 없다. 여기에 해시나 키를 넣으면 ZIP을 받은 누구나 해시를 오프라인 크래킹하거나 키를 평문으로 읽는다.
- 발행 패키지는 기관별 발행 키로 AES-GCM 봉인되고, 설치 프로그램은 `provision.json`을 디스크에 풀지 않고 메모리에서만 쓴다([kdog_install.py `install_files`](../../scripts/windows/kdog_install.py)). 계정 해시와 키 모두 이 경로를 타야 설치 전까지 보호된다.
- 공급자 키는 Windows DPAPI(PC·Windows 사용자 바인딩)로 저장되므로([secrets.py `protect`](../../backend/app/secrets.py)) 빌드·발행 시점에는 암호화할 수 없다. 설치 PC에서 설치하는 Windows 사용자가 등록해야 한다.

### 받아들이는 위험 (사용자 확인)

- 기관 내 모든 PC가 같은 두 계정 비밀번호와 같은 Gemini 키를 공유한다. 한 PC·한 사람의 유출이 전 PC 유출이다.
- ZIP·발행 키·`.env` 내용을 가진 사람은 유효 기간 안에 어느 PC에든 설치해 **발행자 Google 프로젝트 비용으로** AI 분석을 돌릴 수 있다. 종전의 "무단 설치본은 로컬 업무만" 통제가 사라진다.
- 키 유출 대응은 공급자 콘솔 취소 + 재발행 + 전 PC에서 「공급자 키 관리」 교체(또는 재설치)다.
- 완화: 기관별 별도 Gemini 키(프로젝트 또는 키 분리) 사용, `--expires`를 짧게, 발행 기록에 키 지문만 남겨 어느 기관에 어느 키가 나갔는지 추적, `.env`는 발행 PC 밖으로 내보내지 않음. 첫 로그인 비밀번호 강제 변경은 이번 범위 밖(필요 시 별도 계획).

## 범위

1. `issue_release.py`: `--env <파일>`로 계정·키·기간을 읽어 봉인. 기존 `--user/--admin/--developer/--expires` 프롬프트 방식은 그대로 두고 둘 중 하나만 쓴다.
2. `provision.json`: `secrets` 항목 추가(선택). `provision_accounts`는 무시한다.
3. `app.manage provision-secrets`: 표준입력 JSON의 키를 개발자 계정을 행위자로 하여 DPAPI 등록(설치 프로그램용).
4. `kdog_install.py`: 계정 생성 뒤 키가 있으면 등록. 업무 계정이 있으면 첫 계정 입력은 자연히 건너뛴다(기존 동작).
5. 시험·`verify_release`·문서.

제외: `build_release.py`·평문 ZIP 변경, macOS·사용자 설치형(online) 패키지, OpenAI/Anthropic 키 동봉(요청 없음), 첫 로그인 비밀번호 변경, 설치 대수 제한, 「직원 계정」 화면 변경, 실제 공급자 호출(설치 시 연결 시험을 하지 않는다).

## 설계

### 1. `.env` 입력 (`issue_release.py`)

`--env <경로>`를 추가한다. 형식은 `KEY=VALUE` 한 줄씩, `#` 주석과 빈 줄 허용, 값의 양끝 작은·큰따옴표 제거. 표준 라이브러리로 직접 파싱하며 `python-dotenv`를 추가하지 않는다(새 의존성 없음 → 버전 검증 대상 없음).

| 키 | 필수 | 의미 |
| --- | --- | --- |
| `KDOG_DEVELOPER_USER`, `KDOG_DEVELOPER_PASSWORD` | 키를 넣을 때 필수 | 개발자 계정 (키 등록 행위자) |
| `KDOG_MASTER_USER`, `KDOG_MASTER_PASSWORD` | 선택 | 고객 마스터 업무 계정 (`operator`) |
| `GEMINI_API_KEY` | 선택 | Gemini 주키 |
| `GEMINI_API_KEY_BACKUP` | 선택 | Gemini 예비키 (주키와 달라야 함) |
| `KDOG_EXPIRES` | 선택 | 설치 가능한 마지막 날 `YYYY-MM-DD`. `--expires`가 있으면 명령줄 우선 |

규칙:

- `--env`와 `--user/--admin/--developer`를 함께 쓰면 거절한다(입력 경로 하나만).
- 계정 검증은 기존 `issue()`와 같다(아이디 형식, 예약 이름, 비밀번호 12~256자, 각 역할 최대 1개, 서로 다른 아이디). 둘 다 없으면 거절.
- 키가 하나라도 있으면 개발자 계정이 필수다(`secrets.change`가 활성 개발자 행위자를 요구한다). 주키 없이 예비키만은 거절. 두 키가 같으면 거절. 키는 공백 제거 후 8~512자(화면 입력 규칙과 동일).
- 알 수 없는 키 이름은 거절한다(오타로 비밀이 빠지는 것을 막는다).
- `.env`는 이미 `.gitignore`(`.env`, `.env.*`) 대상이다. 예시 파일 `scripts/issue_release.env.example`을 추가한다(값 없음).
- 발행 기록 JSON에는 `"secrets": {"gemini": {"primary": "<sha256 앞 12자>", "backup": ...}}` 지문만 남긴다. 키 원문·비밀번호·발행 키는 기록·콘솔 어디에도 남기지 않는다. 콘솔에는 "Gemini 주키·예비키 동봉"처럼 슬롯 이름만 출력한다.

### 2. `provision.json`

기존 `"format": "kdog-provision-1"`을 유지하고 선택 항목을 더한다.

```json
{"format": "kdog-provision-1", "customer": "...", "issued_at": "...",
 "accounts": [...],
 "secrets": {"gemini": {"primary": "<키>", "backup": "<키 또는 생략>"}}}
```

- `provision_accounts()`는 `secrets`를 읽지 않는다(검증식이 최상위 추가 키를 허용함을 시험으로 고정한다).
- `secrets`가 있으면 `accounts`에 `developer`가 있어야 한다. 이는 발행과 `provision-secrets` 양쪽에서 검증한다.

### 3. `app.manage provision-secrets` (`backend/app/auth.py` 또는 `secrets.py`)

표준입력으로 같은 `provision.json`을 받는다.

- 검증: 형식·고객 ID·`secrets.gemini.primary` 문자열(8~512자)·선택 `backup`(주키와 다름)·`accounts`의 개발자 아이디 존재. 그 개발자가 DB에 활성 `developer`로 있어야 한다(직전 `provision-accounts` 결과).
- 슬롯별 처리: 이미 `available`한 키가 등록돼 있으면 **바꾸지 않고** "기존 키를 유지합니다"를 출력한다(계정의 "기존 비밀번호 유지"와 같은 원칙. 교체는 개발자가 「공급자 키 관리」에서). 없거나 제거 상태이면 `secrets.change(store, "gemini", value, developer, slot=slot)`로 등록한다. 이 함수가 DPAPI 보호 파일 생성·`secret.change` 감사·퇴역 파일 정리를 모두 수행하므로 새 저장 경로를 만들지 않는다.
- 추가 감사: `secret.provisioned` `{slot, reference, customer}`(행위자 = 개발자 계정). 값은 기록하지 않는다.
- 출력은 슬롯 이름과 결과만. 예외(`ValueError`, `HTTPException`, `sqlite3.Error`)는 "키 등록 실패: …"로 종료 코드 1. DPAPI 불가(비Windows·다른 사용자)는 `HTTPException(409)`가 그대로 메시지가 된다.
- 설치 프로그램 외 수동 실행도 가능하지만 안내하지 않는다.

### 4. 설치 프로그램 (`kdog_install.py`)

`provision-accounts` 성공 뒤, `provision.json`에 `secrets`가 있으면 같은 바이트를 `provision-secrets`에 표준입력으로 넘긴다.

- 실패하면 "AI 키를 등록하지 못했습니다. 프로그램 파일과 계정은 설치되었습니다. 로그인 후 「개발 설정 → 공급자 키 관리」에서 등록하세요."를 출력하고 종료 코드 1(바로가기 없음). 계정 실패와 같은 처리다.
- 키는 설치 프로그램 변수와 자식 프로세스 표준입력에만 있고 파일·로그·화면에 나오지 않는다. `install_files`의 `provision.json` 미추출 규칙은 그대로다.
- 그 뒤 `first_user()`는 업무 계정이 있으면 `exists`로 끝나므로 묻지 않는다. 개발자만 발행한 패키지는 지금처럼 묻는다.
- 완료 문구에 "AI 키가 등록된 경우 같은 Windows 사용자로 실행해야 합니다"를 추가한다.
- 한계(문서 명시): 설치 프로그램이 다른 Windows 사용자(예: 관리자 계정)로 실행되면 DPAPI가 그 사용자에 묶여 앱 실행 사용자가 `decrypt_failed`를 본다. 운영 안내에 "앱을 쓸 Windows 사용자로 Install.cmd를 실행"을 명시한다.

### 5. 문서

- [PILOT_OPERATIONS.md](../PILOT_OPERATIONS.md) 「발행」·「사용자 설치」·「AI 키 등록과 비밀번호 분실」·「보안 경계」: `.env` 발행 예시, 동봉 키의 위험과 완화(기관별 키, 짧은 기간, 유출 시 절차), 같은 Windows 사용자 설치, 기존 키 유지 규칙, `.env` 보관 원칙(발행 PC 밖 반출 금지, 발행 후 삭제 권장).
- [DEVELOPMENT.md](../DEVELOPMENT.md) 「패키지와 종단 리허설」: `--env` 예시, `verify_release` 검사 항목.
- [설치안내.txt](../../scripts/windows/설치안내.txt): "앱을 쓸 Windows 사용자로 설치", "전달받은 계정으로 로그인".
- 이 계획서에 실행 기록 링크를 추가하고 종전 계획서 상단에 "2026-10-23 결정 변경, 이 계획으로 대체"를 적는다.

## 변경 파일

| 파일 | 변경 |
| --- | --- |
| `scripts/issue_release.py` | `--env` 파싱·검증, `issue(..., secrets=None)`, 기록 JSON 지문, 콘솔 안내 |
| `scripts/issue_release.env.example` | 신규, 값 없는 예시 |
| `backend/app/auth.py` (또는 `secrets.py`) | `provision_secrets(db, store, document)` |
| `backend/app/manage.py` | `provision-secrets` |
| `scripts/windows/kdog_install.py` | 키 등록 단계, 안내 문구 |
| `scripts/verify_release.py` | 합성 `.env`로 발행, 설치 후 슬롯 상태·노출 검사 |
| `backend/tests/test_issued_release.py` | 아래 시험 |
| `docs/PILOT_OPERATIONS.md`, `docs/DEVELOPMENT.md`, `scripts/windows/설치안내.txt`, 종전 계획서 | 절차·안내 |

## 검증 (성공 기준)

`backend/tests/test_issued_release.py`에 추가(합성 값만, 실제 공급자 호출 없음):

1. `.env` 파싱: 주석·빈 줄·따옴표 처리, 알 수 없는 키 거절, `--env`와 계정 옵션 동시 사용 거절, `KDOG_EXPIRES`와 `--expires` 우선순위.
2. `issue()` 검증: 키만 있고 개발자 없음·예비키만·주키=예비키·길이 위반을 쓰기 전에 거절. 정상 발행의 `provision.json`에 키가 있고, 발행 ZIP·기록 JSON·콘솔 출력 어디에도 키 원문·비밀번호가 없다(기존 `test_issue_seals_product_and_accounts_and_records_no_secret` 확장). 기록 JSON의 지문이 키의 SHA-256 앞 12자다.
3. `provision_accounts()`는 `secrets`가 있는 문서를 받아 계정만 만든다.
4. `provision_secrets()`: 개발자가 있으면 주키(·예비키)를 등록하고 `secret.change`·`secret.provisioned` 감사가 남으며 `slot_states`가 `vault`·`available`이다. 이미 등록된 슬롯은 유지한다. 개발자가 없거나 비활성이면 거절. `protect` 실패(409)는 종료 코드 1과 메시지(DPAPI는 `test_gemini_key_slots.py`와 같이 `patch("app.secrets.protect")`로 격리).
5. `manage provision-secrets`는 표준입력을 읽고 실패를 종료 코드 1로 보고하며 출력에 키 값이 없다.
6. 설치 프로그램 흐름(fixture 서브프로세스): 계정 → 키 등록 → 첫 계정 입력 생략 → 바로가기. 키 등록 실패 시 종료 코드 1과 안내. 개발자만 발행한 패키지는 기존처럼 첫 계정을 묻는다.

`verify_release.py verify_issued`: 합성 `.env`(개발자·마스터·합성 주키)로 발행 → 발행 ZIP에 키 바이트 없음 → 설치 → 마스터 계정 로그인·접수 → 개발자 `developer/settings`에서 `primary`가 `vault`·`available`, `backup`은 미등록 → 재설치 시 키·계정 유지. 기존 "새 패키지는 두 슬롯 미등록" 검사는 사용자 설치형(online)에만 남긴다.

수동 실측(실행 기록에 별도 기재): 실제 Gemini 키로 발행한 패키지를 물리 PC에 설치하고 「공급자 키 관리」 연결 시험이 성공하는지, 다른 Windows 사용자로 실행했을 때 `decrypt_failed`가 보이는지.

## PR 절차

1. 브랜치 `veluga/issue-env-provision-20261023`에서 구현 → `uv run --locked python -X utf8 -m unittest discover -s tests -v` → `build_release.py` + `verify_release.py` 리허설.
2. 코드 리뷰·콜드 리뷰 → 수용 항목 반영 → 실행 기록 `K-DOG_발행계정키사전등록_실행기록_v1.0_<날짜>.md` 작성 → PR.
3. 패치 릴리스는 별도 PR(`K-DOG_패치릴리스_v0.3.3_<날짜>.md`).
