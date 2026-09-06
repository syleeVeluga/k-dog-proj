# K-DOG M4 설명·검토·내보내기 구현 기록

버전: v1.0

작성일: 2026-09-06

범위: [구현 지시서](K-DOG_바이브코딩_구현지시서_v1.0_20260905.md) M4·S6/S7·T06/T08/T11–T14, [검수](K-DOG_문서검수_v1.0_20260905.md) F-04/F-05

## 구현 결과

상세에서 현재/과거 실행의 점수와 리포트를 조회하고 운영자·교수·운영 관리자가 항목 선택지/미관찰 상태와 설명을 사유와 함께 수정한다. AI 원결과를 덮어쓰지 않으며 SQLite 5개 테이블과 기존 입력 불변 계약을 유지한다. 승인·반려 절차는 없다.

worker는 두 평가가 준비되면 S6 설명을 생성한다. Gemini가 기본 공급자이고 GPT/OpenAI·Claude/Anthropic도 기존 REST 전송 계층을 사용한다. 설명 처리 중에도 부분/전체 점수를 조회하며 설명 실패는 준비된 점수를 지우지 않는다. 공급자·모델·프롬프트·출력 한도는 신규 run 접수 때 고정한다.

`reporting.py`는 검토 revision·유효 점수 재계산·설명 근거 검증·대표 프레임을 담당한다. `exports.py`는 불변 batch snapshot과 실제 PDF/XLSX/CSV 파일을 만든다. `report_models.py`는 수정·설명·설정·내보내기 API 계약을 정의한다. `Reports.tsx`는 기존 목록·상세·개발자 화면에 검토/출력을 연결한다.

## 사용 방법

기존 [실행 안내](DEVELOPMENT.md)의 `uv sync --locked`, 프런트엔드 빌드, API와 worker 실행을 따른다. PDF/XLSX 출력에는 API 키가 필요하지 않다.

1. 개발자는 **리포트 설명 공급자**에서 공급자와 구조화 출력을 지원하는 모델 ID를 적용한다. 기존 실행은 변경하지 않는다. 환경 기본값은 `KDOG_REPORT_PROVIDER=gemini`, `KDOG_REPORT_MODEL`이며 Gemini 모델 미지정 시 `KDOG_GEMINI_MODEL`을 사용한다.
2. 운영자는 동의된 자료로 분석한다. 두 평가가 끝나면 설명이 생성된다. **현재 점수로 설명 생성·재시도**는 현재 실행 설정으로 설명만 다시 시도하며 성공한 관찰/평가를 재호출하지 않는다.
3. **항목 선택지·미관찰 상태 수정**에서 원본의 허용 선택지, 해당 항목의 근거, 수정 사유를 저장한다. 계산값을 직접 입력하거나 없는 점수를 생성하지 않는다. DOG-12·OWN-14의 미정 선택 규칙을 수동 채점으로 우회할 수 없다.
4. **대표 이미지 선택**에서 이 실행의 원본 영상과 초 단위 시간을 선택한다. FFmpeg가 실제 프레임을 추출하고 원본 해시·영상 소속·시간 범위를 검증한다. 생성 이미지나 다른 참가자 자료로 대체하지 않는다.
5. **설명 수동 수정**에서 표지 요약, 4영역 코멘트, ②④ 해설, 팁 1–2개, 근거 및 사유를 저장한다. 수정 전에 본 점수가 바뀌었으면 저장을 거절한다.
6. **개별 파일 내보내기** 또는 목록의 **전체 내보내기**에서 PDF/XLSX/CSV를 선택한다. 전체 출력은 행사 ID로 제한하거나 모든 행사를 포함한다. 검색·자료 상태 필터로 인원을 조용히 줄이지 않는다.
7. 파일 생성 실패/중단 시 **고정 버전 파일 생성 재시도**로 같은 snapshot을 재출력한다. 준비된 파일은 **파일 다운로드**로 받는다. 전달은 운영자가 외부에서 수동 수행한다.

M3 이전 실행에는 S6 설정이 없다. 기존 관찰·평가를 명시적으로 재사용한 새 실행을 만들거나 수동 설명을 저장할 수 있다. 신규 설정을 과거 실행에 주입하지 않는다. 키는 선택 공급자의 worker 환경 변수에서만 읽으며 UI·산출물·snapshot에 저장하지 않는다.

## 결과·수정·파일 버전

- `reviews/<run_id>/<id>.json`에 수정 revision 전체를 불변 저장하고 `changes`에 경로·해시·사용자·시각·사유를 기록한다. 항목 수정은 이전/이후 값도 기록한다. AI 단계 파일은 유지한다.
- 유효 결과는 원결과에 허용된 수정만 적용해 프로그램이 다시 집계한다. API는 수정 revision과 점수/평가/설문/근거의 `source_hash`를 함께 검사한다. 늦게 완료된 평가에 이전 설명 초안을 잘못 연결하지 않는다.
- 설명은 해당 source hash를 `steps`의 `report` 분기 키와 산출물에 고정한다. 점수 수정 뒤 기존 설명은 `stale`이며 최신 설명처럼 반환/내보내지 않는다. 수동 설명도 동일하게 점수 해시를 연결한다. 이미지 선택은 점수를 바꾸지 않아 설명을 불필요하게 무효화하지 않는다.
- 설명에는 허용 근거 ID만 연결한다. 4영역의 label/value 및 교차 유형 이름·규칙은 서버가 null/pending으로 고정한다. 안내 문구도 서버가 붙인다. 자연어 주장 자체의 정확성은 구조 검증만으로 보장되지 않으며 실제 품질 검증이 필요하다.
- 최초 포함 3회·구조 수정 최대 1회, 기존 지연/Retry-After·점유 토큰·중단 복구를 사용한다. 점수 수정으로 다른 source가 되면 별도 설명 시도 집합을 사용한다. 과거 source의 실패가 새 설명을 무한 재시도하게 만들지 않는다.
- `POST /api/exports`는 하나의 쓰기 트랜잭션에서 참가자 목록과 각 case의 현재 입력/session/display run, 수정, 설명, 이미지 bytes, 원응답, 항목집, 생성자/시각을 `export_id`에 고정한다. 과거 실행을 명시적으로 내보내는 경우만 그 실행을 선택한다. 전체 출력은 완료시각으로 run을 선택하지 않는다.
- 파일 생성은 snapshot 저장 후 트랜잭션 밖에서 수행한다. 도중 입력·점수·설명·이미지 수정이나 신규 참가자 등록은 이미 고정한 묶음을 바꾸지 않는다. 원본 JSON/이미지를 다시 조회해 새 값으로 교체하지 않는다.
- 파일 bytes를 원자적으로 게시하고 DB가 해시를 채택한다. 파일 게시 직후 중단으로 DB가 채택하지 못한 파일은 같은 snapshot으로 재생성한다. 이미 채택된 파일은 해시를 검사하고 그대로 다시 제공한다. 재출력/재다운로드는 AI를 호출하지 않는다.

## 출력 내용과 보류

개별 PDF는 표지/실제 대표 이미지, 4영역 비교 자리, 영역 코멘트·근거, 교차 해설, 팁, 안내, 점수/검토/버전 기록을 제공한다. 한국어와 ②④를 임베딩 글꼴로 표시한다. 전체 PDF는 `행사 ID/참가자 ID.pdf`의 ZIP이다. 구분자 조합이 같은 서로 다른 행사/ID도 충돌하지 않는다.

실제 XLSX는 전체요약·리포트·영역비교·행동55항목·행동집계·설문·근거·수정이력·규칙설명과 선택한 대표 이미지 시트를 포함한다. 점수는 숫자, ID는 문자열/텍스트 서식, 생성/수정 시각은 UTC 날짜 셀이다. 수식처럼 시작하는 입력도 문자열로 저장한다. CSV는 같은 9개 행 기반 표를 UTF-8 BOM ZIP으로 제공하고 실행 가능한 수식 접두어는 보호한다. CSV 자체에는 셀 타입이 없으므로 Excel에서 가져올 때 ID 열을 텍스트로 지정한다.

전체 출력에는 아직 worker가 실행되지 않은 참가자도 요약·55항목 상태·30문항 원응답을 남긴다. 0점이나 가짜 평가로 채우지 않는다. 삭제 요청된 자료는 제외하며, 결과 제공 동의가 없는 참가자가 포함되면 묶음 생성을 중단한다. 해당 참가자를 조용히 누락한 파일을 전체 파일로 제공하지 않는다. 파일 생성 전/채택 직전/다운로드 시 현재 동의를 확인하며 철회된 파일은 앱에서 재다운로드할 수 없다.

q23/C-2, DOG-12·OWN-14 선택 경계, 4영역 매핑·가중치, ②④ 유형은 기존 보류를 유지한다. **미정인 네 영역에 임의 막대 길이를 그리지 않는다.** 화면/PDF는 자기인식·AI관찰의 보류 자리를, XLSX는 두 비교 열의 null과 `mapping_pending`을 제공한다. 확정되지 않은 매핑의 실수치 그래프는 제공하지 않는다.

## 검증

2026-09-06: Python 전체 **92개**(기존 74 + M4 18), Playwright **7개**, production build, 원본 행동 55/설문 30 대조, `git diff --check`를 수행했다. 실제 공급자는 호출하지 않았다. 기존 Starlette TestClient의 httpx 사용 중단 예정 경고는 남아 있으며 시험은 통과한다.

주요 검증은 설명 지연 중 55항목 조회, 허용 근거/선택지/상태, 점수 수정 후 집계와 stale 설명 배제, 교수 수정 권한·개발자 데이터 차단, 설정 고정, 내보내기별 인원/타 참가자 혼입 방지, 원문 문자열 ID·숫자·한국어 PDF·CSV 내용, 철회 도중 파일/설명 채택 차단, 설명/출력 파일 게시 직후 중단 복구, AI 재호출 없는 재다운로드다.

실제 합성 영상으로 프레임을 추출해 PDF/XLSX에 넣었다. [데스크톱 미리보기](images/m4-report-desktop.png), [360px 미리보기](images/m4-report-mobile.png), [PDF 표지](images/m4-pdf-cover.png), [PDF 설명](images/m4-pdf-comments.png), [Excel 리포트](images/m4-excel-report.png), [Excel 이미지](images/m4-excel-image.png)를 확인했다. 청록색 프레임과 관찰/설명은 테스트 자료이며 실제 반려견/AI 결과가 아니다.

PDF 3페이지를 Poppler로 렌더링하고 한글·②④·줄바꿈·페이지를 확인했다. XLSX의 10개 시트 대표 범위를 렌더링했으며 보조 렌더러가 문자열 ID를 숫자로 표시하고 임베딩 이미지를 누락하는 한계가 있어 **실제 Microsoft Excel에서 읽기 전용으로 다시 검증**했다. Excel의 `0001` 텍스트와 1개 이미지 객체, 리포트/이미지 시트의 PDF 인쇄 결과를 확인했다. 대표 이미지가 가로 두 페이지로 분리되는 문제는 인쇄 영역/맞춤 설정으로 수정했다.

```powershell
# backend/
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
uv run --locked python -X utf8 -m tests.report_preview "$env:TEMP/kdog-m4-qa"
# frontend/
npm run build
npm run test:e2e
# root
git diff --check
```

## Cold review와 수정

M3 기준 `8756c8b` 이후 변경을 구현 후 다시 검토했다. 새 요구사항을 추가하지 않고 파일 분리와 동시 수정 계약을 중심으로 확인했다. 아래 3건은 **수정 전 실패하는 회귀 시험으로 재현**했고 수정 후 통과했다.

| 우선순위 | 발견 사항 | 수정·검증 |
|---|---|---|
| P1 | 한 분기만 완료된 결과로 설명을 쓰는 동안 나머지가 완료돼도 사람 revision은 같아 이전 설명을 전체 점수에 저장할 수 있음 | `expected_source_hash` 필수 검사. 같은 revision이라도 평가 source가 바뀌면 409 |
| P1 | `A-B` 행사/`C` 참가자와 `A` 행사/`B-C` 참가자의 ZIP 파일명이 같아 압축 해제 시 덮어쓸 수 있음 | 행사별 디렉터리/참가자 파일명으로 고유 경로 보장 |
| P2 | 대기 run은 설문 계산 step이 없어 내보내기 원응답이 null로 빠짐 | run 입력 snapshot의 30개 원응답을 계산 전에도 보존 |

추가로 개별 화면의 다운로드 이력은 개별 snapshot만 표시해 전체 묶음을 개별 파일로 혼동하지 않게 했다. 선택지/공급자 select에는 명시적인 접근성 레이블을 추가했다. 사용하지 않는 새 import만 정리했다.

코드 탐색은 codebase-memory `list_projects`·`index_repository`·graph 검색을 우선 사용했다. 재색인 후에도 그래프가 M0 196 nodes에 머물러 M1–M4 모듈이 누락되어, 해당 파일은 직접 읽기와 diff로 보완했다.

## 의존성·공식 문서 확인

확인일 **2026-09-06**. 공식 PyPI JSON/npm latest의 최신 안정 버전과 런타임/peer 조건을 조회했다. 기존 버전은 유지하고 출력 의존성만 정확한 버전과 lockfile로 추가했다.

| 패키지 | 최신 안정/선택 버전 | 사용·호환성 및 출처 |
|---|---|---|
| ReportLab | 5.0.1 | PDF, Python >=3.9,<4. [PyPI](https://pypi.org/pypi/reportlab/json), [5.0 변경](https://docs.reportlab.com/releases/notes/whats-new-50/), [TrueType](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/), [Platypus](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/) |
| Pillow | 12.3.0 | 이미지 검증·XLSX 이미지, Python >=3.10. [PyPI](https://pypi.org/pypi/pillow/json), [Image API](https://pillow.readthedocs.io/en/stable/reference/Image.html) |
| pypdf (dev) | 6.17.0 | PDF 내용 시험, Python >=3.9. [PyPI](https://pypi.org/pypi/pypdf/json), [추출 API](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) |
| openpyxl | 3.1.5 유지 | Python >=3.8. [PyPI](https://pypi.org/pypi/openpyxl/json), [스타일](https://openpyxl.readthedocs.io/en/stable/styles.html), [이미지](https://openpyxl.readthedocs.io/en/stable/images.html) |
| Pydantic / FastAPI | 2.13.5 / 0.141.1 유지 | Python >=3.9 / >=3.10. [Pydantic PyPI](https://pypi.org/pypi/pydantic/json), [모델](https://docs.pydantic.dev/latest/concepts/models/), [FastAPI PyPI](https://pypi.org/pypi/fastapi/json), [릴리스](https://fastapi.tiangolo.com/release-notes/) |
| Uvicorn / httpx | 0.52.4 / 0.28.1 유지 | Python >=3.10 / >=3.8. [Uvicorn PyPI](https://pypi.org/pypi/uvicorn/json), [httpx PyPI](https://pypi.org/pypi/httpx/json) |
| React / React DOM | 19.2.8 / 19.2.8 유지 | DOM peer React ^19.2.8. [React npm](https://registry.npmjs.org/react/latest), [DOM npm](https://registry.npmjs.org/react-dom/latest), [버전](https://react.dev/versions) |
| Vite / TypeScript | 8.2.2 / 7.0.2 유지 | Node ^20.19 또는 >=22.12 / >=16.20. [Vite npm](https://registry.npmjs.org/vite/latest), [TypeScript npm](https://registry.npmjs.org/typescript/latest) |
| Playwright Test | 1.63.0 유지 | Node >=20. [npm](https://registry.npmjs.org/@playwright/test/latest), [공식 릴리스](https://playwright.dev/docs/release-notes/) |
| React / DOM types | 19.2.18 / 19.2.7 유지 | DOM types peer React types ^19.2.0. [React types npm](https://registry.npmjs.org/@types/react/latest), [DOM types npm](https://registry.npmjs.org/@types/react-dom/latest) |

Python 3.14·Node 24 환경에서 설치·빌드·시험을 확인했다. ReportLab 5의 원격 이미지 가져오기 제한 변경은 해당하지 않는다. 출력은 검증된 로컬 bytes만 사용하며 원격 이미지 URL을 해석하지 않는다. [글꼴 출처·OFL·해시](../resources/fonts/README.md)를 함께 기록했다. FFmpeg는 기존 8.1.1을 유지하며 [공식 프레임 추출 계약](https://ffmpeg.org/ffmpeg.html)을 사용한다. AI API endpoint/구조화 출력 계약은 [M3 검증 기록](K-DOG_M3_구현기록_v1.0_20260906.md)의 기존 세 공급자 전송 계층을 재사용했다.

## 남은 범위

실제 동의된 참가자 영상·공급자 키로 관찰/평가/설명 품질과 모델 지원·과금은 **미검증**이다. 합성 자료/REST 모의 시험을 실연결 검증으로 간주하지 않는다. 4영역 실수치 그래프와 관계 유형은 책임자의 매핑·규칙 확정 전 보류한다. M5의 개발자 프롬프트 초안/시험/적용/복원·키 저장소·운영 복구 정리는 후속 범위다.
