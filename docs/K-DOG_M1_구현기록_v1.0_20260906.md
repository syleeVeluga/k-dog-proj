# K-DOG M1 구현 기록 및 운영 안내

버전: v1.0 · 작성일: 2026-09-06
기준: [구현 지시서 §10 M1·§11 T02/T08](K-DOG_바이브코딩_구현지시서_v1.0_20260905.md), [문서 검수 F-01–F-05](K-DOG_문서검수_v1.0_20260905.md)

## 완료 범위

React·TypeScript 화면과 FastAPI·SQLite 입력 앱을 구현했다. 인증, 운영자/교수/운영 관리자/개발자 분리, 직원 계정 관리, 참가자 등록·검색·상세, 수동 설문 입력, 표준 CSV/XLSX 미리보기·저장, 촬영 세션·동선·카메라 연결, 영상 관리 사본 등록·제공을 지원한다. 앱 서버를 종료·재실행한 뒤 1명·2영상·설문을 다시 조회하는 것을 M1 완료 기준으로 검증한다.

M0 원본 항목집·미정 규칙은 수정하지 않았다. 참가자 입력 단계이며 분석 실행·결과 내보내기 기능은 아직 없다. 원본 가로 Excel의 임의 열/순번 매핑 UI는 후속 작업이다. M1은 자체 표준 입력 양식을 제공한다.

## 실행·계정·저장 위치

처음 설치·빌드·실행 명령은 [개발 실행 안내](DEVELOPMENT.md)를 따른다. 비밀번호는 12~256자이며 CLI의 숨김 프롬프트로 입력한다. 소스·명령 인자·브라우저 저장소에 비밀번호를 넣지 않는다.

```powershell
# backend/에서 실행. --data-dir은 하위 명령 앞에 둔다.
uv run --locked python -X utf8 -m app.manage --data-dir D:/K-DOG-data create-user manager --role admin
uv run --locked python -X utf8 -m app.manage --data-dir D:/K-DOG-data create-user developer --role developer
uv run --locked python -X utf8 -m app.manage --data-dir D:/K-DOG-data serve
# 계정 분실 시 동일 데이터 폴더를 지정해 로컬에서 비밀번호를 재설정한다.
uv run --locked python -X utf8 -m app.manage --data-dir D:/K-DOG-data reset-password manager
```

예시 경로 대신 기본 `%LOCALAPPDATA%/K-DOG/data`를 쓰려면 `--data-dir`을 생략한다. `KDOG_DATA_DIR` 환경 변수도 지원한다. **계정 생성·서버·재설정 명령은 같은 데이터 폴더를 사용해야 한다.** 프런트엔드 새 빌드 후 서버를 재시작한다.

| 역할 | M1 권한 |
|---|---|
| 운영자 | 참가자·설문·세션·영상 입력, 동의·삭제 요청 기록, 자료 조회 |
| 교수/검토자 | 참가자·설문·영상 조회. 입력 자료 수정은 운영자에게 요청 |
| 운영 관리자 | 운영자 기능과 직원 계정 생성·역할 변경·비활성화 |
| 개발자 | 별도 로컬 발급, 개발자 API 인증 확인. 참가자 자료 조회 불가 |

운영 관리자의 개발자 계정 발급·수정·자기 권한 변경은 서버가 거절한다. 교수의 점수 검토·수정 권한은 해당 기능을 구현하는 후속 단계에서 적용한다. 개발자 공급자 설정도 후속 단계다.

비밀번호는 scrypt 해시로 저장한다. 로그인 쿠키는 HttpOnly/SameSite=Strict, DB에는 토큰 SHA-256만 저장한다. 사용자당 활성 세션 1개·8시간 만료이며 재로그인·권한 변경·비활성화·비밀번호 재설정은 이전 세션을 무효화한다. 로그인 5회 연속 실패 후 60초 동안 잠근다. 검증 오류·이력에는 비밀번호를 기록하지 않는다.

기본 서버는 loopback HTTP다. 내부망은 TLS 프록시를 구성한 뒤 `--host`와 HTTPS `--public-origin`을 명시해야 한다. HTTPS origin은 Secure 쿠키를 사용하며 프록시는 원래 Host를 유지해야 한다. 허용 Host·변경 요청 Origin·커스텀 요청 헤더를 검사한다. TLS 프록시·인증서 구축 자체는 이번 단계에 포함하지 않는다.

## 자료 입력

1. 참가자 ID·행사 ID·반려견 이름을 등록한다. ID는 영문·숫자·`_`·`-`의 텍스트 값이며 앞자리 0을 보존한다. 동일 행사+참가자 ID는 충돌로 거절하고 이름으로 자동 연결하지 않는다.
2. 참가자 상세에서 실제 받은 동의의 문구 버전·기록 시각·영상 분석/외부 AI/결과 제공 상태를 기록한다. 브라우저 로컬 시각은 시간대가 있는 UTC로 저장한다.
3. 현재 촬영 세션의 동시/순차 여부와 동선 메모를 입력하고 카메라 ID를 확인해 영상을 선택한다. 한 번에 선택한 파일은 모두 해당 카메라에 연결된다. 다른 카메라는 따로 등록한다.
4. 설문 q01~q30을 수동 입력하거나 표준 파일을 가져온다. 1~5 또는 미응답만 허용한다. q23 원응답도 그대로 보존하고 계산하지 않는다.
5. 재촬영은 새 세션을 만들고 설문·영상을 따로 연결한다. 선택 세션을 전환해 이전 자료를 조회할 수 있으며 자동 합치지 않는다.

표준 CSV/XLSX는 화면에서 내려받는다. 설문 `survey_version` 값은 가져오기 화면에 표시한다. 열 순서 변경은 허용하지만 열 이름·문항 ID는 고정이다. Excel 숫자 ID는 자동 변환하지 않으며 수식 응답도 실행하지 않는다. UTF-8 CSV와 텍스트 ID를 사용한다.

가져오기는 오류 행과 정상 행을 분리해 참가자 연결·원응답을 미리 보여준다. 정상 행 저장은 한 트랜잭션이며 충돌 시 전부 롤백한다. 미리보기 이후 revision이 변경되면 다시 검증한다. 같은 설문 재저장은 새 revision을 만들지 않는다. 가져오기 기술 제한은 파일 8 MiB·10,000행, XLSX 압축 해제 크기 32 MiB이며 참가자/영상의 운영 상한이 아니다. 20명 초과 입력도 허용한다.

영상은 저장소 밖 관리 위치로 스트리밍 복사·fsync·SHA-256을 완료한 뒤 등록한다. 원본 파일명은 표시 메타데이터일 뿐 저장 경로로 사용하지 않는다. 원래 SD카드/파일이 없어도 관리 사본을 조회한다. 같은 세션의 동일 해시는 중복 거절한다. 업로드 전과 채택 직전에 현재 동의·삭제 상태를 확인하며 장시간 업로드 후에는 로그인·역할도 다시 검사한다.

확장자와 빈 파일을 검사하지만 실제 디코딩·길이·오디오 검사는 M2 대상이다. 등록 파일은 `pending_probe`로 표시하며 RunInput의 검증된 VideoReference라고 취급하지 않는다. 파일 제공 직전에 크기·SHA-256과 현재 동의를 확인한다. 큰 영상의 해시 검사 비용은 M2에서 실제 파일로 측정할 필요가 있다.

삭제 요청은 목록·자료 제공 차단과 이력 기록까지 구현했다. 이미 시작된 전송의 취소·회수는 보장하지 않는다. 물리 삭제·백업 삭제/복원은 보관 정책과 M5 작업이 필요하다. 서버 강제 종료·DB 롤백으로 남은 미참조 입력/영상 파일은 API로 노출하지 않는다. 자동 고아 파일 정리도 M5 대상이다.

## 저장 계약과 검수 반영

SQLite는 `users`, `cases`, `runs`, `steps`, `changes` 5개 테이블만 사용한다. WAL·외래키·고유 제약·짧은 쓰기 트랜잭션을 적용한다. `cases`는 현재 입력 revision·선택 session·명시적 display run·manifest 경로/해시를 가진다. 참가자 자료 수정은 낙관적 revision 검사 후 새 불변 JSON을 쓰고 DB 참조를 바꾼다. 감사 이력에는 작업자·시각·대상·revision을 기록한다.

| 검수 | M1 반영 | 후속 검증 |
|---|---|---|
| F-01 | 불변 입력 파일, runs/steps 시도·토큰·만료·고유 출력 참조 필드, run 입력/설정 불변 트리거 | worker의 점유 조건부 결과 채택과 늦은 A/B 경합 시험은 M2/M5 |
| F-02 | 현재 동의·삭제 상태를 입력 파일과 분리. 업로드/채택/파일 제공 재확인, 철회·삭제 차단 | 외부 AI 요청·재시도·내보내기·백업 복원 시 재적용은 해당 단계 |
| F-03 | run의 reuse manifest 필드 예약. M0 근거 검증을 완화하지 않음 | 관련 해시·버전 기반 재사용 허용 목록은 M2/M3 |
| F-04 | 선택 session/input revision/display run 필드. 입력 변경 시 display run 해제, 완료시각 자동 선택 없음 | 실제 run 선택·이전 결과 표시·전체 export batch 고정은 M3/M4 |
| F-05 | q23 원응답 보존, 미정 계산 생성 없음 | 기존 rule_pending 계약 유지, 계산기는 M3 |

`intake-1.0` manifest는 미검사 영상을 보관하기 위한 별도 입력 계약이다. M2는 미디어 검사 후 M0 RunInput을 검증·직렬화해 `runs`에 넣어야 한다. M1은 작업을 접수하거나 worker를 실행하지 않는다. 스키마 버전은 SQLite `user_version=1`이며 다음 변경은 데이터 보존 migration이 필요하다.

## 개발 UI

```powershell
# 터미널 1: backend/ (Vite의 Host/Origin을 명시)
uv run --locked python -X utf8 -m app.manage serve --public-origin http://127.0.0.1:5173
# 터미널 2: frontend/
npm run dev
```

`http://127.0.0.1:5173`에 접속한다. Vite는 `/api`를 8000 포트로 프록시한다. 5173이 사용 중이면 포트를 정리하거나 프록시·origin을 일치시킨다. 운영은 [개발 안내](DEVELOPMENT.md)의 정적 빌드 제공 방식을 사용한다.

## 검증 결과

- Python `unittest`: **39개 통과**(M0 24개 + M1 15개). ID 앞자리 0/동명견/중복, 세션·revision 충돌, q01~q30 타입·범위·null, 권한·CSRF·Host, 로그인 무효화·해시·오류 마스킹, 동의 철회·삭제 차단, 업로드 중 동의 변경, 실패 파일 정리, 원본 제거 후 복원, 동일 크기 파일 변조, CSV/XLSX 행 오류·원자적 롤백·21명 입력을 검증했다.
- 실제 Uvicorn 자식 프로세스에서 1명·2영상·설문을 저장하고 프로세스를 종료·재시작한 뒤 응답과 영상 해시를 대조한다. 앱 인스턴스 재생성 시험도 별도로 유지한다.
- TypeScript 검사와 Vite production build 통과. npm 설치 감사에서 취약점 0건.
- Playwright Chromium 3개: 데스크톱 전체 등록/재조회/재촬영, 360px 표준 입력·상세 조작, 개발자/교수 역할 경계를 확인했다. 브라우저 콘솔의 런타임 오류와 모바일 문서 가로 넘침도 검사했다.
- 원본 55/30 항목집 `--check` 일치. 원본 Excel과 미정 규칙 변경 없음.
- codebase-memory의 프로젝트 확인·M0 심볼 탐색·snippet 조회를 사용했다. 새 파일 추가와 커밋 후 fast/full 재색인은 성공 응답을 반환했지만 그래프가 기존 190 nodes에 머물러 신규 create_app/Store 심볼 검색이 비었다. 신규 코드의 그래프 반영은 도구 측 미해결 제한이며 다음 작업에서 재확인한다. 검증은 실제 파일·실행 테스트·Git diff를 기준으로 했다.
- 모든 자료는 가상이다. 실제 영상 디코딩·AI 관찰 품질·외부 공급자 호출·운영 부하·내부망 TLS 배포는 미검증이다. M1을 실제 AI 검증 완료로 보고하지 않는다.

화면 검증 자료: [데스크톱 목록](screenshots/m1-desktop-list.png), [데스크톱 상세](screenshots/m1-desktop-detail.png), [360px 상세](screenshots/m1-mobile-detail.png).

## 의존성 확인 — 2026-09-06

설치 전 인터넷 검색·공식 문서·레지스트리 메타데이터로 최신 안정 버전과 호환성을 확인했다. 아래 최신 버전과 선택 버전은 동일하다. Python 3.14.2 / Node.js 24.13.0에서 실제 빌드·테스트했고 직접 버전과 전이 버전은 각각 manifest와 lockfile로 고정했다.

| 의존성 | 최신/선택 | 공식 출처·호환성 |
|---|---|---|
| FastAPI | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/), [릴리스](https://fastapi.tiangolo.com/release-notes/), [Security](https://fastapi.tiangolo.com/tutorial/security/). Python >=3.10, Pydantic >=2.9 |
| Uvicorn | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/), [릴리스](https://github.com/Kludex/uvicorn/releases). Python >=3.10, 기본 서버만 사용 |
| Pydantic | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [validator API](https://docs.pydantic.dev/latest/concepts/validators/). M0 버전 유지, Python >=3.9 |
| openpyxl | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/), [읽기 전용 API](https://openpyxl.pages.heptapod.net/openpyxl/optimized.html). Python >=3.8, M0 버전을 런타임 의존성으로 이동 |
| HTTPX (개발) | 0.28.1 | [PyPI](https://pypi.org/project/httpx/), [릴리스](https://github.com/encode/httpx/releases), [API](https://www.python-httpx.org/quickstart/). Python >=3.8 |
| React / React DOM | 19.2.8 | [React 버전](https://react.dev/versions), [React npm](https://www.npmjs.com/package/react), [React DOM npm](https://www.npmjs.com/package/react-dom). DOM peer React ^19.2.8, CSR만 사용 |
| Vite | 8.2.2 | [npm](https://www.npmjs.com/package/vite), [시작](https://vite.dev/guide/), [v8 migration](https://vite.dev/guide/migration). Node ^20.19 또는 >=22.12, 추가 React 변환 플러그인 없이 기본 JSX 사용 |
| TypeScript | 7.0.2 | [npm](https://www.npmjs.com/package/typescript), [릴리스](https://github.com/microsoft/TypeScript/releases). Node >=16.20, bundler 해석·react-jsx·strict 검사 |
| React 타입 | 19.2.18 / 19.2.7 | [@types/react](https://www.npmjs.com/package/@types/react), [@types/react-dom](https://www.npmjs.com/package/@types/react-dom). DOM 타입 peer @types/react ^19.2 |
| Playwright Test | 1.63.0 | [npm](https://www.npmjs.com/package/@playwright/test), [공식 설치/지원 환경](https://playwright.dev/docs/intro). Node >=20, Chromium 번들 설치 후 headless 시험 |

FastAPI의 전이 의존성 Starlette 1.6.0은 현재 TestClient의 HTTPX 사용에 deprecation 경고를 낸다. FastAPI가 명시한 HTTPX <1.0 호환 범위의 최신 안정 버전으로 테스트를 통과했다. 런타임에는 HTTPX를 사용하지 않으며 후속 TestClient 전환 시 다시 버전을 검증한다. SQLite·scrypt·CSV·파일 I/O는 Python 표준 라이브러리다.
