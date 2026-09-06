# K-DOG 동의 관리 제거 기록

작성일: 2026-09-06

범위: M1~M5 동의 관리 제거, 자료 삭제 유지, 기존 SQLite/백업 호환

## 운영 계약

참가 신청은 별도 이메일 등 외부 절차에서 사전에 처리한다. 앱은 동의 상태·문구 버전·기록 시각·철회를 관리하지 않는다. 외부 신청 확인 체크박스나 동의 기본값도 추가하지 않는다. 직원은 참가자를 등록한 뒤 바로 영상을 올리고 분석·결과 조회·내보내기를 수행한다. 기존 직원 권한·입력 검증·AI 설정·호출 한도는 그대로 적용한다.

상세의 **자료 관리 → 삭제 요청 접수**는 운영자·운영 관리자에게 제공한다. 삭제 요청됨을 선택하고 **삭제 요청 저장**을 누르면 목록·파일 접근을 차단하고 진행 분석의 점유를 무효화한다. 물리 폐기는 기존 관리 명령을 사용하며 복원 시 삭제 목록을 재적용한다.

## 변경 범위

- 프런트엔드: 동의 폼·타입·시각 변환·업로드/재생/분석 비활성화 조건·내보내기 안내 제거.
- API: `Consent`, `AccessEdit`, 참가자 응답의 `consent`, `PUT /api/cases/{case_id}/access` 제거. 삭제 전용 `POST /api/cases/{case_id}/deletion`은 `{ "expected_revision": 정수 }`만 받으며 운영자/관리자 권한과 현재 입력 버전을 확인한다.
- 삭제는 입력 변경이 아니므로 manifest를 재작성하거나 input_revision·display_run_id를 바꾸지 않는다. 기존 입력과 실행 추적 관계를 보존한다.
- 저장·작업: `require_consent`와 직접 동의 판정을 제거한다. `Store.case`의 삭제 차단, 작업 점유·중지 검사, 결과 채택 직전 재확인, 내보내기 스냅샷 검사와 원격 임시 파일 정리는 유지한다.
- 테스트: 동의 등록 준비 단계를 제거하고, 철회 경합 시나리오는 삭제 경합 검증으로 전환한다. 동의 없는 정상 실행·출력과 삭제 API 권한/입력 계약을 확인한다.
- 문서: PRD·S0·F-02·개발 안내를 갱신했다. M1~M4 구현 기록은 과거 시험 이력으로 보존하고 현재 계약 링크를 추가했다. 원본 Excel과 평가 규칙은 변경하지 않았다.

## 기존 DB와 백업

SQLite user_version 3. 신규 DB에는 동의 컬럼이 없다. 기존 DB를 여는 `Store` 초기화에서 `cases.consent_json`을 제거하고 과거 `access.state` 이력 JSON의 `consent` 키만 제거한다. 이력의 작성자·시각·대상·삭제 요청 값은 유지한다. 컬럼 제거·이력 정리·버전 변경은 하나의 쓰기 트랜잭션으로 실행하며 실패 시 롤백한다. 재실행해도 입력·결과를 재작성하지 않는다.

서버와 worker를 함께 종료한 뒤 프런트엔드를 빌드하고 새 코드로 재시작한다. 실제 운영 DB는 이번 개발 검증에서 열지 않았다. 기존 백업 원본은 수정하지 않으며 복원된 작업 사본이 같은 마이그레이션을 거친다. 구버전 앱과 신버전 앱을 같은 데이터 폴더에 동시에 실행하지 않는다.

과거 동의 미등록·철회 값은 더 이상 접근 차단 기준이 아니다. 삭제 요청되지 않은 저장 결과는 조회 가능하다. 중지된 run은 자동 재개하지 않고 이전 입력 버전·표시 포인터도 임의 복구하지 않는다. 삭제된 자료는 계속 차단한다. 기존 백업에 남아 있는 과거 값은 백업 보관·폐기 절차의 대상이며 이번 변경이 기존 백업의 물리 소거를 수행하는 것은 아니다.

## 의존성 확인

확인일: 2026-09-06. 새 의존성을 도입하지 않았고 manifest/lockfile을 유지했다. 공식 레지스트리 최신 안정 버전과 선택 버전이 모두 일치한다.

| 계열 | 최신 = 선택 버전 | 확인 출처 |
|---|---|---|
| API·모델 | FastAPI 0.141.1, Pydantic 2.13.5, Uvicorn 0.52.4 | [FastAPI](https://pypi.org/pypi/fastapi/json), [Pydantic](https://pypi.org/pypi/pydantic/json), [Uvicorn](https://pypi.org/pypi/uvicorn/json) |
| 파일·시험 | openpyxl 3.1.5, ReportLab 5.0.1, Pillow 12.3.0, HTTPX 0.28.1, pypdf 6.17.0 | [openpyxl](https://pypi.org/pypi/openpyxl/json), [ReportLab](https://pypi.org/pypi/reportlab/json), [Pillow](https://pypi.org/pypi/pillow/json), [HTTPX](https://pypi.org/pypi/httpx/json), [pypdf](https://pypi.org/pypi/pypdf/json) |
| UI | React/React DOM 19.2.8, 타입 19.2.18/19.2.7 | [React](https://registry.npmjs.org/react/latest), [React DOM](https://registry.npmjs.org/react-dom/latest), [React 타입](https://registry.npmjs.org/@types/react/latest), [DOM 타입](https://registry.npmjs.org/@types/react-dom/latest) |
| 빌드·브라우저 | TypeScript 7.0.2, Vite 8.2.2, Playwright 1.63.0 | [TypeScript](https://registry.npmjs.org/typescript/latest), [Vite](https://registry.npmjs.org/vite/latest), [Playwright](https://registry.npmjs.org/@playwright/test/latest) |

검증 환경은 Python 3.14.2 / SQLite 3.50.4 / Node.js 24.13.0이다. Python 3.14는 위 Python 패키지의 requires_python 범위에 포함된다. React DOM의 React ^19.2.8 및 DOM 타입의 React 타입 ^19.2.0 요구를 충족한다. Node.js 24는 Vite의 >=22.12.0, Playwright의 >=20, TypeScript의 >=16.20.0 조건을 충족한다. [FastAPI 변경 이력](https://fastapi.tiangolo.com/release-notes/), [Pydantic 변경 이력](https://docs.pydantic.dev/latest/changelog/), [모델 설정 API](https://docs.pydantic.dev/latest/api/config/), [React 상태 API](https://react.dev/reference/react/useState), [Playwright 변경 이력](https://playwright.dev/docs/release-notes)을 대조했다. 기존 API에서 동의 필드만 제거하며 프레임워크 업그레이드에 따른 변경은 없다. SQLite 컬럼 제거는 [공식 ALTER TABLE 계약](https://www.sqlite.org/lang_altertable.html)을 따른다.

## 검증과 cold review

실행 명령은 `backend/`에서 `uv run --locked python -X utf8 -m unittest discover -s tests -v`, `uv run --locked python -X utf8 -m app.import_catalogs --check`, `frontend/`에서 `npm run build`, `npm run test:e2e`다. 저장소 루트에서 `git diff --check`와 변경 문서 상대 링크 검사를 수행한다.

- 브라우저 8개 통과(34.4초). 동의 등록 없이 2대 카메라·설문·분석·점수·리포트·내보내기를 실행하고, 모바일 삭제 폼과 다른 세션의 삭제 후 근거/점수/리포트 숨김·다운로드 차단을 확인했다.
- production build, 행동 55항목·설문 30문항의 원본 카탈로그 대조 통과.
- [데스크톱 상세](images/consent-removal-desktop.png), [360px 상세](images/consent-removal-mobile.png)를 열어 동의 패널 제거와 자료 관리 배치를 확인했다. 합성 참가자만 사용했다.
- 최종 Python 전체 113개 통과(107.119초). cold review 보강 시험과 DB/백업 전환 시험을 포함한다.

Cold review는 최초 구현·시험 후 변경 diff와 인접 호출부를 다시 읽어 수행했다. 동의 차단의 잔존 여부, 삭제 접수 권한과 동시 업로드, 공통 접근 검사 호출부, 작업 점유 무효화·늦은 결과 채택, 삭제 중 내보내기, 기존 DB·백업 전환을 대조했다. 새 동의 기능의 잔존이나 삭제 차단을 해제한 변경은 발견하지 않았다. 삭제 시 입력 revision·manifest 참조/해시·display_run_id가 유지되는지와 삭제 후 새 export 접수 차단을 추가 검증하고, 동의 준비 코드 제거로 사용되지 않게 된 테스트 변수를 정리했다.

변경 문서 상대 링크 52개와 `git diff --check`도 통과했다.

전환 시험은 미등록·거절·허용 값의 제거, 기존 삭제 상태·이력의 삭제 요청 값 보존, 마이그레이션 실패 후 컬럼·버전 롤백과 재실행, 옛 백업의 실행/단계/파일 해시 동일성·저장 점수 조회·중지 상태 유지·기존 출력 다운로드를 확인한다. 별도 테스트는 삭제 이후 옛 백업을 복원해도 삭제 목록이 적용되는 것을 확인한다.

MCP 그래프는 fast/full 갱신 후에도 현재 구현 파일 상당수를 누락했으므로 부족한 코드 발견·분석은 파일 검색으로 보완했다. 실제 참가자 데이터·운영 DB·공급자 실 API는 사용하지 않았다. HTTPX TestClient 사용에 대한 기존 Starlette 폐기 예정 경고는 남아 있으며 이번 기능 제거 범위에서 의존성을 교체하지 않았다.
