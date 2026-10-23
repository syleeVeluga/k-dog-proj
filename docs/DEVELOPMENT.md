# K-DOG 개발 실행 안내

버전: v1.8 · 2026-10-20 · S1.1 / 통합명세 v1.3

개발 기준은 [S00–S17 계획](archive/개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md), 검증 근거는 [실행 기록](archive/개발반영_20261003/K-DOG_구현실행기록_v1.0_20261003.md)과 [인수 대장](archive/개발반영_20261003/K-DOG_인수검증대장_v1.0_20261003.md)을 따른다. 실제 영상·장비 검증과 미확정 자료/정책은 [후속 대장](archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)에 있다.

## 환경과 실행

macOS 사용자 설치형은 `uv run --project backend --locked python scripts/build_release.py releases/kdog-s1-macos-online.zip --variant macos-online`으로 빌드한다. 깨끗한 커밋 트리와 기존 frontend 의존성이 필요하다. [macOS 설치 안내](../scripts/macos/online/macOS_설치안내.md), [구현·검증 기록](plans/K-DOG_macOS사용자설치형_v1.0_20261021.md)을 따른다. Windows 배포 두 종류와 별도이며 macOS 포터블은 만들지 않는다.

React 빌드를 FastAPI가 제공하고 SQLite·불변 파일·별도 worker를 사용한다. Python 3.14, Node.js 24, uv, npm, FFmpeg/ffprobe가 필요하다. 패키지 버전은 lockfile에 고정하며 공식 최신/선택 버전·호환성·확인일은 실행 기록에 남긴다. 새 의존성 사용 전 공식 문서와 registry를 확인한다.

저장소 루트에서 처음 한 번 실행한다.

```powershell
cd frontend
npm ci
npm run build
cd ../backend
uv sync --locked
uv run --locked python -X utf8 -m app.manage create-user manager --role operator
uv run --locked python -X utf8 -m app.launcher
```

계정 비밀번호는 숨김 프롬프트로 입력한다. 기본 계정은 없다. 런처가 API와 worker를 함께 시작하므로 별도 worker를 중복 실행하지 않는다. 기본 주소는 `http://127.0.0.1:8000`, 자료는 `%LOCALAPPDATA%/K-DOG/data`다. 코드 저장소 내부의 데이터 경로는 거절한다. 기존 자료는 [운영 안내](PILOT_OPERATIONS.md)의 명시 초기화 후 실행한다. 키가 없으면 AI 요청이 실패하며 가상 결과로 자동 전환하지 않는다.

## Gemini 주키·예비키

같은 Windows 실행 계정으로 개발자 계정에 로그인해 「개발 설정 → 공급자 키 관리 → Gemini」의 두 슬롯을 등록한다. 기존 Gemini 키/환경 변수는 주키다. 각 연결 시험은 선택 키의 모델 목록만 조회하며 자동 전환이나 모델 품질 검증을 수행하지 않는다. 원격 접속은 [HTTPS 운영](PILOT_OPERATIONS.md#중앙-서버와-촬영-pc3대)을 따른다.

새 실행은 주키부터 시작한다. 주키의 로컬 미가용 또는 정규화된 인증·권한·결제·요청 제한·공급자 일시 장애/연결 유실/처리 timeout에서 가용 예비키로 전환한다. 일반 입력/스키마·근거·guard 실패나 원격 정리만 실패한 경우는 전환하지 않는다. 외부 실패 뒤 전환은 새 attempt/호출 예약을 사용하며 Retry-After와 기존 전체 시도·호출 상한을 공유한다. 같은 run은 예비키를 유지하고 다음 run은 다시 주키부터 시작한다. 같은 프로젝트 키 둘은 할당량을 공유하므로 독립 복구가 보장되지 않는다.

슬롯 제거는 해당 키만 제거한다. 「Gemini 전체 키 사용 중지」는 다음 시도에서 두 슬롯을 막으며 이미 요청한 원격 작업의 취소나 공급자 콘솔 키 폐기와는 별도다. 백업에는 두 ciphertext와 세션이 없고 복원 뒤에는 두 슬롯을 명시 재등록한다. 원격 임시 파일 정리는 당시 활성 reference와 같은 키만 사용한다. 교체/제거된 키의 정리 대기는 새 키로 추정 정리하지 않는다. 비용/응답 미확인은 0원이나 성공으로 바꾸지 않는다.

실제 Worker+fake REST의 채점·애착·최종본·문장·HTML/PDF·재사용·복원 검증은 [GK01~04 실행 기록](plans/Gemini주키예비키_20261013/K-DOG_Gemini주키예비키구현실행기록_v1.0_20261013.md)에 있다. 실공급자 프로젝트별 전환·계량·모델 품질/교수·현장 실측은 별도 인수다.

## 자동 검증

```powershell
# backend/에서 실행
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check
# frontend/에서 실행
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

브라우저 시험은 8765 포트의 임시 S1 서버와 저장소 밖 합성 자료를 사용한다. `npm run test:e2e` 한 번으로 현행 제품 전체를 실행하며 판본 환경변수나 구판 UI 실행은 필요하지 않다. 공통 권한·보안·대상 맥락·미저장 입력·새로고침·모바일·키·백업 보호를 S1 fixture에서 검사한다. UI 개편(2026-10-11)의 화면 문구 점검(`copy-guard.spec.ts`: 운영자·교수·관리자 메뉴에 개발 코드·UUID·64자리 해시가 기본 노출되지 않는지)과 공통 계정 합성 현장 시나리오(`scenario-staff.spec.ts`, `scenario-professor.spec.ts`: 외부 요청 0건 확인 포함)도 같은 명령에 포함된다. 교체된 구판 UI 시험의 대응 관계는 [S15 기록](archive/개발반영_20261003/K-DOG_PR-S15_배포와통합인수_v1.0_20261003.md)에 있으며 역사적 API fixture는 backend에 보존한다. 임시 자료와 백업은 같은 임시 상위 폴더에 격리하고 screenshot은 무시되는 `frontend/test-results/`에 둔다.

저장소 루트에서 `git diff --check`, 문서 링크·원본 hash 검사, `graft build` 후 `graft check`도 수행한다. source 탐색/호출 관계는 graft를 먼저 사용한다.

## 원본과 현행 계약

S1 고객 원본은 로컬 전용 `docs/요구사항_20261003/`이다. [원본 목록](archive/개발반영_20261003/K-DOG_원본자료목록_v1.0_20261003.md)의 hash와 일치해야 한다. `app.import_catalogs --spec 20261002 --check`는 통합명세/계산 원본에서 S1의 8개 추출 자산을 대조한다. `--spec`의 기본값도 `20261002`이며 `app.import_catalogs_v4`에는 실행 CLI가 없다. 원본 재추출은 검토한 경우에만 `--check` 없이 실행한다. 참가자 응답·영상·빈양식 미수령분을 임의로 만들지 않는다.

`domain/*_v4.py`가 S1 계약이며 `intake-4.0`, `catalog-20261002-s1.1`을 사용한다. 행동 카탈로그 90행은 직접 수치 83·자동 4·메모 3으로 구분하고 `개59` 추가 메모를 수치 분모에 넣지 않는다. 설문 원문 Q01–Q28의 28문항을 보존하며 Q26–Q28 감정의 일관성 문항의 역채점도 반영한다. 원척도·역채점·결측 정책은 S1 설문 정책 자산을 따른다. strict 모델 검사와 출처·카탈로그·관찰창·권한의 문맥 검증을 함께 수행한다.

`docs/큐브전달_20260929/`의 역사 원본15개는 2026-10-04 저장소에서 삭제하고 로컬 전용으로 제외했다. 이전 근거는 commit `8b9c960`에 남는다. 역사 원본 대조가 필요하면 담당자가 제공한 해시 검증 전달 묶음을 별도 확보하고 `app.import_catalogs --spec 20260929 --customer-dir <로컬_원본_폴더> --check`를 실행한다. `*-v3.json`은 역사 카탈로그와 현재도 쓰는28문항 설문 근거다. 역사 원본이 없으면 원본 의존 시험2개만 명시 skip하며 원본 대조 통과로 표시하지 않는다. v1/v2/v3 코드/자산 중 공통 worker/저장/시험에서 참조하는 것만 남아 있으며 새 제품 쓰기 경로는 S1이다. 이 값들을 S1 기대값으로 사용하지 않는다. G01 빈 채점양식과 G04 정정 원본 확인 전 실제 S1 Excel 점수 가져오기는 비활성이다. 검수 참고파일 등록은 점수 가져오기와 별개다.

## 행사 신청 설문 가져오기(2026-10-22)

「일괄 등록 (CSV·Excel)」에서 2026 K-DOG FESTIVAL 체험 신청 응답 XLSX/CSV를 그대로 올릴 수 있다. 영역마다 다시 시작하는 문항 번호는 원문으로 Q01~Q28에 연결하고 한글 응답 라벨을 자동 제안한다. 접수 정보 8열도 연결하며 나이의 개월 원문은 출처에 보존하고 화면에는 정수 연수를 사용한다. 연락처·동의·중성화 여부·희망 일시는 원자료에 보존하고 희망 시간을 확정 예약으로 쓰지 않는다. 설문 응답 시트를 선택하고 미리보기를 확인한 뒤 확정한다. 원본에 참가자 ID가 없어 재업로드 시 새 ID로 중복될 수 있으므로 기존 참가자는 명시적으로 연결한다. [연결 규칙·검증 기록](plans/K-DOG_행사신청설문반영_v1.0_20261022.md)을 따른다.

## 문항 매핑과 누적 비교(2026-10-21)

[문항 매핑과 누적 비교 계획](plans/누적비교반영_20261021/K-DOG_문항매핑과누적비교적용계획_v1.0_20261021.md)의 CM01~CM05 구현이다. `resources/report/survey-comparison-20261008.json`(EXT1.1)은 28문항을 S01~S09 9지표로 묶고 SF=S03(s10·s11), NF=S04(s12~s14)만 미국 연구 참고값(SF 0.66/SD0.91/n42,926, NF 1.03/SD0.78/n42,764, 전체 43,517)에 연결한다. launcher 필수 자산이며 원본 hash·셀 위치·판본 차이를 함께 고정한다. 전달 XLSX는 무시 목록 `/docs/참고자료/`에 로컬 보존하고 커밋하지 않는다.

리포트 발급 화면의 새 발급은 `cumulative: true`로 누적 비교(`report-run-20261021-cm`, `report-presentation-20261021-cm`, `resources/report/presentation-20261021.json`·`templates/report-20261021.*`)를 사용한다. API 요청에서 `cumulative`를 생략하면 기존 rp04 계약으로 발급한다. 접수 시 참여쌍 대표 설문 집합·9지표 정수 분자/분모·지표별 n·SF/NF 외부 기준 정의를 snapshot으로 고정하며 재시도·다운로드는 재집계하지 않는다. 옛 rp04 발급과 옛 자산은 그대로 둔다. 참여쌍 API는 `GET/POST /api/comparisons-s1/pairs`, `POST /api/comparisons-s1/pairs/{pair_id}/submissions`, `POST /api/comparisons-s1/pairs/{pair_id}/state`다.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest tests.test_comparison_mapping_v4 tests.test_comparison_participation_v4 tests.test_cumulative_outputs_v4 tests.test_cumulative_report_v4 tests.test_cumulative_acceptance_v4 -v
# 로컬 전달 XLSX 셀 대조(선택): 기본 위치 docs/참고자료/에 없으면 경로 지정, 둘 다 없으면 해당 1건만 skip
$env:KDOG_COMPARISON_DELIVERY = "D:/로컬/외부연구값_문항대조와출력기준_누적비교반영_20261008.xlsx"
# frontend/ — 전체 npm run test:e2e에 포함
npx playwright test tests/comparison-participation-v4.spec.ts tests/cumulative-comparisons-v4.spec.ts
```

셀 대조 skip은 원본 대조 통과가 아니다. 합성 시험은 운영 DB의 실제 SF/NF 기준 등록·참여쌍 확인을 대신하지 않는다. 운영 절차는 [운영 안내](PILOT_OPERATIONS.md), 실제 결과는 [구현 실행 기록](plans/누적비교반영_20261021/K-DOG_문항매핑과누적비교구현실행기록_v1.0_20261021.md)을 따른다.

## 전처리와 실행

배포 전 제거 대상 영상 점검은 다음 명령으로 수행한다. 원본 DB와 WAL을 임시 폴더로 복사하여 검사하며 운영 자료를 변경하지 않는다. 점검 중 DB가 바뀌면 API·worker를 종료하고 재실행한다. `total: 0`/exit0 확인 뒤 배포한다. 1건 이상이면 case/receipt/batch 식별자만 보고하고, 처리 방법은 사용자가 결정한다. 자동 삭제·이관은 하지 않는다. 이전 앱을 같은 운영 DB에 병행 실행하지 않는다.

```powershell
# backend/; 배포 대상의 실제 데이터 루트를 지정
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" check-removed-media
```

실제 8구간·사건·카메라 offset을 확정하고 명시 요청으로 실행한다. S1은 공통시각과 각 영상 시각, 원본/변환본/AI용 클립을 구분하며 AI용 1fps 실제 프레임 PTS와 hash를 고정한다. 규칙은 `resources/rules/preprocess-v4.json`이다.

기본 카메라 우선순위는 CAM1~CAM4다. MKV는 FFmpeg로 디코드하며 전처리 클립은 MP4로 만든다. `N_CAMk_설명`/`CAMk_설명` 파일명은 촬영 카메라를 제안하고 CAM4의 사양 원본 번호는 null을 유지한다. 프론트엔드 `src/segmentsCsv.ts`는 UTF-8/BOM 구간 CSV를 열 이름으로 읽어 촬영 기록 초안을 채운다. 기준 카메라의 8구간 시작·다음 번호 시작으로 유도한 끝, 연결 카메라 평균 offset과 파일 SHA-256을 기록한다. CSV 입력은 접힌 영역 밖에 표시하며 퇴장 끝과 걷기 국면 시각이 없어도 8구간 기록을 확정할 수 있다. 상세 사건·관찰 근거·꼬리 선택은 선택 입력이며 미확인 정보를 채점 근거로 만들지 않는다. 순수 파서 회귀는 `tests/segments-csv.spec.ts`, 저장·확정은 `tests/recording-v4.spec.ts`를 사용한다. 현행 최종 CSV와 확정 조건은 [최종 CSV 적용 기록](plans/K-DOG_최종CSV촬영입력개선_v1.0_20261023.md), 이전 기술 인수 이력은 [4카메라 실행 기록](plans/4카메라구간CSV전환_20261014/K-DOG_4카메라구간CSV구현실행기록_v1.0_20261014.md)을 따른다.

```powershell
# backend/; 화면에서 확인한 현재 입력 revision과 새 요청 ID를 지정
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" preprocess CASE_ID --actor manager --expected-revision 7 --request-id PREPROCESS-001
```

같은 요청 재시도에는 동일 request ID를 쓴다. 다른 입력·새 처리에는 새 ID와 현재 revision을 쓴다. 성공/실패·원본 부모 hash·실제 fps·출력 hash가 batch에 고정된다. 메뉴 방문이나 입력 저장으로 자동 실행하지 않는다. AI 실행은 현재 모델/설정/예산을 고정하며 실제 공급자 호출과 재시도에는 비용이 발생할 수 있다.

구조 개선 후 촬영 CSV의 순수 초안 병합은 `src/segmentsCsv.ts`의 `applySegmentsCsvDraft`, AI·전처리의 pending/응답 순서·타이머는 `src/useExecutionTracking.ts`에서 찾는다. 각 화면 adapter가 DTO·저장 payload와 부분 조회 결과를 해석한다. backend의 `app.analysis.owned_write`는 현재 실행 점유·실제 계정 확인과 같은 SQLite 쓰기 transaction의 수명을 소유하며, Worker 네 쓰기와 채택·게시 다섯 쓰기가 사용한다. claim·heartbeat·오류 종료·업로드/전처리의 별도 토큰은 기존 module에 남는다. 실제 시험과 한계는 [아키텍처 개선 실행 기록](plans/아키텍처개선_20261020/K-DOG_아키텍처개선실행기록_v1.0_20261020.md)을 따른다.

## 패키지와 종단 리허설

ZIP은 커밋된 깨끗한 작업 트리에서 만든다. S1 카탈로그·계산/문장/비교 규칙·HTML/CSS 템플릿·로컬 폰트, 운영 안내·계획·후속 문서와 실행 런타임을 포함한다. 런타임은 python.org 공식 CPython embeddable(고정 SHA-256, `releases/.cache/`에 보관)에 `uv export --locked --no-dev` 결과를 hash 필수·wheel 전용으로 설치한 `runtime/python`, 그리고 [FFmpeg 최소 빌드](../scripts/ffmpeg/README.md) 결과를 `build.json` 해시로 확인한 `runtime/ffmpeg`다. FFmpeg 빌드 결과가 없거나 해시가 다르면 ZIP을 만들지 않는다. `오픈소스고지.txt`에는 고정 고지문과 동봉한 Python·npm 패키지 목록을 넣는다. 고객 원본·영상·키·런타임 자료와 개발용 시험·빌드·실측 스크립트는 제외한다. 개발 명령과 시험 근거는 `release.json`의 commit에 해당하는 소스 저장소에서 확인한다. `app.launcher.REQUIRED`가 S1 필수 자산을 검사한다.

```powershell
# 저장소 루트; 프로젝트 Python 사용
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py "releases/kdog-s1-windows-x64.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py "releases/kdog-s1-windows-x64.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/issue_release.py "releases/kdog-s1-windows-x64.zip" --customer SCHOOL-1 --developer keyman --expires 2026-12-31
# 사용자 설치형(uv·FFmpeg 직접 설치): 런타임 없이 만들고, PATH에 uv·FFmpeg가 있고 인터넷이 되는 PC에서 검증
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py --variant online "releases/kdog-s1-windows-x64-online.zip"
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py "releases/kdog-s1-windows-x64-online.zip"
# backend/
uv run --locked python -X utf8 ../scripts/rehearsal.py --pairs 2 --seconds 10 --report "D:/tmp/s1-rehearsal.json"
# 자동 구간 실측 (docs/plans/K-DOG_영상자동구간과자동분석계획_v1.0_20261023.md). 정답 MKV는 저장소 제외 대상
# overlay_*: 녹화 자막 전환 읽기(로컬, 비용 없음) / segment_*: Gemini 추정(실제 호출·비용 발생)
uv run --locked python -X utf8 ../scripts/overlay_boundary_spike.py --csv "../docs/plans/확정 영상 및 구분_20261014/segments.csv" --video CAM1 "../docs/plans/확정 영상 및 구분_20261014/5_2_CAM1_복도정면.mkv" --report "D:/tmp/overlay-spike.json"
uv run --locked python -X utf8 ../scripts/segment_boundary_spike.py --csv "../docs/plans/확정 영상 및 구분_20261014/segments.csv" --video CAM2 "../docs/plans/확정 영상 및 구분_20261014/5_2_CAM2_테스트룸_입구.mkv" --report "D:/tmp/segment-spike.json"
```

`verify_release`는 PATH를 Windows 기본 경로로 제한해 uv·Python·FFmpeg가 없는 상태로 현재 Windows의 새 한글/공백 경로에 ZIP을 풀고, `Start.cmd --check`의 손상 거절, 내장 Python·FFmpeg 사용, S1 health·접수·재시작 조회·감독 종료를 검사한다. 이어서 같은 ZIP으로 합성 고객 `VERIFY` 발행 패키지(무작위 비밀번호, developer만, 오늘까지 설치 가능)를 만들어 제품 파일 평문 노출이 없는지, 틀린 키와 헤더·본문 변조·유효 기간 연장·만료 패키지가 아무것도 만들지 않는지, 키 설치·설치 중 첫 업무 계정 입력·바로가기, 그 업무 계정 로그인·접수, 개발자 키 설정 API 접근, 재설치 후 자료·계정 유지와 첫 계정 재질문 없음을 검사한다 (설치 위치·바로가기·자료는 임시 폴더). `issue_release`는 고객별 발행 패키지와 발행 키를 만든다. 사용법과 전달 규칙은 [운영 안내](PILOT_OPERATIONS.md)의 발행 절을 따른다. 패키지 안의 FFmpeg로 전처리 시험을 다시 돌리려면 풀린 `runtime/ffmpeg/bin`을 PATH 맨 앞에 두고 backend 시험을 실행한다. 깨끗한 OS와 물리 PC3대는 별도 실측이다.

`--variant online`은 S15 방식의 사용자 설치형 ZIP이다. `runtime/` 없이 `backend/pyproject.toml`·`backend/uv.lock`과 `scripts/windows/online/`의 `Install.cmd`·`install.ps1`·`Start.cmd`, 사용자 설치형 `오픈소스고지.txt`(글꼴·npm 목록)를 넣고 (npm 라이선스 전문은 `licenses/npm`. 앱은 `runtime/` 폴더가 있으면 내장 FFmpeg만 쓰므로 이 ZIP에는 `runtime/`이 없어야 한다) `release.json`에 `"variant": "online"`을 기록한다. FFmpeg 빌드 결과와 embeddable Python이 필요 없다. `issue_release`는 이 ZIP을 거절한다 (발행은 포터블 ZIP만). `verify_release`는 `variant`를 보고 이 ZIP을 따로 검증한다: 설치 전 `Start.cmd`가 `Install.cmd`를 안내하는지, 손상 시 `.venv`를 만들기 전에 거절하는지, 틀린 `UV_PROJECT_ENVIRONMENT`·`PYTHONHOME`·`PYTHONPATH`를 무시하고 `backend/.venv`(Python 3.14)와 PATH FFmpeg를 쓰는지, 로그인·접수·`Start.cmd` 재시작 조회·감독 종료를 검사한다. 이 검증은 uv·FFmpeg가 PATH에 있고 인터넷(또는 uv 캐시)이 되는 PC에서만 돈다.

리허설은 Forms 접수/설문→3개 독립 촬영 계정 동시 수신→CAM1/2/3 연결→실제 구간/offset 확정→FFmpeg 전처리→독립 사람 원자료→계산/최종결과→실제 HTML/PDF 발급과 hash 고정을 검증한다. 모든 항목의 미관찰 사유가 명시된 합성 시트를 사용하며 실제 행동 점수를 발명하지 않는다. 총 벽시계와 단계별 시간을 분리한다. 기본은 72쌍/45초이며 빈 임시 폴더만 쓴다. 외부 AI 호출은 0건, 논리 클라이언트3개이며 실제 3PC나 1GB 영상 시간의 대체 증거가 아니다.

실측 준비 CLI `scripts/benchmark_s1.py`의 `--template`, `--schema`, `--manifest ... --data-dir ... --actor ... --output ...` 사용은 [S16](archive/개발반영_20261003/K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md)을 따른다. 읽기 전용 집계이며 실제 AI 실행이나 운영 승인 도구가 아니다.
