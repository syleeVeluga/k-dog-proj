# PR-D03 암호화 발행과 설치

버전: v1.0 · 2026-10-05 · 상태: 구현 완료 (2026-10-05) · 선행: D01, D02 · 기준: main `6376311`

상위: [설치·배포 개선 계획](K-DOG_설치배포개선계획_v1.0_20261005.md). 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치 제안: `veluga/d03-issued-install` · 권장 PR 제목: `release: 고객별 암호화 발행과 키 입력 설치`

## 문제와 결과

결정 K02~K04를 구현한다. 개발자는 D01 평문 ZIP을 입력으로 고객별 암호화 패키지와 발행 키를 만든다. 사용자는 `Install.cmd`를 더블클릭하고 키를 한 번 입력한다. 그러면 설치, 계정 생성, 바탕화면 아이콘 생성이 끝난다.

D01에서 없앤 설치 단계가 여기서 **발행 패키지 전용 `Install.cmd`로 다시 생긴다.** 이번에는 키 입력과 복호화를 담당하며, uv나 인터넷은 쓰지 않는다.

계정은 두 가지를 발행 때 지정한다.

- **관리자 계정(필수):** 직원 계정 발급용이다.
- **개발자 계정(선택):** AI 공급자 키 등록 화면은 developer 역할만 쓸 수 있다 ([api.py:152](../../backend/app/api.py#L152)). 관리자 화면에서는 developer 계정을 만들 수 없다 ([api.py:276](../../backend/app/api.py#L276)). 지금은 S15 설치 스크립트가 두 계정을 모두 만들었지만, 새 흐름에서 관리자만 만들면 키를 등록할 방법이 없다. 그래서 발행 때 함께 지정할 수 있게 한다.

키는 DPAPI 때문에 사용자 PC의 같은 Windows 사용자로 화면에서 등록한다. 키를 미리 넣지 않는다는 원칙은 그대로다.

## 발행 패키지 구조

```
K-DOG-<고객ID>-v<버전>-<commit7>.zip
  Install.cmd                 ← 사용자가 더블클릭 (ASCII 전용)
  설치안내.txt                 ← 한 쪽짜리 한국어 안내
  installer\kdog_install.py   ← 평문 설치 프로그램 (저장소의 scripts/windows/kdog_install.py)
  runtime\python\  runtime\ffmpeg\   ← D01과 동일, 공개 소프트웨어라 암호화하지 않음 (FFmpeg 소스 묶음 포함)
  오픈소스고지.txt              ← D01과 동일, 암호화하지 않음
  payload.kdog                ← 헤더 + AES-256-GCM(제품 ZIP)
```

`payload.kdog`의 제품 ZIP에는 다음이 들어간다.

- D01 패키지에서 `runtime/`과 `오픈소스고지.txt`를 뺀 전부: `Start.cmd`, `release.json`, `backend/app`, `resources`, `frontend/dist`, `docs`
- `provision.json`: 고객 ID, 계정별 아이디·역할·기존 `password_hash` 형식 해시, 발행 시각

## 암호화 형식

| 항목 | 값 |
| --- | --- |
| 발행 키 | 무작위 125비트, Crockford Base32 25자, 표시 `KDOG-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`. 입력 처리 순서: 앞의 `KDOG` 접두어(있으면) 제거 → 대소문자·하이픈·공백 무시 → O→0, I/L→1 정규화 → 정확히 25자인지 확인 |
| 키 유도 | `cryptography` HKDF-SHA256 (무작위 salt 16바이트, 출력 32바이트). 키 자체가 125비트 무작위 값이라 느린 KDF가 필요 없다. 매개변수는 코드에 고정하고 헤더 값을 신뢰하지 않는다 |
| 암호화 | `cryptography` AESGCM, 무작위 nonce 12바이트 |
| 파일 배치 | `KDOGPKG1`(8바이트) + 헤더 길이(4바이트, big-endian) + 헤더 JSON 바이트 + 암호문. 헤더는 `{"format": "kdog-issued-1", "customer", "version", "commit", "salt", "nonce"}`. AAD는 **파일에 저장된 헤더 바이트 그대로**이며, JSON을 다시 직렬화해 쓰지 않는다 |

봉인/개봉 함수는 `scripts/windows/kdog_install.py` 한 곳에만 두고, 발행 스크립트가 이 파일을 불러 쓴다. 형식 구현을 두 군데 두지 않는다.

## 설치 흐름 (`kdog_install.py`)

1. `Install.cmd`는 `runtime\python\python.exe`가 없으면 "Extract all files from the ZIP first" 안내 후 종료한다. ZIP 안에서 바로 더블클릭한 경우에 해당한다.
2. 발행 키를 입력받는다. 화면에 보이게 입력하여 오타를 확인할 수 있게 한다. 틀리면 "키가 맞지 않습니다"를 출력하고 다시 묻는다. 빈 입력은 설치 취소다. 키 확인(복호화 성공) 전에는 디스크에 아무것도 쓰지 않는다.
3. `%LOCALAPPDATA%\Programs\K-DOG\`에 남아 있는 이전의 `.tmp-*` 폴더를 지운다. 새 임시 폴더에 제품 ZIP을 풀되 `provision.json`은 제외하고 메모리에만 둔다. 패키지의 `runtime\`을 복사한 뒤 `launcher --check`(D01의 전체 해시 검사)를 실행한다.
4. 검사가 통과하면 임시 폴더를 `<버전>-<commit7>` 폴더로 이름을 바꾼다. 백신이나 색인기가 파일을 잡고 있으면 실패할 수 있으므로 몇 초 동안 간격을 두고 재시도한다.
   - 같은 버전 폴더가 이미 있으면 복사를 건너뛰고 `--check`만 다시 실행한다.
   - 검사가 실패하면 폴더 경로와 함께 "폴더를 지운 뒤 다시 설치하세요"를 안내한다.
   - 이름 바꾸기 전에 중단되었다면 다시 실행할 때 처음부터 설치한다. 이름 바꾸기가 끝난 뒤에 중단되었다면 다시 실행할 때 계정·바로가기 단계만 수행한다.
5. 설치된 Python으로 `app.manage provision-accounts`를 실행하고 메모리의 `provision.json` 바이트를 표준입력으로 넘긴다. 자료 경로는 기존 규칙(`KDOG_DATA_DIR` 또는 `%LOCALAPPDATA%\K-DOG\data`)을 따른다. 계정마다 다음과 같이 처리한다.
   - 아이디가 없으면 지정 역할과 해시로 만든다.
   - 같은 아이디가 **같은 역할의 활성 계정**이면 바꾸지 않고 "기존 계정과 기존 비밀번호가 유지됩니다"를 출력한다.
   - 역할이 다르거나 비활성 계정이면 아무것도 바꾸지 않고 실패로 안내한다.
6. 바탕화면에 `K-DOG.lnk`를 만든다. 대상은 새 버전 폴더의 `Start.cmd`, 작업 폴더는 설치 폴더다.
   - PowerShell `WScript.Shell`을 사용한다. 바탕화면 경로는 `[Environment]::GetFolderPath('Desktop')`로 구하여 OneDrive로 옮겨진 바탕화면에도 대응한다. 이미 있으면 새 버전으로 덮어쓴다.
   - 회사 PC 정책(PowerShell 제한 언어 모드 등)으로 실패해도 설치는 성공으로 끝낸다. 이때는 `Start.cmd`의 전체 경로를 출력한다.
7. 완료 안내: 계정 아이디, 새 계정이면 "비밀번호는 별도로 전달받은 것을 사용하세요", "바탕화면 K-DOG 아이콘으로 실행하세요", "이미 실행 중이면 창을 닫고 다시 실행하세요".

기존 `create-user`와 같이 DB에 바로 쓰므로 앱이 실행 중이어도 설치할 수 있다 ([manage.py:162](../../backend/app/manage.py#L162)). 실행 중인 이전 버전은 창을 닫고 아이콘으로 다시 실행하면 새 버전으로 바뀐다. 이전 버전 폴더는 지우지 않으며 정리 방법은 운영 안내에 적는다.

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `scripts/windows/kdog_install.py` | 신설 | 키 정규화, 봉인/개봉, 설치 흐름 1~7. 발행 패키지에는 `installer\kdog_install.py`로 들어간다. 검증용 `--install-root`·`--shortcut-dir` 인자 (기본값은 실제 경로) |
| `scripts/windows/Install.cmd` | 신설 | ASCII 전용. 런타임 존재 확인, `PYTHONPATH`·`PYTHONHOME` 비우기, 설치 프로그램 실행, `pause` |
| `scripts/windows/설치안내.txt` | 신설 | ① 받은 ZIP의 SHA-256을 키와 함께 받은 값과 비교(방법 한 줄) ② 압축 풀기 (필요하면 "차단 해제") ③ Install.cmd 실행 ④ 키 입력 ⑤ 바탕화면 아이콘으로 실행 ⑥ 창을 닫으면 종료 ⑦ 문의처: 벨루가 veluga.app@veluga.io |
| `scripts/issue_release.py` | 신설 | `issue_release.py <평문 ZIP> --customer <ID> --admin <아이디> [--developer <아이디>]`. 고객 ID는 `[A-Za-z0-9-]{1,32}`. 계정마다 `getpass`로 두 번 입력받고 12~256자를 확인한다. 키 생성 → 봉인 → `releases/issued/<고객ID>/`에 ZIP·`.sha256`·발행 기록 저장. 키는 콘솔에 한 번 출력한다. "이미 설치된 PC에서는 같은 아이디의 기존 비밀번호가 유지된다"는 경고도 함께 출력한다 |
| `backend/app/manage.py`, `backend/app/auth.py` | 수정 | `provision-accounts` 하위 명령: 표준입력 JSON을 검증한 뒤 설치 흐름 5의 규칙대로 admin/developer 계정 생성. 감사 기록 `user.provisioned`(고객 ID 포함) |
| `backend/pyproject.toml`, `backend/uv.lock` | 수정 | `cryptography==50.0.2` 추가 (구현 시 최신 재확인). 관련 없는 의존성은 올리지 않는다 |
| `scripts/verify_release.py` | 수정 | 발행 패키지 검증 추가 (아래) |
| `backend/tests/test_issued_release.py` | 신설 | 봉인/개봉 왕복, 틀린 키·헤더 변조·본문 변조 거절, 키 정규화(`KDOG` 접두어 포함), `provision-accounts`의 신규/기존 동일 역할/역할 불일치/비활성/잘못된 입력 |
| `docs/PILOT_OPERATIONS.md`, `README.md`, `docs/DEVELOPMENT.md` | 갱신 | 사용자 설치 절차, 발행 명령, 키·SHA-256 전달 규칙, 비밀번호 분실 시 `reset-password`, AI 키 등록(개발자 계정, 사용자 PC의 같은 Windows 사용자), 이전 버전 폴더 정리, 보안 경계(상위 §6) |

## 검증과 완료 조건

`verify_release.py`의 발행 검증은 임시 폴더에서 합성 고객(`VERIFY`)·무작위 비밀번호·admin과 developer 계정으로 발행한 뒤 다음을 확인한다.

- 발행 ZIP 이름 목록과 바이트에 제품 파일 평문(`backend/app/` 경로, 알려진 소스 문자열, `provision.json`)이 없다.
- 틀린 키에서는 설치 폴더·임시 폴더·계정·바로가기가 만들어지지 않는다. 헤더나 본문을 1바이트 바꾼 패키지는 거절된다.
- PATH에 uv·Python·FFmpeg가 없는 상태에서 올바른 키로 설치된다. 설치 폴더에 `provision.json`이 없다.
- 바로가기 대상이 새 버전의 `Start.cmd`이고, 그 경로로 실행하여 발행 관리자로 로그인·접수·재시작이 된다. 발행 개발자 계정으로 로그인하면 키 설정 화면 API(`/api/developer/settings`)에 접근할 수 있다.
- 같은 패키지를 다시 설치하면 자료와 계정이 그대로 유지되고 성공으로 끝난다.

그 밖의 완료 조건:

- backend 전체 시험, frontend build·전체 e2e, `git diff --check`가 통과한다.
- 현재 Windows에서 실제 바탕화면 경로로 설치 → 아이콘 실행 → 로그인을 한 번 수행하고 기록한다. 기록 후 시험용 바로가기·설치 폴더는 정리한다.
- 발행 키·비밀번호·발행 기록이 git 추적 대상이 아님을 `git status`로 확인한다.
- 고객 발송 전 조건: 상위 계획 Q01(FFmpeg 재배포 확인)·Q02(보안 정책 차단)·Q05(특허) 결과를 기록한다. 깨끗한 OS·다른 PC 설치는 E10 후속으로 남긴다.

## 위험과 대응

| 위험 | 대응 |
| --- | --- |
| 다운로드한 ZIP의 인터넷 표시(MOTW)로 `.cmd` 실행 시 보안 경고 | 설치안내에 "열기/실행" 또는 ZIP 속성의 "차단 해제" 방법을 그림 없이 한 줄로 안내. 실제 동작은 E10에서 확인 |
| 평문 영역(`Install.cmd`, 설치 프로그램, `runtime`) 변조 | 암호화로는 막을 수 없다 (상위 §6). 키와 같은 경로로 받은 SHA-256과 ZIP을 비교한 뒤 설치하도록 안내 |
| 키 입력 오타 | 보이는 입력, 접두어 제거와 혼동 문자 정규화, 무제한 재입력 |
| 설치 도중 중단, 이름 바꾸기 실패 | 임시 폴더 → 재시도하는 이름 바꾸기. 남은 임시 폴더는 다음 설치 때 정리 |
| 키와 ZIP을 함께 전달 | 발행 스크립트 출력과 운영 안내에 "다른 경로로 전달" 경고 |

## 구현 및 검증 기록

- [x] 구현·변경 파일 및 commit/PR 기록
- [x] `cryptography` 최신·선택 버전·확인일·근거 기록
- [x] 발행 검증·실제 바탕화면 설치 결과와 발행 패키지 크기·SHA-256 기록 (키는 기록하지 않음)
- [x] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [x] Q01·Q02·Q05 확인 상태와 E10 후속 인계 기록

### 구현 (2026-10-05)

브랜치 `veluga/d03-issued-install`. 계획의 파일별 변경을 모두 반영했다 (`scripts/windows/kdog_install.py`·`Install.cmd`·`설치안내.txt`, `scripts/issue_release.py`, `backend/app/auth.py`·`manage.py`의 `provision-accounts`, `backend/pyproject.toml`·`uv.lock`, `scripts/verify_release.py`, `backend/tests/test_issued_release.py`, `docs/PILOT_OPERATIONS.md`·`README.md`·`docs/DEVELOPMENT.md`). 계획과 다르거나 구체화한 점:

- HKDF `info`는 `K-DOG issued package v1`로 코드에 고정했다. 헤더는 `sort_keys` JSON이며 AAD는 저장된 헤더 바이트 그대로다.
- 키 입력은 `KDOG`·`K-DOG`·`KD0G` 접두어를 길이(29자)로만 인식해 떼므로 키 글자를 잘못 지우지 않는다. NFKC 정규화로 전각 문자도 받는다. 형식 오류 안내에 한/영 확인을 덧붙였다.
- 설치 프로그램은 패키지의 `runtime/` 전체가 아니라 봉인된 `release.json`에 있는 공개 파일만 복사한다. 압축을 푼 폴더에 나중에 파일을 넣어도 설치되지 않는다.
- 헤더의 `version`·`commit`(설치 폴더 이름)은 형식(`[0-9A-Za-z.+-]`, 40자리 16진수)을 확인한다.
- 바로가기는 PowerShell 오류 시 즉시 중단하고 만든 링크의 대상을 다시 읽어 비교한다. 기존 아이콘이 잠겨 갱신되지 않으면 성공으로 보고하지 않고 `Start.cmd` 경로를 안내한다. 대상 비교는 8.3 짧은 경로를 펼쳐서 한다. 지정한 바로가기 폴더가 없으면 만든다.
- `issue_release`는 평문 ZIP 전체를 `release.json`과 대조하고, 발행 설치를 지원하지 않는 평문 ZIP(`cryptography`나 `provision-accounts` 없음)을 거절한다. 같은 이름의 발행 ZIP을 덮어쓰지 않고 `.part`로 쓴 뒤 이름을 바꾼다. 발행 기록에는 설치 프로그램 SHA-256을 남기고 키·비밀번호·해시는 남기지 않는다.
- 발행할 때마다 새 키를 만든다 (Q03 기본안).

### 버전 확인 (2026-10-05)

| 대상 | 최신 확인 | 선택 | 근거 |
| --- | --- | --- | --- |
| cryptography | 50.0.2 (2026-09-30) | 50.0.2 | [PyPI](https://pypi.org/project/cryptography/). `cp311-abi3-win_amd64` wheel이 3.14에서 동작. API: [AEAD](https://cryptography.io/en/latest/hazmat/primitives/aead/)(`AESGCM.encrypt/decrypt(nonce, data, associated_data)`, 실패 시 `InvalidTag`), [HKDF](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/)(`HKDF(algorithm, length, salt, info).derive`). 설치 후 직접 왕복·변조 거절 확인 |
| cffi (cryptography 의존) | 2.1.1 | 2.1.1 | `cp314-cp314-win_amd64` wheel 있음. `uv lock` 결과 추가는 cffi 2.1.1·cryptography 50.0.2·pycparser 3.0뿐이고 기존 고정 버전은 바뀌지 않았다 |

### 시험

- `tests.test_issued_release` 11개 OK: 키 생성·표시·입력 정규화(접두어·소문자·공백·전각·혼동 문자), 봉인/개봉 왕복, 틀린 키·헤더 변조·본문 변조 거절, 손상·비정상 헤더(크기·형식·경로 문자열) 거절, `provision-accounts` 신규/기존 동일 역할 유지/역할 불일치·비활성 시 무변경/잘못된 입력/CLI 종료 코드, 발행 결과 구성·비밀 미기록·발행마다 새 키·덮어쓰기 거절·지원하지 않는 평문 ZIP 거절, 취소·틀린 키 시 무기록, 설치 파일 복사(`provision.json` 제외·목록 밖 파일 제외·검사 실패 시 임시 폴더 삭제·기존 버전 재확인·경로 탈출 거절), 바로가기 실패 대체.
- backend 전체: **599개 OK, skip 2** (역사 원본 부재로 정상 skip). frontend build, 전체 e2e **45개 통과**, `git diff --check` 통과.
- 평문 패키지 `k-dog-v0.3.0-s1-windows-x64-928c066.zip`: 1,362개 파일, **74,766,790 B**, SHA-256 `1c158d138a5ddbdeef1065e1e7aa9c0c25001e5f3afbd03e1a5e2b49d7f51c2a` (cryptography 추가로 D01보다 약 4MB 증가).
- `verify_release.py` 통과 (평문 + 발행): 합성 고객 `VERIFY`·무작위 비밀번호·admin/developer로 발행 → 발행 ZIP 이름 목록과 각 항목 내용에 제품 파일·소스 문자열·`provision.json`·비밀번호 해시 없음 → PATH에 uv·Python·FFmpeg가 없는 상태에서 틀린 키, 헤더 1바이트 변경, 본문 1바이트 변경 모두 설치 폴더·임시 폴더·자료·바로가기를 만들지 않음 → 올바른 키로 설치, 설치 폴더에 `provision.json` 없음, 바로가기 대상이 새 버전 `Start.cmd` → 그 `Start.cmd`로 실행해 발행 관리자 로그인·접수, 발행 개발자로 `/api/developer/settings` 접근 → 같은 패키지 재설치 시 "기존 비밀번호가 유지", 재시작 후 자료·로그인 유지.

### 실제 바탕화면 설치 (현재 Windows 11, 2026-10-05)

위 평문 패키지로 합성 고객 `DESKTOP-CHECK` 발행 패키지(74,772,117 B, SHA-256 `e9aafbca1af4440fb02ae001c77804d480eacc39c41ef1cd0e98d16040aa4a95`)를 만들어 기본 경로 그대로 설치했다. 사용자 자료를 건드리지 않도록 자료 폴더만 임시 `KDOG_DATA_DIR`로 지정했다.

| 항목 | 결과 |
| --- | --- |
| 설치 | 키를 소문자·공백 구분으로 입력해도 통과. 종료 코드 0. `%LOCALAPPDATA%\Programs\K-DOG\0.3.0-928c066\`에 설치, 관리자 계정 생성 |
| 바로가기 | OneDrive로 옮겨진 한글 바탕화면(`…\OneDrive - MSFT\바탕 화면\K-DOG.lnk`)에 생성, 대상은 새 버전 `Start.cmd` |
| 아이콘 실행 | 셸로 바로가기를 열어(더블클릭과 같은 경로) K-DOG가 8000 포트에서 시작, 브라우저 열기 1회(`BROWSER` 기록) |
| 로그인 | 발행 관리자 `desk-admin`(admin) 로그인 성공 |
| 정리 | K-DOG 프로세스 종료 확인 후 바로가기와 설치 폴더 삭제 (원래 없던 폴더) |

이 PC는 기본 터미널이 "Windows에서 결정"(Windows Terminal)이라 아이콘 실행 창이 Windows Terminal에 열린다. 창 X 닫기 동작은 D02에서 conhost 창으로 확인했다. 깨끗한 OS·다른 PC 설치, SmartScreen·인터넷 표시(MOTW) 경고 동작, 마우스 직접 조작은 E10 후속이다.

### cold review와 조치

독립 cold review 결과 P1 없음, P2 3건, P3 9건. 암호 구성(새 salt·nonce, 저장 헤더 AAD, 길이 경계, 키 엔트로피)과 `provision.json` 메모리 전달, 계정 처리 원자성은 문제없다고 확인되었다.

| 등급 | 발견 | 조치 |
| --- | --- | --- |
| P2 | 바로가기 저장이 실패해도 이전 버전 아이콘이 있으면 성공으로 보고 (재현됨) | 수용: 오류 시 중단, 링크 대상 재확인 |
| P2 | 발행 시 평문 ZIP이 발행 설치를 지원하는지 확인하지 않음 | 수용: `cryptography`·`provision-accounts` 확인, 설치 프로그램 해시 기록 |
| P2 | 시간 초과·잘못된 ZIP·Python 차단·DB 잠김이 영문 traceback으로 보임 | 수용: 한국어 안내, `manage`의 `Store`·`sqlite3` 오류 처리 |
| P3 | `K-DOG-`·`KD0G` 접두어, 전각 입력 거절 | 수용 |
| P3 | 압축 푼 폴더에 추가된 파일이 함께 설치됨 | 수용: 봉인된 목록의 공개 파일만 복사 |
| P3 | 헤더 version/commit 형식 미검증 | 수용 |
| P3 | 두 설치를 동시에 실행하면 서로의 임시 폴더를 지울 수 있음 | 보류: 같은 PC에서 동시에 두 번 설치하는 경우만 해당. 실패한 쪽은 다시 실행하면 된다 |
| P3 | 같은 이름 재발행 시 원시 오류 | 수용: 안내 후 거절, `.part` 후 이름 변경 |
| P3 | 키 확인 후 진행 안내 없음 | 수용 |
| P3 | SHA-256 대소문자 혼동 | 수용: 설치안내에 명시 |
| P3 | 설치 단계 단위 시험 부족 | 수용: 설치 파일·바로가기·헤더 형식 시험 추가 |
| P3 | 실행 기록 미작성 | 수용: 이 기록 |

### Q01·Q02·Q05 상태와 E10 인계

- Q01 (FFmpeg GPL 재배포): 결정 K07·K08대로 대응 소스·라이선스·한국어 고지를 동봉하고 발행 ZIP에서도 암호화하지 않는다. 개발자 점검은 D01 기록에 있다. **확인 담당자(벨루가)의 동봉물 점검 결과는 아직 기록되지 않았으며 고객 발송 전에 남긴다.**
- Q02 (보안 정책 차단): 해당 없음(K08). 서명하지 않은 `.cmd`·`ffmpeg.exe`의 SmartScreen·MOTW 경고는 설치안내의 "차단 해제"·"추가 정보 → 실행"으로 대응하며 실제 동작은 E10에서 확인한다.
- Q05 (H.264/AAC 특허): 비상용 학교 이벤트(K08)로 추가 조치 없이 진행한다. 상용 배포로 바뀌면 다시 검토한다.
- E10 후속: 깨끗한 Windows·다른 PC에서 발행 ZIP 다운로드(MOTW) → 압축 풀기 → `Install.cmd` → 키 입력 → 아이콘 실행 → 로그인 → 창 닫기, 그리고 업데이트 설치 후 이전 버전 폴더 정리를 실측한다.
- 발행 키·비밀번호·발행 기록은 `releases/`(git 무시 대상) 밖으로 커밋하지 않았다 (`git status` 확인).
