# K-DOG S1 통합 Cold Review

버전: v1.0 · 2026-10-04 · 대상: PR #40 `veluga/s1-integrated-release`, 검토 시작 `360b722b`

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 연결: [실행 기록](K-DOG_구현실행기록_v1.0_20261003.md), [인수 검증](K-DOG_인수검증대장_v1.0_20261003.md), [실측·확인 후속](K-DOG_실측및확인후속대장_v1.0_20261003.md).

## 검토 범위와 기준

S00~S17의 현재 구현을 S1.1 원문·요구사항/인수 대장과 대조하고, 제품의 호출 관계를 기준으로 퇴역 코드와 현재 필요한 계약을 구별했다. 특히 구판 진입, 설정 분기, 공유 모듈의 숨은 의존, 원본 보존·삭제/철회·불변 결과·재시도 경계를 검토했다. 실제 영상/유료 공급자 실측과 미확정 정책은 기존 후속 대장의 범위로 유지한다.

코드 탐색은 graft map/ask/grep/skeleton/callers와 코드 범위를 사용했다. 모듈 수준 import는 graph 결과와 AST import 검사로 보완했다. 이미 존재한 `docs/큐브전달_20260929/` 원본15개 삭제는 이번 수정에 포함하거나 복구하지 않았다. 원본이 있는 별도 Git 작업 트리에서 전체 회귀를 실행했고, 현재 고객 원본12개의 bytes/hash를 수령 목록과 다시 대조했다. 민감한 원본은 commit/배포에 포함하지 않는다.

## 발견사항 수용 검토

| ID | 발견사항·영향 | 최종 결정·근거 | 반영 |
| --- | --- | --- | --- |
| CR01 | API factory의 구판 선택 인자와 퇴역 endpoint, UI의 구판 분기가 남아 S1 단일 운영 경계를 불필요하게 복잡하게 했다. | 수용. S01은 구판 점수/실행 호환을 요구하지 않으며 원입력 보존과 구판 실행은 별개다. | 구판 API/화면/설정·partial import·전처리·채점·보고서 실행 제거. factory/신규 접수는 S1만 생성. 알 수 없는 API는 JSON404, OpenAPI에는 catchall 미노출. |
| CR02 | S1이 구판 `sheets`에서 권한/참조 helper3개를 가져오며 구판 점수·전처리 규칙을 함께 로드했다. | 수용. helper의 현재 의미와 권한 재확인은 유지하고 퇴역 실행 모듈에 대한 의존만 제거한다. | helper3개를 `sheets_v4.py`로 동일하게 이동, S1 callers 변경, 고립된 구판 모델/실행 코드 제거. |
| CR03 | CLI의 S1 gate와 별개로 공유 Python Worker에는 구판 실행 dispatch와 provider 구현이 남아 있었다. | 수용. 직접 Worker 사용으로 구판 실행이 재진입할 수 없어야 한다. | Worker/analysis는 `s1`·`report_v4`만 허용, 기본 scorer는 GeminiScorerV4. 구판 큐 미호출 회귀 추가. 점유/불변 attempt/호출 계량/원격 정리 유지. |
| CR04 | 배포 allowlist에 더 이상 사용하지 않는 구판 채점·전처리·리포트 자산이 포함될 수 있었다. | 수용. 원본 보존/추출에 필요한 자산만 구별하여 남긴다. | scoring-v1/v2, preprocess-v1/v2/v3, 구판 report presentation 및 미사용 매핑을 ZIP에서 제외. runtime 필수 자산 존재/허용 검증. |
| CR05 | 구판 실행 시험은 제거한 API/설정/채점 계약을 유지하도록 요구하며 current fixture도 판본 선택 인자를 사용했다. | 수용. 존재하지 않는 제품 동작의 회귀를 유지하면 제거가 불완전해진다. | 퇴역 실행 시험 삭제, 공통 접수·동의·원입력 migration·삭제/복원·키 보호·미디어 절단 시험은 S1 또는 raw fixture로 유지. 제거 endpoint404와 schema·Python Worker 차단 추가. |
| CR06 | 모든 v1/v2/v3 이름과 원본 읽기 코드를 일괄 제거하는 제안. | 거절. S1이 현재도 쓰는 28문항 survey-v3와 raw source-only/reset/백업 참조, 역사 카탈로그 추출 시험이 손상된다. | 역사 fixture·원본 읽기·공용 계약은 유지. 구판 점수 migration/조회/실행은 복구하지 않음. |
| CR07 | 설정 판본·재시도·다중카메라·명시 공개·외부 비교 승인 구조를 ‘복잡함’만으로 축소하는 제안. | 거절. 현재 S1 요구사항과 독립 채점, 불변 재시도, 원격 비용/정리, 연구 철회 방지에 직접 필요하다. | 현재 동작 유지. 키 vault와 기존 키 폐기/보호 기능도 공통 운영 인프라로 유지. 미사용 구판 pipeline 설정만 제거. |
| CR08 | 실제 영상 검증·물리3PC/LAN·미수령 Excel·D/G 확인을 이번 코드 병합의 완료 조건으로 추가하는 제안. | 보류. 앞선 사용자 지시의 실측 후속 분리와 미확정 규칙 경계를 유지한다. | 후속 대장 E/P 항목 유지, 임의 규칙/승인·실제 AI 호출 추가 없음. |

수용 건만 수정했다. 현재 S1 계산·판정·보고서 산식에는 임의 변경이 없다. 위 제거와 직접 Worker 구판 차단 외에 재현되지 않은 문제를 추정 수정하지 않았다.

## 검증

제품 코드 commit은 `940cf738c805bce18483cd4276ce91a405691066`이다. 전체 시험은 이 commit과 동일한 코드의 별도 작업 트리에서 실행한다. 초기 실패를 통과로 합산하지 않는다. 최종 변경을 다시 검토하여 수용 건의 제거 범위·caller/import·권한/원본/불변 결과 보호와 문서 링크를 확인했으며 추가로 수용할 미해결 발견사항은 없다.

- `backend/`: `uv run --locked python -X utf8 -m unittest discover -s tests -v` **574개/586.821초/OK/exit0/skip0**. 종전685개에는 이번에 제거한 구판 제품 실행 시험이 포함됐다. 현재 S1의 T01~T32/O01~O14 연결 시험과 원본/migration·동의/삭제·공통 인프라 검증은 유지한다.
- ZIP CRC·중복/경로·manifest 정확한 파일 집합·146개 파일 hash·퇴역 실행/보호 원본 미포함 감사 통과.

- `frontend/`: `npm run test:e2e` **41개 전체/3.6분/exit0/skip0**. 공유 저장소 전체 순서를 다시 통과했으며 단독 통과를 전체 통과로 대신하지 않았다. Windows asyncio의 연결 종료 callback10054 로그2회는 실행 결과와 구별했다.
- `npm run build`: 52 modules, JS463.09kB, 통과. 구판 UI 제거 후 종전 bundle 크기 경고가 없어졌다.
- `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`: S1 자산8개 원문 대조 통과. G01/G04 미수령·실제 Excel import 비활성 메시지를 유지한다.
- 수령 목록 SRC01~SRC12의 크기/SHA-256 모두 재확인. 검증 트리에는 기존 Git의 역사 원본을 유지하여 역사 v3 source/CLI 시험도 실행한다. 기본 작업 폴더의 사용자 삭제15개는 포함하지 않는다.
- `python -X utf8 scripts/build_release.py <ZIP>`: 깨끗한 검증 트리에서 source commit `940cf73`,146파일 ZIP 생성. 제품 코드는 이번 정리를 반영하며 이후 리뷰 문서 갱신은 이 ZIP의 source commit과 구별한다.
- `python -X utf8 scripts/verify_release.py <ZIP>`: 현재 Windows의 새 한글/공백 경로·새 venv 설치, 손상 파일의 설치 전 거절, 환경변수 격리, 로그인/접수/재시작, supervisor 종료 통과. 실제 AI 호출0. 깨끗한 OS·별도 물리PC의 실측으로 표시하지 않는다.
- 검증 ZIP: `releases/k-dog-v0.3.0-s1-windows-x64-940cf73.zip`, SHA-256 `b835290bf104a13a0f7e4d9b85165e58d3331104cccecfad9620d8c2c9379e8b`. 종전 `aedab57` ZIP은 이번 구판 제거 이전의 이력이다.

브라우저 중간 실행에서는 같은 트리의 패키지 build가 dist를 교체하는 순간 GET `/`404가 발생해 시험1개가 시간 초과됐다. 코드 수정으로 숨기지 않고 build와 브라우저 실행을 겹치지 않게 최종 전체41개가 통과했다. 판본 선택 인자를 넘긴 fixture와 구판URL409 기대는 현재 계약으로 수정한 후 재검증한다.

## 의존성과 호환성

2026-10-04 공식 PyPI/npm registry의 최신 안정판과 공식 API/릴리스 문서를 재확인했다. 새 패키지·잠금 변경은 없으며 Python3.14.2와 Node24.13.0에서 기존 잠금을 사용한다. 원래 고정된 버전의 API를 유지하고 관련 없는 업그레이드는 제외했다.

| 패키지 | 최신 안정판 | 선택한 잠금 | 공식 확인 |
| --- | --- | --- | --- |
| Pydantic | 2.13.5 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [API](https://docs.pydantic.dev/latest/api/base_model/) |
| FastAPI | 0.142.2 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/), [릴리스](https://fastapi.tiangolo.com/release-notes/) |
| Uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/) |
| openpyxl | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/), [문서](https://openpyxl.readthedocs.io/en/stable/) |
| ReportLab / Pillow | 5.0.1 / 12.3.0 | 동일 | [ReportLab](https://pypi.org/project/reportlab/), [Pillow](https://pypi.org/project/pillow/) |
| HTTPX | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/), [transport](https://www.python-httpx.org/advanced/transports/) |
| React / react-dom | 19.3.0 | 19.2.8 | [registry](https://registry.npmjs.org/react/latest), [공식 버전](https://react.dev/versions) |
| @types/react / react-dom | 19.3.0 | 19.2.18 / 19.2.7 | [React 타입](https://registry.npmjs.org/@types/react/latest), [DOM 타입](https://registry.npmjs.org/@types/react-dom/latest) |
| Vite | 8.3.2 | 8.2.2 | [registry](https://registry.npmjs.org/vite/latest), [공식 안내](https://vite.dev/guide/) |
| TypeScript | 7.0.2 | 7.0.2 | [registry](https://registry.npmjs.org/typescript/latest), [공식 문서](https://www.typescriptlang.org/docs/) |
| Playwright | 1.63.0 | 1.63.0 | [registry](https://registry.npmjs.org/@playwright/test/latest), [릴리스](https://playwright.dev/docs/release-notes) |

Pydantic/FastAPI의 현재 요청·응답 계약과 기존 TestClient, React19.2의 renderer·타입 조합을 유지했다. Node24는 Vite의 Node20.19+/22.12+ 및 Playwright Node20+ 조건을 만족한다. 테스트의 Starlette HTTPX deprecation 경고는 통과 여부와 분리하고 의존성 변경을 섞지 않았다.
