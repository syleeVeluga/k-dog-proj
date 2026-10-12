# K-DOG 360 통합 MP4 구현 실행 기록

버전: v1.0 · 2026-10-12 · 상위: [전체 계획](K-DOG_360통합MP4업로드계획_v1.0_20261012.md)

## MP01 계약·보관·분석 입력 경계

착수 기준은 ES03 [PR #89](https://github.com/syleeVeluga/k-dog-proj/pull/89) 병합 `5ef483f`다. 브랜치는 `veluga/mp01-external-360-media`다.

- `external_360_mp4`는 MP4·typed external_processing·부모0·conversion null로 접수한다. 기존 종류의 부모 요구와 기존 null 직렬화를 유지한다. EXT360/null 원본 번호를 서버에서 검사한다. DB 테이블 재구축·이전 점수 이관·산식 변경은 없다.
- PATCH는 같은 video/upload/hash의 새 입력 판본으로 처리 정보만 정정한다. 원래 receipt request_json/hash/link_json와 이전 manifest는 보존한다. 현재 actor·로그인 세션·선택 회차·revision·파일 identity/hash·불변 출처를 저장 직전에 재확인한다. 시간 근거에 쓰인 timeline 정정은 촬영 재확정을 요구한다.
- flat/preserved만 클립 후보다. 나머지는 conversion_required와 파일별 사유로 남는다. projection과 timeline은 별개다. 펼침/preserved는 촬영 시간 근거로 사용할 수 있다. edited/unknown의 기준·사건·coverage·확정 offset은 촬영 확정 및 전처리에서 거절한다. 값 없는 offset과 초안은 보존한다.
- 고정 batch 검증은 해당 manifest 판본의 유효 metadata와 source snapshot을 대조한다. 현재 입력 재사용과 과거 pin 제공을 구분한다. revision 변경 guard·ES 실행별 actor/result pointer와 이력을 유지한다.
- 새 시험 `backend/tests/test_external_media_v4.py`는 단일 파일 공유 등록/재시작·정정·기존 canonical JSON·보존 파일 등록·9조합·영상 전송 후보 제외·시간 앵커·과거 실행/outdated·진행 중 정정 guard·backup/restore/clean을 검증한다. 합성 bytes/FFmpeg 영상과 기존 fixture만 사용했다. 유료/실제 외부 공급자 요청0이다.

독립 reviewer `mp01_cold_review`가 읽기 전용 검토했다. 아래 2건을 수용했고 보류/거절0이다.

| 발견 | 결정과 수정 |
| --- | --- |
| CR-IMP01 / P2: PATCH가 request hash·kind/camera/binding 손상을 거절하지 않음 | 수용. `_external_source`로 읽기/쓰기 양 단계의 원장 해시·불변 출처를 대조하고 hash 검사 중 JSON/hash/binding 변화도 거절한다. 최초 external_processing과 유효 metadata는 등치하지 않는다. 변조 및 로그인 변경 회귀 추가 |
| CR-IMP02 / P2: 선택 expected_sha256과 실제 hash 대조 누락 | 수용. 선언 hash가 있으면 실제 SHA-256과 대조한다. linked state·scope·binding 대상도 검사하고 변조 회귀 추가 |

시험 fixture의 frozen model 직접 변경·누락 evidence_id·restore 인자·clean 예외 기대는 실제 기존 계약에 맞춰 수정했다. 제품 변경을 위해 기존 보관 정책을 느슨하게 하지 않았다.

기존 지정 회귀111개와 새 계약/합성8개가 통과했다. 최초 통합 실행117개/431.794초에서 clean 시험의 기대 예외1건만 실패했고, fixture 수정 뒤 신규7개/21.582초·보존등록1개/1.180초를 통과했다. 수용 수정 후 API4개/4.990초, 최종 request ID·scope·binding·hash 변조7종/로그인 race1개/1.577초도 통과했다. 기존 입력·수신·촬영·전처리·보관·업무권한·ES 실행 조회 회귀에 제품 실패는 없었다. 중복 실행은 고유 시험 개수에 더하지 않았다.

reviewer는 두 수용 건의 코드상 해결과 신규 독립 결함0을 확인했다. 마지막 원장 request ID 대조 권고도 같은 범위로 수용·시험했다. `git diff --check` 통과. PR/commit/병합은 아래에 연결한다.

MP01: [PR #90](https://github.com/syleeVeluga/k-dog-proj/pull/90), 구현 `1327ab8`, main 병합 `d4959a7`. 원격 PR의 check rollup은 비어 있었고 위 로컬 검증을 근거로 병합했다.

## MP02 단일 파일 업로드·처리 정보 화면

MP01 병합 `d4959a7`에서 `veluga/mp02-360-upload-ui`로 착수했다. typed metadata와 표시를 추가하며 기존 ES 내 실행·지정 상세·pending resolver·generation/폴링 코드는 유지한다.

- 새 선택지는 MP4 단일 선택·unknown 기본값·선택 도구/메모다. 부모 원본과 카메라/원본 번호를 요구하지 않고 EXT360/null은 요청 내부에서만 사용한다. 기존 보존 파일도 같은 종류로 등록할 수 있으며 이미 등록한 종류는 덮어쓰지 않는다.
- 파일 선택 시 출처·대상/회차·metadata를 대기 항목에 고정한다. 전송 전 external metadata는 해당 항목에서만 수정할 수 있다. 요청 시작 후 ID/본문을 고정하여 응답 유실·전송 실패 때 같은 요청으로 재시도한다. 새 파일의 선택 옵션 변경은 기존 큐를 재분류하지 않는다.
- 처리 정보 편집은 원래 선언과 현재 입력을 구분해 표시한다. revision 충돌은 초안을 유지하고 최신값 확인/명시 폐기 뒤 재입력한다. 파일별 고정 회차에 편집기를 유지하여 다른 직원의 회차 변경·완료 목록 접기에도 값이 사라지지 않는다. 회차가 다르면 저장을 차단한다.
- 현재 입력의 사유와 과거 지정 batch의 고정 metadata를 각각 표시한다. 기본 화면·부모 옵션·영상/클립/오디오·접근성 이름은 EXT360 대신 「360 통합 영상」을 쓴다. 미지원 파일도 보관 성공을 표시하되 실제 전처리 사유와 다음 동작을 안내한다.

검증: build 통과. 지정 기존 E2E45개 및 신규4개를 고유 시험 기준으로 통과했다. 최초48개 중46 통과/신규 선택항목2 timeout은 명시 접근성 이름 보완으로 해결했다. 수용 수정 후 업로드·촬영·전처리·context16개/1.0분 통과, 카드 PNG 보완 뒤 신규4개/25.4초 통과. 360/390/768/1440px 가로 넘침0과 실제 API 업로드/download bytes·정정 판본·전송1회, 응답 유실 고정 요청, 409·자동 회차 갱신 초안 보존을 확인했다. 실제 FFmpeg mixed 파일의 정상 클립1개/미지원 클립0·시간 앵커 거절·과거 지정 execution metadata/outdated·자동 재실행0도 확인했다.

독립 reviewer `mp02_cold_review`의 P2(회차 갱신 때 정정 초안 소실)·P3(부모 목록 내부 코드) 2건을 모두 수용·수정·시험했다. 재검토에서 해결·신규 actionable0을 확인했다. 추가 라이브러리/SDK·의존성 변경은 없다. Node24.13.0에서 선택 React DOM19.2.8의 React^19.2.8, Playwright1.63.0의 Node>=20, Vite8.2.2의 Node^20.19 또는 >=22.12를 공식 선택판 registry로 대조했다. [React effect API](https://react.dev/reference/react/useEffect), [Vite build](https://vite.dev/guide/), [TypeScript](https://www.typescriptlang.org/docs/)도 확인했다.

합성 PNG를 직접 시각 검수했다: [새 옵션](evidence/mp02-option.png), [파일 수신 완료](evidence/mp02-file-complete.png), [390px 등록 카드](evidence/mp02-registered-390.png), [전처리 제한/고정 정보](evidence/mp02-preprocess-1366.png). 실제 참가자 영상/프레임은 없다.

## 의존성 확인 — 2026-10-12

MP02: [PR #91](https://github.com/syleeVeluga/k-dog-proj/pull/91), 구현 `a76093c`, main 병합 `befa18c`. 이 commit에서 MP03 `veluga/mp03-360-upload-acceptance`를 시작했다.

## MP03 통합 인수·설치 검증 — 진행 중

- 실제 decoded 단일/혼합 전처리와 실행 조합은 MP01의 9조합/guard/pin 시험 및 MP02의 실제 HTTP/FFmpeg·정정/outdated/과거 실행 화면 시험으로 연결한다. VM-ES-T01~04의 actor/실행ID·세션/판본·지연응답 보호는 기존 ES 회귀와 함께 검사한다.
- 새 `test_external_media_acceptance_v4`는 실제310초·64x64·2fps/오디오 FFmpeg 합성 MP4 하나를 부모0·EXT360 flat/preserved로 수신/등록하고 실제 전처리 batch를 만든다. batch의 실제 clip ref/hash가 가짜 공급자에 전달됐는지 확인하며 S1 Worker·86 AI 원자료·기본/최종결과·리포트를 연결한다. 공급자 요청31건과 프로그램 처리 항목군은 실제 가용창에 따라 구분한다. 수작업 fixture의42건을 실제 창에 강요하지 않는다. 기존 program-only 합성 renderer seam을 사용하며 제품 산식을 복제하지 않는다. 나중 처리 정보 정정 뒤 기본결과 원문/발급 PDF hash가 같음을 확인했다(1개/69.676초). 리포트 PDF bytes는 합성 fixture이며 실제 renderer 전체 회귀는 별도다. 유료 외부 호출0이다.
- 기존 `build_release.py`/`verify_release.py`/launcher 방식과 allowlist를 유지한다. 추가 `scripts/verify_mp4_package.py`는 설치 패키지의 실제 interpreter·HTTP 접수/조회/download·감독 재시작에서 새 종류와 최초 선언/정정 판본 보존을 확인한다. content 저장/정정은 합성 interpreter 동작이며 HTTP upload/decode 시험을 대체하지 않는다. online은 PATH uv/FFmpeg와 venv를 사용하고 직접 interpreter 호출 전 잘못된 PYTHONHOME/PYTHONPATH를 제거한다.
- 독립 reviewer `mp03_cold_review`의 P2 2건을 수용했다: online venv 직접 호출의 잘못된 Python 환경 변수 제거, 수작업 batch만 연결했던 종단 시험을 실제 MP4 전처리 batch로 교체. 최초 전체 UI132개에서129 통과/3 실패를 확인했고 긴 파일명 모바일 CSS(이전 aria-label selector)와 새 mixed 시험의 operator 이력 간섭을 각각 현재 selector1줄/전용 합성 계정으로 수정했다. 촬영 판본 충돌 시험의 기존 폴링 기대 실패1건은 해당 코드를 바꾸지 않고 같은 expectation으로 재검증해 통과했다. 수용 수정 후 관련15개/1.4분 통과. reviewer는 두 수용 건과 추가 수정의 해결·신규 actionable0을 확인했다. 최종 전체 UI를 다시 확인한다.
- 깨끗한 checkpoint `6ea8940`의 portable/online ZIP을 만들고 기존 설치 검증 및 새 MP4 런타임 접수·정정·재시작/download 검증을 모두 통과했다. 이 checkpoint 이후의 CSS/인수 fixture 수정과 최종 문서를 포함한 깨끗한 commit으로 최종 ZIP을 다시 만들며, 위 후보 ZIP을 최종 배포물로 표시하지 않는다. 현재 Windows 한 대의 새 한글/공백 경로·임시 synthetic DB 검증이며 깨끗한 OS/물리 PC3대 실측은 아니다.

백엔드 전체 `uv sync --locked`/unittest discover는749개·1225.046초에서747 통과/2 skip으로 끝났다. skip은 미제공 역사적 고객 원본 번들의 대조 시험2개이며 S1 제품 회귀 실패가 아니다. 전체 실행이 먼저 import한 초기 연결 fixture를 이후 실제 decoded chain으로 보강해 별도 통과했다. 마지막 실제 종단 fixture44.325초는 op 업로드→review 전처리/AI·리포트→dev metadata 정정·과거 공유 조회→review 현재 입력의 명시 새 execution까지 확인한다. 이전/새 실행ID·원래 실행자·outdated·과거 basic/PDF bytes를 보존하고 새 펼침 영상 클립0을 확인했다. 중복 실행은 고유 시험 수에 더하지 않았다.

문서9개의 로컬 링크62개를 실제 파일과 committed-tree 목록으로 검사해 오류0을 확인했다. diff-check 통과. Graft build/check의 wiring sync OK를 확인했고 deep concept 요약은 미생성 상태로 별도 표시했다.

## 추가 의존성·실행 환경 확인 — 2026-10-12

공식 PyPI registry에서 Uvicorn 최신0.54.0/선택0.52.4, openpyxl 최신/선택3.1.5, ReportLab5.0.1/5.0.1, Pillow12.3.0/12.3.0, cryptography50.0.2/50.0.2, pypdf6.20.0/6.19.0을 확인했다. 각 Python>=3.8~3.10 조건(ReportLab<4)을 만족하는 기존 Python3.14 조합을 유지한다. [Uvicorn](https://pypi.org/pypi/uvicorn/json), [openpyxl](https://pypi.org/pypi/openpyxl/json), [ReportLab](https://pypi.org/pypi/reportlab/json), [Pillow](https://pypi.org/pypi/pillow/json), [cryptography](https://pypi.org/pypi/cryptography/json), [pypdf](https://pypi.org/pypi/pypdf/json).

실제 개발 runtime은 Python3.14.2·Node24.13.0·uv0.11.18·PATH FFmpeg8.1.1이다. [Python 공식 최신](https://www.python.org/downloads/)은3.15.0이며 프로젝트>=3.14,<3.15 제약과 기존 package 선택3.14.8을 유지한다. [uv 최신](https://pypi.org/pypi/uv/json)0.13.0, [FFmpeg 최신](https://ffmpeg.org/download.html)9.0.2(8.1 계열 최신8.1.3)을 확인했다. portable은 기존 hash 고정 Python3.14.8·FFmpeg9.0.2 최소 빌드를 사용한다. 기존 PC 도구/상관없는 잠금 의존성을 자동 업그레이드하지 않았다. npm @types 최신19.3.0/기존 React19.2 잠금 타입을 유지했다.

`npm ci`/audit는 기존 빌드 의존성 source-map-js1.2.1의 high1건([GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q))을 반환했다. [공식 registry](https://registry.npmjs.org/source-map-js/latest)의 수정 안정판1.2.2·Node>=0.10을 확인했다. 현재 제품 ZIP에는 node_modules나 source map 처리 서비스가 없고 정적 dist를 사용한다. 이번 업로드/인수 범위에서 잠금 파일을 바꾸지 않았으며 빌드 도구 후속 정비로 남긴다. audit0이라고 표시하지 않는다.

## 의존성 확인 표 — MP01·MP02

| 대상 | 최신 안정판 / 선택 잠금판 | 근거 |
| --- | --- | --- |
| Pydantic | 2.14.1 / 2.13.5 | [PyPI](https://pypi.org/pypi/pydantic/json), [선택판](https://pypi.org/pypi/pydantic/2.13.5/json), [model serializer](https://docs.pydantic.dev/latest/concepts/serialization/) |
| FastAPI | 0.143.0 / 0.141.1 | [PyPI](https://pypi.org/pypi/fastapi/json), [선택판](https://pypi.org/pypi/fastapi/0.141.1/json), [PATCH](https://fastapi.tiangolo.com/tutorial/body-updates/), [release notes](https://fastapi.tiangolo.com/release-notes/) |
| HTTPX | 0.28.1 / 0.28.1 | [PyPI](https://pypi.org/pypi/httpx/json) |
| React/react-dom | 19.3.0 / 19.2.8 | [React versions](https://react.dev/versions), [React registry](https://registry.npmjs.org/react/latest), [DOM registry](https://registry.npmjs.org/react-dom/latest) |
| Playwright | 1.64.0 / 1.63.0 | [registry](https://registry.npmjs.org/@playwright/test/latest), [release notes](https://playwright.dev/docs/release-notes) |
| Vite | 8.3.4 / 8.2.2 | [registry](https://registry.npmjs.org/vite/latest) |
| TypeScript | 7.0.2 / 7.0.2 | [registry](https://registry.npmjs.org/typescript/latest) |

기존 Python3.14/Node 잠금 조합을 유지한다. 선택 Pydantic은 Python>=3.9, FastAPI는 >=3.10·Pydantic>=2.9이며 프로젝트 Python3.14와 호환된다. 최신 React DOM은 React^19.3.0을 요구하므로 관련 없는 업그레이드를 섞지 않는다. Playwright 최신 Node>=20, Vite 최신 Node^20.19 또는 >=22.12, TypeScript Node>=16.20 조건을 확인했다. 새 의존성·SDK·잠금 파일 변경은 없다. 선택판 UI API/peer와 실제 runtime은 MP02에서 대조한다.

## 실제 파일·현장 인수

실제 Studio 파일이 제공되지 않았다. 360 직접 AI 시야/미세 행동 판독, 원본 대비 품질, 장시간 오디오/시각 정확도, GB급 성능은 미실행이며 [실측 후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)의 E01~E05/P01을 따른다. 합성 기술 인수를 실측 완료로 표시하지 않는다.
