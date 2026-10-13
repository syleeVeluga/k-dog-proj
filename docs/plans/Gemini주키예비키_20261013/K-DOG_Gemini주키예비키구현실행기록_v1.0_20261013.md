# K-DOG Gemini 주키·예비키 구현 실행 기록

버전: v1.0 · 2026-10-13 · 상위: [전체 계획](K-DOG_Gemini주키예비키적용계획_v1.0_20261013.md)

## 공식 API·의존성 확인

확인일 2026-10-13. 새 패키지를 추가하지 않고 기존 manifest/lockfile을 유지한다. Python 3.14.2와 Node 24.13.0을 사용한다. 이번 기능은 평가 규칙·모델 변경이나 의존성 업그레이드를 요구하지 않으므로, 기존 검증된 잠금판에서 기능 변경을 검증한다.

PyPI JSON과 npm 공식 registry의 최신 안정판 및 runtime/peer를 직접 조회했다. Python 패키지의 Python 최소 버전은 모두 3.14 실행을 허용한다. React DOM/타입의 React peer는 잠금판 조합을 유지하며, Vite는 Node >=22.12, Playwright는 Node >=20, TypeScript는 Node >=16.20 조건을 확인했다.

| 패키지 | 최신 안정판 | 선택 잠금판 | 공식 registry |
| --- | --- | --- | --- |
| Pydantic | 2.14.1 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/) |
| FastAPI | 0.143.0 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/) |
| Uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/) |
| HTTPX | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/) |
| OpenPyXL | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/) |
| ReportLab | 5.0.1 | 5.0.1 | [PyPI](https://pypi.org/project/reportlab/) |
| Pillow | 12.3.0 | 12.3.0 | [PyPI](https://pypi.org/project/pillow/) |
| Cryptography | 50.0.2 | 50.0.2 | [PyPI](https://pypi.org/project/cryptography/) |
| PyPDF | 6.20.1 | 6.19.0 | [PyPI](https://pypi.org/project/pypdf/) |
| React / React DOM | 19.3.0 | 19.2.8 | [React](https://registry.npmjs.org/react), [DOM](https://registry.npmjs.org/react-dom) |
| TypeScript | 7.0.2 | 7.0.2 | [npm](https://registry.npmjs.org/typescript) |
| Vite | 8.3.4 | 8.2.2 | [npm](https://registry.npmjs.org/vite) |
| Playwright Test | 1.64.0 | 1.63.0 | [npm](https://registry.npmjs.org/@playwright/test) |
| React types / DOM types | 19.3.0 / 19.3.0 | 19.2.18 / 19.2.7 | [React](https://registry.npmjs.org/@types/react), [DOM](https://registry.npmjs.org/@types/react-dom) |

[Pydantic 타입/API](https://docs.pydantic.dev/latest/concepts/types/), [changelog](https://docs.pydantic.dev/latest/changelog/), [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/), [typed response API](https://fastapi.tiangolo.com/tutorial/response-model/), [Uvicorn releases](https://github.com/Kludex/uvicorn/releases), [React releases](https://react.dev/blog), [Vite releases](https://vite.dev/releases), [Playwright releases](https://playwright.dev/docs/release-notes), [TypeScript releases](https://www.typescriptlang.org/docs/handbook/release-notes/overview.html)를 확인했다. SecretStr·typed response·기존 API를 사용하며 최신 minor 변경을 이번 범위에 섞지 않는다. 기존 Uvicorn release-notes URL 조회 실패는 공식 GitHub releases 조회로 보완했다. 새 Uvicorn API 도입은 없다.

선택판 registry도 재확인했다. FastAPI 0.141.1은 Pydantic >=2.9.0, Pydantic 2.13.5는 pydantic-core 2.46.5를 요구하며 기존 lockfile 조합을 유지한다. React DOM 19.2.8의 React ^19.2.8과 DOM types 19.2.7의 React types ^19.2.0 요구에 현재 잠금판이 맞는다. API는 기존 response_model/SecretStr/REST만 사용하며 새 minor의 기능을 요구하지 않는다.

[Gemini Interactions errors](https://ai.google.dev/gemini-api/docs/api-errors), [troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting), [Files API](https://ai.google.dev/gemini-api/docs/files)를 확인했다. HTTP/정규 code와 로컬 credential 원인을 분리하고 provider message는 저장하지 않는다. 기존 REST와 Windows DPAPI를 사용하며 SDK 재시도를 도입하지 않는다.

## GK01 이중키 저장·API

착수 조사 기준 `6b0d195` 이후 계획 PR #94가 병합된 `ba8508f`를 최종 기반으로 사용한다. 브랜치 `veluga/gk01-gemini-key-slots`.

기존 `gemini` target/reference/ciphertext는 주키로 유지하고 `gemini:backup`을 추가했다. 신규 슬롯 API는 required `expected_reference`를 write fence에서 비교한다. 현재 developer 활성/역할을 같은 fence에서 재검사한다. 원문 중복은 다른 가용 슬롯의 복호화 값과 일시 비교하고 거절한다. 두 슬롯 전체 폐기는 한 transaction으로 확정하며 unlink 실패도 폐기를 되돌리지 않는다.

`gemini_slots`는 source/로컬 미가용 사유와 현재 reference의 시험 결과를 제공한다. 각 시험은 한 슬롯만 요청하고 당시 reference/시각에 고정한다. 백업/복원은 기존 키 제외 정책을 그대로 사용한다. 복원된 주키·예비키 모두 파일 미가용으로 명시 재등록이 필요하며 환경 변수로 부활하지 않는다. 자동 실행 전환은 GK02의 범위다.

검증: 기존 settings 8개와 신규 슬롯 9개(17개/11.987초) 통과. 기존 Gemini transport 4개 포함 13개/6.496초 통과. frontend build와 settings/retirement E2E 2개/7.7초 통과. 실제 Windows DPAPI, 두 슬롯 동시 등록·동일 슬롯 stale 경쟁, 실패한 unlink, 개발자 비활성, Host/Origin, validation 비밀 미반사, backup/restore 재등록을 검사했다. 최초 신규 보안 시험에서 기존 Host 거절 status를 403으로 잘못 기대한 1건을 실제 400 계약에 맞췄다.

분리 검토 단계에서 기존 `secret.test` JSON에 slot/시각이 없는 경우 typed 응답이 실패할 수 있음을 발견해 수용했다. 감사 `happened_at`과 primary 기본값으로 읽고 현재 reference의 최신 시험을 조회하도록 수정했다. 늦은 retired 시험이 새 reference의 시험을 가리지 않도록 회귀를 추가했다. 수정 중 시험 코드 배치 오류 1건을 바로잡고 신규 10개/7.211초 통과. 독립 reviewer 및 최종 triage/PR/병합 기록은 완료 후 추가한다.

실제 운영 키 조회·실공급자 호출·참가자 영상 사용·운영 DB 변경·고객 배포는 수행하지 않았다.
