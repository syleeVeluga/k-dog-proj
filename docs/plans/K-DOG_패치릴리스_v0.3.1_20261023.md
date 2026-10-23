# K-DOG 패치 릴리스 v0.3.1

버전: v0.3.1 · 2026-10-23 · 기준: `main / 3aa69ed` · S1.1

## 범위

v0.3.0(`accab04`) 이후 병합한 [행사 신청 설문 가져오기](K-DOG_행사신청설문반영_v1.0_20261022.md), [독립 검토·수정](K-DOG_행사신청설문_ColdReview_v1.0_20261023.md)을 배포한다. 관련 요구사항은 R02·R07·R18, 인수 항목은 O01·T14·T25다. 백엔드·프런트엔드와 두 lockfile의 앱 버전을 0.3.1로 맞춘다. 평가 산식·저장 스키마·의존성 버전은 변경하지 않는다.

Windows 포터블·Windows 사용자 설치형·macOS 사용자 설치형을 같은 깨끗한 커밋에서 새로 빌드한다. 행사 어댑터 `backend/app/festival_forms.py`, 공유 연결 자산 `resources/mappings/forms-festival-20261022.json`, 새 frontend 번들을 기존 허용 목록으로 포함한다. 고객 원본·참가자 자료·키·운영 DB는 포함하지 않는다. 기존 S1 사용자는 [업데이트 안내](../PILOT_OPERATIONS.md#업데이트와-이전-버전-정리)에 따라 종료·백업 후 새 폴더에 설치하고 같은 자료 경로를 쓴다. 이번 패치를 위해 S1 점수를 초기화하지 않는다.

## 검증과 독립 검토

frontend TypeScript/Vite 빌드와 설문·파일 등록 브라우저 23개(26.3초)가 통과했다. 기존 500 kB 초과 번들 경고는 남는다. 버전 변경 후 `uv lock --check`가 앱 버전 불일치를 검출했으며 `uv lock`으로 루트 패키지 버전 한 줄만 갱신했다.

독립 검토자는 네 manifest/lockfile의 버전 일치·의존성 불변·공백 검사·세 배포 형식의 새 자산 포함 경로를 확인했다. 수정 필요 사항은 없으며 빌드 스크립트 변경 없이 세 형식을 모두 재생성한다.

최초 backend 명령에 존재하지 않는 `tests.test_launcher`를 넣어 모듈 로드 오류가 발생했다. 런처 시험은 `tests.test_packaging`에 있으므로 잘못된 모듈 인자를 제거해 다시 실행했다. 최종 명령 `uv run --locked python -X utf8 -m unittest tests.test_forms_import_v4 tests.test_forms_api_v4 tests.test_survey_v4 tests.test_packaging tests.test_issued_release tests.test_macos_distribution -v`는 108개 중 107개 통과·네이티브 macOS 키체인 1개 명시 skip(42.313초)이다. 설치 검증·최종 패키지 hash·게시 commit은 GitHub [v0.3.1 릴리스](https://github.com/syleeVeluga/k-dog-proj/releases/tag/v0.3.1)의 실제 게시 기록과 로컬 무시 경로 `releases/build-20261023/`, ZIP별 `.sha256`, receipt에 남긴다. 게시 전 모든 ZIP의 manifest·CRC·전 파일 hash·소스 일치 및 Windows 설치·재시작을 검증한다.

S1 원본 대조 명령은 로컬 전용 SRC02가 없어 실패했다. 원본 대조 통과로 표시하지 않는다. 전체 backend/E2E를 재실행한 것으로 표시하지 않는다. macOS 네이티브 키체인·실기기 설치, 깨끗한 OS·물리 PC 3대, 실제 공급자·영상·교수·현장 인수는 별도다. 운영 자료 등록이나 외부 AI 호출은 수행하지 않는다.

## 라이브러리 확인

2026-10-23 공식 PyPI/npm의 최신 안정판·선택판 메타데이터(런타임과 peer 제약)를 조회하고 공식 문서·릴리스 정보를 확인했다. 기존 고정 의존성으로 검증된 앱을 배포하며 관련 없는 최신판 이관은 별도 회귀가 필요하므로 수행하지 않는다. 상세 메타데이터는 로컬 `releases/build-20261023/dependency-verification.json`에 있다.

| 패키지 | 최신 안정판 | 선택판 | 공식 근거 |
| --- | --- | --- | --- |
| Pydantic | 2.14.1 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [변경 기록](https://docs.pydantic.dev/latest/changelog/) |
| FastAPI | 0.161.1 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/), [릴리스](https://fastapi.tiangolo.com/release-notes/) |
| uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/) |
| openpyxl | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/) |
| reportlab | 5.1.0 | 5.0.1 | [PyPI](https://pypi.org/project/reportlab/) |
| Pillow | 13.0.0 | 12.3.0 | [PyPI](https://pypi.org/project/pillow/) |
| cryptography | 50.0.2 | 50.0.2 | [PyPI](https://pypi.org/project/cryptography/), [변경 기록](https://cryptography.io/en/latest/changelog/) |
| httpx | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/) |
| pypdf | 6.21.2 | 6.19.0 | [PyPI](https://pypi.org/project/pypdf/) |
| uv | 0.13.5 | 0.12.13 | [PyPI](https://pypi.org/project/uv/), [CLI](https://docs.astral.sh/uv/reference/cli/) |
| React / React DOM | 19.3.1 | 19.2.8 | [React](https://registry.npmjs.org/react/latest), [React DOM](https://registry.npmjs.org/react-dom/latest), [판본 안내](https://react.dev/versions) |
| @types/react / @types/react-dom | 19.3.0 | 19.2.18 / 19.2.7 | [React 타입](https://registry.npmjs.org/@types%2freact/latest), [DOM 타입](https://registry.npmjs.org/@types%2freact-dom/latest) |
| Playwright | 1.64.1 | 1.63.0 | [npm](https://registry.npmjs.org/@playwright%2ftest/latest), [릴리스](https://playwright.dev/docs/release-notes) |
| TypeScript | 7.0.2 | 7.0.2 | [npm](https://registry.npmjs.org/typescript/latest), [릴리스](https://www.typescriptlang.org/docs/handbook/release-notes/overview.html) |
| Vite | 8.3.5 | 8.2.2 | [npm](https://registry.npmjs.org/vite/latest), [런타임 요구](https://vite.dev/guide/) |

Python은 프로젝트 `>=3.14,<3.15`를 유지하며 포터블 런타임은 기존 고정 SHA-256의 [3.14.8](https://www.python.org/downloads/release/python-3148/)이다. 로컬 시험은 Python 3.14.6·Node 24.18.1을 사용한다. 공식 문서 직접 조회가 403인 네 페이지는 브라우저 검색 도구로 확인했다. 새 API 사용이나 breaking API 이관은 없다.
