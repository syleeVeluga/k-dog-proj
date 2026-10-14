# K-DOG 4카메라·구간 CSV 구현 실행 기록

버전: v1.0 · 2026-10-14 · 착수 기준: `2f015c2` · 상태: VC01 #100·VC02 #101·VC03 #102·VC04 #103 구현·검증·독립 검토·문서·병합 완료

상위: [전환 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md). 각 PR은 구현 → 검증 → 독립 cold review → 수용 건 반영·재검증 → 문서 → 병합 순서로 진행한다. 2026-10-14 사용자가 별도 검토 에이전트를 명시 허용했다. 원본 영상·운영 DB·참가자 자료·키는 커밋하지 않는다.

## 1 버전 확인

2026-10-14 공식 PyPI/npm registry와 공식 문서에서 최신 안정판·선택 버전·runtime/peer 조건을 확인했다. 새 의존성은 없고, 이번 작업과 무관한 업그레이드는 하지 않는다. 기존 lockfile과 Python 3.14/Node ≥22.12 계약 및 검증된 설치 runtime을 유지한다.

| 라이브러리 | 최신 안정판 | 선택(기존 고정) | registry |
| --- | --- | --- | --- |
| Pydantic | 2.14.1 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/) |
| FastAPI | 0.143.0 | 0.141.1 | [PyPI](https://pypi.org/project/fastapi/) |
| Uvicorn | 0.54.0 | 0.52.4 | [PyPI](https://pypi.org/project/uvicorn/) |
| openpyxl | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/project/openpyxl/) |
| ReportLab | 5.0.1 | 5.0.1 | [PyPI](https://pypi.org/project/reportlab/) |
| Pillow | 12.3.0 | 12.3.0 | [PyPI](https://pypi.org/project/pillow/) |
| cryptography | 50.0.2 | 50.0.2 | [PyPI](https://pypi.org/project/cryptography/) |
| httpx | 0.28.1 | 0.28.1 | [PyPI](https://pypi.org/project/httpx/) |
| pypdf | 6.20.1 | 6.19.0 | [PyPI](https://pypi.org/project/pypdf/) |
| React / React DOM | 19.3.0 | 19.2.8 | [React registry](https://registry.npmjs.org/react/latest), [DOM registry](https://registry.npmjs.org/react-dom/latest) |
| Vite | 8.3.4 | 8.2.2 | [npm registry](https://registry.npmjs.org/vite/latest) |
| TypeScript | 7.0.2 | 7.0.2 | [npm registry](https://registry.npmjs.org/typescript/latest) |
| Playwright | 1.64.0 | 1.63.0 | [npm registry](https://registry.npmjs.org/@playwright/test/latest) |

API·breaking change 확인: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/), [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/), [React reference](https://react.dev/reference/react), [Vite migration](https://vite.dev/guide/migration), [Playwright release notes](https://playwright.dev/docs/release-notes), [Python 3.14 SQLite](https://docs.python.org/3.14/library/sqlite3.html). 선택 API는 기존 모델·hook·시험 API만 사용하며 최신판 전용 기능을 도입하지 않는다. React DOM의 React peer는 같은 19.2.8로 고정되어 있다. Vite의 Node ≥22.12 조건에 현재 Node 24.13.0이 맞으며 Python은 3.14.2다.

## 2 VC01

- 구현: 외부360 종류·metadata·PATCH·보관 전용 분기·변환 도구·전용 시험 제거. `cameraName`은 공통 타입 모듈로 이동. 원본/변환본 부모 hash·불변 파일·판본·실제 업무 행위 검사 유지. `media_status: pending_probe`와 과거 batch의 `conversion_required` JSON 호환 유지.
- 검증: `npm run build` 통과. 변경 관련 backend 85건(53.726초) + uploads23건(6.344초) 통과. E2E `uploads-v4 recording-split-v4 preprocess-v4 recording-v4 scoring-ai-v4 copy-guard scenario-staff` 22건(1.4분) 통과.
- 최초 E2E에서 같은 파일명 과거 카드가 먼저 보여 저장 응답 전 DB를 조회하는 시험 경쟁 조건1건을 확인했다. 연결 POST 응답을 기다리도록 수정하고 위22건 재실행에 통과했다.
- 독립 cold review: P2 1건 수용. SQLite `mode=ro`도 WAL 모드 원본 폴더에 보조 파일을 만들 수 있었다. 원본 DB/WAL의 임시 복사본을 질의하고 전체 복사 전후·질의 후 원본 존재 여부/size/mtime를 비교하도록 수정했다. WAL 최신 committed 행·정상 종료 WAL DB·파일목록/hash 무변경을 포함한4건을 검토자가 독립 재실행해 통과했고 잔여 actionable finding0을 확인했다.
- 운영 점검: 실제 로컬 운영 DB에서 `uv run --locked python -X utf8 -m app.manage check-removed-media`를 수정 전후 실행하여 cases0/receipts0/batches0, total0/exit0 확인. 외부 배포 대상 DB는 제공되지 않았으며 배포 전 같은 명령을 실행해야 한다. 자동 삭제·이관0.
- 제거 검색: 제품·시험·스크립트·현행 운영 문서에서 점검 명령과 그 합성 회귀 외 참조0. 점검은 제거 대상 literal을 읽어야 하므로 계획의 일률적 grep0 조건에서 이 두 파일만 예외로 명시한다. 역사 문서는 보존한다.
- 문서: 개발/운영 안내에서 폐기 경로 제거, 배포 전 점검 명령 기록, 360 계획·archive에 퇴역 이력 연결. 삭제된 도구 링크는 당시 commit 참조로 전환.

최초 전체 명령 `uv run --locked python -X utf8 -m unittest discover -s tests -v`는 시험 모듈을 먼저 로드하여, 작업 중 제거한 benchmark의 폐기 단언1건이 남아 오류였다(771건/1514.030초, 역사 원본2건 skip). 현재 파일의 관련85건 재검증에서 수정 확인 뒤 최종 전체를 다시 검증했다. 모든 `tests/test_*.py` 모듈을 정렬해 `modules[i::4]`로4묶음에 배분하고 각 묶음을 `python -X utf8 -m unittest -v tests.<module> ...`로 실행했다. 147/287/155/186건, 각262.064/453.516/702.282/354.406초, **합계775건 오류·실패0**이며 역사 v3 원본 미보유2건만 skip이다. INSV/360 skip은 없다. `git diff --check`·현재 graph `graft check` 통과, 변경 문서10개의 상대 링크 깨짐0.

PR [#100](https://github.com/syleeVeluga/k-dog-proj/pull/100), 구현 commit `6814723`, 병합 commit `0cae5d3` (2026-10-14) 원격·로컬 main 반영 완료.

## 3 VC02

- 구현: backend/UI 기본 우선순위 CAM1~CAM4, `N_CAMk_설명`/`CAMk_설명` 파일명 제안, CAM4 원본 번호 없음 안내. 기존 원본1/3/2 규칙·서버 대응 유지. 고객 원본 카탈로그·CAMERA_ORIGINALS 변경0, 카메라 수 강제0.
- 검증: 변경 관련 backend39건(49.137초) 통과. 4대 등록과 무음 MKV에서 원본/AI 1fps 클립4개, 오디오 사유와 대표 오디오 선택을 확인했다. `npm run build`, 관련 E2E15건(54.7초) 통과. 최초 E2E의 잘못된 caption locator1건은 table의 접근성 이름으로 정정했다.
- 독립 cold review: actionable finding0. 회차 접두어 뒤 설명 없는 이름도 제안하는 비결함 권고1건을 수용하여 계획의 정규식과 정확히 일치시켰다. `6_CAM1.mkv` 제외 회귀 추가, build·순수 파일명2건 재검증 통과. 검토자가 작은 수정 재검토에서 잔여 결함0 확인.
- 엄밀한 패턴 적용 후 E2E15건(54.8초) 재실행 통과. 개인정보 없는 합성 [CAM4 등록 카드](vc02-four-camera-uploads.png)와 [4대 기본 우선순위](vc02-four-camera-priority.png)를 직접 시각 확인했다. 최종 전체 backend는 모든 시험 모듈4묶음에서147/289/155/186건, 각291.067/462.791/676.385/364.623초, **합계777건 오류·실패0**(역사 v3 원본 미보유2건 skip) 통과. `git diff --check`·상대 링크·graph 동기화 확인 통과. 새 의존성0; §1의 2026-10-14 버전 확인과 고정 lockfile 유지.

PR [#101](https://github.com/syleeVeluga/k-dog-proj/pull/101), 구현 commit `918c06a`, 병합 commit `45b0f7c` (2026-10-14) 원격·로컬 main 반영 완료.

## 4 VC03

- 구현: `segmentsCsv.ts`의 열 이름 기반 UTF-8/BOM·따옴표 CSV 파서, 촬영 기록의 실제8구간 섹션에서 초안 채우기. 다음 번호의 시작으로 끝을 유도하고 퇴장 끝은 null. 연결 카메라의 평균 offset(3자리)과 편차·파일명/hash/계산 열 근거를 채워 확인 체크박스를 선택한다. 파일은 서버에 보내지 않는다.
- 누락·기존 미실시·수동 걷기 국면/사건/관찰/꼬리 기록을 보존한다. 형식 오류와 읽기 중 대상/기준/입력 변경 시 초안에 적용하지 않는다. 기록은 수정 초안으로 바꾸고 기존 PUT·길이/hash·확정 검증을 유지한다. backend 변경0, 새 의존성0; §1의 확인일/고정 버전을 유지.
- 검증: `npm run build`, `npm run test:e2e -- segments-csv recording-v4 copy-guard` **14건(44.0초) 통과**. 샘플8구간·끝7개/null, CAM1 기준 offset +0.069/−0.118/−0.016, CAM3 기준, BOM·열 순서·추가 열·누락·중단·이름·편차·따옴표·형식 오류6건을 확인했다. 4영상 E2E는 hash 중복 방지, 초안 저장200, 걷기 국면 빈 확정422, 수동6국면·미접촉 사건 입력 뒤 확정200, 기준 변경·오류 무적용·미실시 보존을 확인했다.
- 최초 E2E의 textarea 정확한 label 조회와 중첩 `has` screenshot locator2건을 역할 이름·상대 선택자로 정정했다. 미실시 경고의 조사 오류는 「구간은」으로 수정했다. 위 최종14건 재실행 통과. 이전 전체 backend777건을 재실행했다고 주장하지 않으며 최종 통합 전체는 VC04에서 실행한다.
- 독립 cold review: actionable finding0, 수용 수정0. 검토자가 sample fixture와 원본 CSV의 SHA-256 일치를 확인했다. [CSV 초안 화면](vc03-segments-csv-draft.png)은 합성 영상·짧은 CSV만 사용한다.

PR [#102](https://github.com/syleeVeluga/k-dog-proj/pull/102), 구현 commit `85f3aa7`, 병합 commit `e1228af` (2026-10-14) 원격·로컬 main 반영 완료.

## 5 VC04

- 구현: ZIP의 운영 문서 목록에 커밋된 샘플 CSV와 VC02/VC03/VC04 PNG를 포함한다. 첫 inventory에서 CSV의 실제 폴더와 목록 경로 불일치를 발견해 수정했다(`ee6184d` → `afeeed3`). 제품·채점·서버 계약/의존성 변경0. 원본 MKV와 폐기 도구는 포함하지 않는다.
- 전체 backend: §2의4묶음에서147/289/155/186건, 각329.005/516.144/985.018/406.171초, **합계777건 실패·오류0**(역사 v3 원본 미보유2건 skip). 마지막 PNG 목록 보완 뒤 패키징20건/25.152초 재검증 통과.
- S1: `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`의8개 카탈로그·규칙·mapping 통과. G01/G04 미수령 workbook·Excel 활성화 후속은 유지한다.
- frontend: `npm ci`, `npm run build`, 전체 `npm run test:e2e` **139건/12.4분 통과**. 최초는138건 통과·기존 느린 POST의 조회 종료 단언1건 실패(기대5/실제6,14.4분). 코드 변경 없이 단독1건/17.1초와 최종 전체139건에 통과했다. 기존500kB 번들 경고는 유지한다.
- 기존 개발 간접 의존성 source-map-js 1.2.1은 `npm ci`/`npm audit --json`의 high1건이다. [보안 공지](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)의 수정판은1.2.2. `npm audit --omit=dev --json`은0건이며 개발 도구 업그레이드는 별도 후속으로 남긴다.
- 브라우저 인수는 webapp-testing 스킬의 기존 Python Playwright1.63.0/Chromium을 사용했다. FFmpeg는 2026-10-14 [공식 릴리스](https://ffmpeg.org/download.html)의 최신9.0.2 확인. 기존 portable9.0.2 봉인 빌드/source/license, 개발 PATH8.1.1과 PTS 보존 API를 유지하고 이번 범위 밖 runtime 업그레이드를 하지 않았다.
- 독립 cold review: actionable finding0·수용 수정0. 검토자가 두 checked ZIP의 CSV/PNG·manifest hash·원본 제외,777/139/20건 로그, 실제4클립·무음 증거를 대조했다. 최종 문서·새 PNG 커밋 뒤 ZIP 재빌드·설치 검증은 최종 패키지 기록으로 닫는다.
- 문서: DEVELOPMENT4대/MKV/CSV 모듈·시험, PILOT CSV·수동 남은 항목·offset 확인 해제·음성 카메라·AI 예산, 후속 대장 E01 종료·P01 고객 확인 대기를 갱신했다. `git diff --check`,9문서 상대 링크143개 통과. 문서 재검토의 링크 수 정정1건(141→143)을 수용했다. `graft build`는3521 wiring nodes/10306 edges를 생성해 wiring 동기화를 확인했다. meaning tier0%/manifest 없음은 기존 상태이며 의미 요약 완료로 주장하지 않는다.

### 실제 파일 기술 인수

`app.manage --data-dir <새 임시 시험 저장소> serve --port 8000`과 Chromium으로 실제4 MKV 업로드 → 카메라 제안 → 참가자/회차 연결 → CAM1 기준 CSV → 초안 저장 → 기존 확정 검증 → 새 클립 전처리 → 결과 화면을 실행했다. 운영 DB는 사용하지 않았다. CAM1/1·CAM2/3·CAM3/2·CAM4/null 연결과 원수령4파일의 SHA-256/bytes = 현재 파일 = batch source_files 일치를 확인했다.

CSV 원수령은860bytes/CRLF/SHA-256 `7334c82a536fb5be82d6dc5799005b21bc2e91edb0d5710e4fcccfd9c91bf031`. Git 줄바꿈 정규화 후 커밋·fixture·이번 실제 가져오기는851bytes/LF/SHA-256 `f8baaddca93d2a11f3d8e67e650b1ceae98dff9917ff72776660419e9fa13aeb`로 동일하다. BOM·열·8행 수치는 보존됐다. 시작은10.356/51.146/90.822/171.940/188.328/214.116/250.732/299.898초, offset은CAM2 +0.069/CAM3 −0.118/CAM4 −0.016초다.

**기술 fixture의 한계:** CSV가 제공하지 않는 걷기6국면과 퇴장 끝은 임시 시험 기록에만 명시한 합성 입력이다(걷기 경계214.116/221/226.5/233/238.5/246/250.732, 퇴장 끝320초). 실제 행동 관찰·채점·절차 적합성의 실측 근거가 아니다. 걷기 국면 빈 확정422, 수동 fixture 뒤 확정200을 확인했다. 사건·관찰 근거·꼬리 입력은 발명하지 않았으며 관찰 미확인을 유지했다. 외부 AI·실제 채점0건이다.

| 확인 | 결과 |
| --- | --- |
| 업로드 | 4개/합계1,339,460,190bytes,12.043초 |
| 전처리 | 1080.781초, batch complete, CAM1~CAM4 원본 FPS·AI용 클립 모두 완성 |
| 프레임 | CAM1/2/3/4 원본9289/9290/9289/9289개, AI용 각310개 |
| 무음 | 클립8개 audio_ranges 없음. 영상 범위18창×4대=72view 전부 audio_absent_or_unavailable. 전체31창 대표 오디오 null/no_usable_audio/가용0초. 근거 없는13창은 기존 미관찰 상태 유지 |
| 원본 미리보기 | Chromium CAM1 readyState4,336.9초,1920×1080,error null. pageerror0 |
| 시간 범위 | 현재 Windows/i7-11700KF8core16thread/Python3.14.2/Node24.13.0/PATH FFmpeg8.1.1. 다른 회귀와 동시 실행한1회 기술 인수이며 전용 성능 실측·현장/다른PC 결과 아님 |

[실제 파일 무음 결과](vc04-actual-audio.png)는 숫자·파일명·관찰 미확인만 보여 개인 영상 픽셀이 없고 직접 시각 확인했다. 인수 보조 스크립트의 import 경로·기본URL·CSP 문자열 평가·문구 locator 오류는 정정 후 재확인했다. 잘못 시작한 빈 시험 폴더는 생성 시각과 users/cases/receipts/runs0을 확인해 정리했다. 종료 뒤8000포트 해제를 확인했다.

### 패키지·배포 전 점검

`build_release.py` portable/online → `verify_release.py`는 새 설치/손상 거절/로그인/접수/재시작/감독 종료, portable의 봉인·틀린 키/변조 거절·계정/자료 보존·재설치를 통과했다. CSV 경로 수정 commit `afeeed3`의 두 checked ZIP은 CSV·화면3개의 포함/hash와 원본/폐기 도구 제외를 확인했고 portable 설치를 재검증했다.

최종 검증 ZIP은 commit `5ea84d2d904a9aa716ce578ddc27f73258ec170f`의 깨끗한 작업 트리에서 생성했다. 문서·CSV·화면4개의8개 파일은 이 commit의 바이트 및 manifest hash와 일치하고, 원본 MKV/INSV·폐기 도구 미포함을 재확인했다. 두 ZIP의 `verify_release.py`가 모두 통과했으며 외부 AI0건, 현재 호스트 새 설치/재시작 검증이다. 이후 commit은 검증 결과·문서 숫자·병합 상태 기록만 갱신한다. 깨끗한 OS·물리 다른PC는 별도 후속이다.

| 인수 ZIP(임시 시험 산출물) | bytes | SHA-256 |
| --- | --- | --- |
| kdog-vc04-portable-final.zip | 76075190 | `202b11b5a23c39806e946ed15d68e466f518a7b6af70780a8e699d64abdbecf4` |
| kdog-vc04-online-final.zip | 3245571 | `2f11e31d26cd9ca6ead59c4c6451e8b0ef326fb952769610ba5ed8d9711102d1` |

폐기 검색은 inventory 명령과 그 회귀2파일의6 literal만 남는다(§2의 명시 예외). 현행 실행 경로 참조0. 실제 로컬 운영 DB `app.manage check-removed-media`는 인수 전후 cases0/receipts0/batches0,total0/exit0. 외부 배포 DB는 미제공이므로 배포 전 동일 점검을 실행한다. 자동 삭제·이관0.

PR [#103](https://github.com/syleeVeluga/k-dog-proj/pull/103), 구현 `ee6184d`·`afeeed3`, 패키지 검증 snapshot `5ea84d2`, 최종 기록 `47fad9d`, 병합 commit `73023b1` (2026-10-14) 원격·로컬 main 반영 완료.

병합 후 마감 문서3개의 상태를 실제 PR 결과로 갱신했다.9문서 상대 링크143개·`git diff --check` 통과, 별도 독립 cold review actionable0·수용 수정0. 제품 코드·검증 ZIP snapshot은 변경하지 않았다.

## 6 후속 범위

고객 사양·카탈로그 변경, 실제 공급자 품질, 물리3PC, 음성 녹음 카메라와 4대 배치의 고객 확인은 이번 구현 완료와 별도다. 실제 AI 호출은 이번 인수에서 수행하지 않았다. 기존 개발 도구 source-map-js 보완도 별도 후속이다.
