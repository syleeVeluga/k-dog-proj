# PR-S15 배포와통합인수

버전: v1.0 · 2026-10-03 · 상태: 구현·통합 검증 중 · 선행: S14 · 기준: main 3654596

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 공통 검증·리뷰·버전 확인·저장 보호는 상위 §7을 적용한다.

브랜치 제안: `veluga/s15-s1-release` · 권장 PR 제목: `release: S1 중앙 서버 배포와 통합 인수 검증`

## 문제와 결과

S1 기능을 중앙 서버와 촬영용 3PC에서 설치·사용·복구하고, 최종 명세 T01~T32를 실제 앱 경로로 확인한다. 합성 구조 검수와 참가자 실증은 별도 완료 상태로 남긴다.

근거: 운영 요청 4항, 통합명세 11~12절, 기존 C13의 설치·복구 보호. 직접 선행 S14의 상위 의존성을 포함해 S00~S14가 필요하다.

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `scripts/rehearsal.py`, `scripts/build_release.py`, `scripts/verify_release.py` | 수정 | S1 합성 리허설·자산 포함·깨끗한 패키지 검증 |
| `backend/app/manage.py`, `backend/app/launcher.py` | 필요한 수정 | 중앙 서버/LAN 기동·호환성·필수 자산 점검 |
| `scripts/windows/install.ps1`, `scripts/windows/Start.cmd`, `scripts/windows/Install.cmd` | 필요한 수정 | 실제 중앙 서버 설치와 클라이언트 안내 |
| `backend/tests/test_acceptance_v4.py`, `backend/tests/test_deployment_v4.py` | 신설 | T01~T32·3PC 흐름·장애/복구 |
| `backend/tests/test_packaging.py`, `backend/tests/test_rehearsal.py` | 수정 | 초기화·S1 단일 운영·비밀/실자료 제외 |
| `frontend/tests/operations-v4.spec.ts` | 신설 | 동시 업로드→등록→연결→분석→리포트 |
| `docs/DEVELOPMENT.md`, `docs/PILOT_OPERATIONS.md`, `./README.md`, `./AGENTS.md` | 갱신 | 실제 명령·새 기준·작업 진입점·미검증/보류 기능 |
| 본 폴더 인수 검증 대장 | 갱신 | 실제 결과·근거·판본·차이·미실행 기록 |

## 구현과 리허설 순서

1. 깨끗한 Windows/한글 경로에 실제 ZIP를 설치하고 S1 필수 카탈로그·문장·템플릿·폰트·실행 의존성·초기 DB를 확인한다. 기존 설치 전환은 S01의 결과 초기화·원입력 연결로 검증한다. 원본 참가자 파일·키·런타임 데이터를 ZIP에 넣지 않는다. 대체가 끝난 구판 실행 코드·자산은 import/호출 관계를 확인한 뒤 패키지에서 제거한다.
2. 중앙 서버 한 곳과 촬영 PC3대의 브라우저 연결을 검증한다. LAN 주소·HTTPS public origin·인증·방화벽/프록시·대용량 제한·저장공간을 문서화한다. 서로 독립된 로컬 DB3개를 운영으로 안내하지 않는다.
3. 사전 설문과 현장 설문, 영상 먼저/등록 먼저, 3PC 동시 수신, 잘못 연결한 대상 정정, 메인 PC 분석·조회·인쇄의 작업 순서를 실제 화면으로 수행한다.
4. T01~T32 각각 입력/기대/실제/판정/차이/앱·모델·프롬프트·기준 버전을 기록한다. 미확정 제안은 확정 기능 시험 대신 미확정 상태 유지 시험으로 기록한다.
5. 종료·재시작·전원/네트워크 중단·디스크 부족·worker 점유 만료·입력 변경·삭제·동의 철회에서 수신물/분석/리포트의 원자성과 복구를 확인한다.
6. 초기화 이후 S1 백업/복원은 미연결 수신물부터 원본·변환본·batch·시트·의견·출력·export까지 포함한다. 이전 S1 백업을 복원할 때 최신 삭제 이력을 다시 적용한다. 초기화 전 구판 백업의 점수 복원은 지원하지 않는다.
7. 기존 앱 점수·결과가 제거됐고 원입력은 유지됐는지, 새 접수·채점·출력이 S1만 사용하는지 검증한다. 초기화 재실행이 새 S1 결과를 지우지 않고 옛 worker 응답이 점수를 되살리지 않아야 한다. S1 불변 출력·미지원 판본 쓰기 차단과 운영 개시/복구 절차를 기록한다.
8. 완료 상태를 ‘코드/합성 통합’, ‘실제 LAN/설치’, ‘실제 참가자 품질/시간’, ‘외부 비교 승인’으로 구분한다. 실제 장비/자료가 없으면 해당 인수는 미실행이며 운영 검수 완료라고 쓰지 않는다.

## 검증과 완료 조건

- backend 전체 시험·S1 원본 검사·frontend build와 전체 e2e·공백 검사가 통과한다. 구판 점수 조회/실행 호환 시험은 요구하지 않으며 공통 보호장치 회귀는 유지한다.
- T01~T32의 각 행에 실제 결과 또는 명확한 미실행/정책 대기 사유와 담당 PR가 있다.
- 제공 리포트 형식의 PDF 전 페이지·HTML 모바일/오프라인/인쇄를 시각 확인한다.
- 3PC 동시 업로드 충돌이 재전송 없이 복구되고 권한·사례 맥락이 유지된다.
- ZIP 새 설치·기존 결과 초기화·재시작·S1 백업/복원·삭제 이력이 검증된다. 제거한 구판 점수를 다시 불러오는 롤백 경로는 안내하지 않는다.
- 미수령 G01/영상·미승인 D/G 항목은 해당 기능만 비활성/보류로 표시하고 나머지 사용 범위를 운영 안내에 기록한다.

## 인계와 완료 경계

구조 구현 PR는 합성 통합 결과와 보류 목록을 갖춰 병합할 수 있다. **현장 운영 인수는 실제 3PC/설치 검수까지 별도 확인**하며 S16 정확도/시간과 S17 외부 비교가 끝난 것으로 표시하지 않는다. 이번 계획 작성 시에는 어떠한 체크도 통과 처리하지 않는다.

## 구현 및 검증 기록

- [ ] 구현·변경 파일 및 commit/PR 기록
- [ ] 명세 기대값과 실제 시험 결과·미실행 사유 기록
- [ ] 라이브러리/API 최신·선택 버전·확인일·근거 기록
- [ ] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [ ] 남은 D/G 확인, 활성/보류 기능, 다음 PR 인계 기록

### 2026-10-04 구현·cold review·로컬 전환

- 기본 실행은 S1이다. CLI `preprocess`는 명시 request ID/expected revision과 `preprocess_v4`를 사용한다. 실제 저장된 AI run kind `s1`을 worker 시작과 초기화 제외 목록에 일치시켜 재시작이 차단되거나 새 S1 실행이 구판으로 제거되지 않게 했다. `test_deployment_v4`의 실제 subprocess·최초/반복 초기화와 `test_preprocess_v4`의 실제 CLI/응답 재시도 회귀를 추가했다.
- `scripts/rehearsal.py`는 빈 합성 자료 폴더에서 Forms→3개 별도 촬영 계정 동시 수신→CAM1/2/3 연결→실제 구간/offset→FFmpeg→독립 사람 시트→계산/최종→실제 HTML/PDF 발급을 검사한다. 원본/클립/고정 최종 hash, 총 벽시계/단계 시간을 기록한다. 2쌍 리허설·빈폴더 보호·필수자산 시험3개(35.182초), 별도 1쌍10초 CLI(13.001초)를 통과했다. 외부 AI0건이며 물리3PC·대용량 실측과 구분한다.
- `launcher.REQUIRED`를 S1 필수 자산으로 변경하고 패키지에 오프라인 HTML/CSS를 포함한다. graft caller와 실제 startup 파일 접근을 대조하여 제품에서 쓰지 않는 v1/v2 행동/설문 일부·pending/preprocess-v1·v3 mapping 7개와 구 export/개발자 sample 모듈2개를 ZIP 대상에서 제외했다. 공통 Worker/Store/API import에서 필요한 역사 자산은 보존한다.
- cold review P1: 기존 `/imports` 경로가 오류행을 버리고 정상행만 등록하여 S02 원본 보존을 우회했다. S1에서 구 경로를 종료하고 App/설문 진입을 FormsImporter로 통합했다. cold review P2: 구 개발자 설정 draft/activate가 남아 있었다. S1에서 종료하고 키 상태 GET만 남겼다. HTTP/패키지/역사적 명시 fixture5개(4.840초), 실제 브라우저 importer-v4/retirement-v4/settings3개(11.2초), build를 통과했다.
- cold review P1: 참가자 ID 수정 뒤 삭제하면 과거 ID의 백업에서 동일 사례가 되살아났다. 삭제 tombstone의 안정 case_id를 복원에 다시 적용하고 반복 복원에서도 보존했다. `test_deletion_restore_v4`는 정리 전/후 두 경로와 이중 복원을 검증한다. S14 참고 source hash 폐쇄와 함께 독립21개(36.258초) 통과했다.
- 실제 로컬 운영 자료: 원 DB 보존본과 사전 검증 백업152파일을 만들고 승인된 S1 초기화를 적용했다. 참가자2·계정2, 원입력2·영상참조6의 hash를 보존했고 구판 run9/step111을 제거했다. 새 점수/기본결과는0건, 원격 정리 대기0건이다. 초기화 반복 complete, 사후 백업14파일, 별도 새 폴더 복원13참조, 초기화 이전 백업409거절을 확인했다. 보호된 운영 폴더의 상세 증거는 저장소에 넣지 않는다.
- 원본 검사: `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`로 S1 8개 추출 자산, `--spec 20260929 --check`로 역사 v3 6개 자산을 실제 대조했다. `app.import_catalogs_v4`는 CLI가 아니므로 해당 모듈 직접 실행의 성공 종료를 검증 근거로 쓰지 않는다. G01/G04 미수령과 Excel 점수 import 비활성은 유지한다.
- 첫 전체 backend643개(883.082초)에서 구 route substring 및 구판 전처리 CLI 인자 시험2개가 실패했다. 현행 경계에 맞춰 정정했고 intake23개(50.717초)·구판 CLI 거절/실제 S1 CLI2개(11.553초)를 통과했다. 추가 변경을 포함한 전체 회귀를 다시 실행 중이며 실패를 통과로 덮어 기록하지 않는다.
- 새 의존성/lock 변경 없음. 2026-10-04 공식 확인: [React](https://react.dev/versions) 최신19.3.0/선택19.2.8, [Playwright](https://playwright.dev/docs/release-notes) 최신·선택1.63.0, [FastAPI](https://pypi.org/project/fastapi/) 최신0.142.2/선택0.141.1. 관련 없는 업그레이드를 제외하고 기존 잠금 API를 build/HTTP/브라우저로 확인했다.

실제 새 ZIP·최종 전체 회귀·S1 UI 공통 보호 시험의 통합 결과는 아래에 추가한다. 깨끗한 OS·실제 LAN/3PC·실제 영상 품질·시간은 후속 대장 E01–E10의 별도 상태다.


### S1 제품 브라우저 회귀 전환

`backend/tests/browser_server.py`는 제품 기본 `create_app`의 S1을 사용한다. 판본 환경변수와 edition skip을 제거하여 `frontend/`의 `npm run test:e2e` 한 번으로 현행 제품 전체를 실행한다. 서버·백업은 저장소 밖 같은 임시 상위 폴더에 격리하며 worker와 실제 공급자는 실행하지 않는다. 역사적 API fixture는 backend에 유지한다.

| 교체된 UI 시험 | 현행 S1 대응 시험과 유지한 보호 행동 |
| --- | --- |
| `importer.spec.ts` | `importer-v4.spec.ts`의 CSV/XLSX 각각 실제 시트·열 선택, 원라벨 검증, 동명이인 별도 ID, 전체 확정 원자성, 재시도 멱등, 명시 기존 회차 연결·revision 충돌. `intake.spec.ts`의 360px 중복행·수정 후 확정도 유지. |
| `recording.spec.ts`, `recording-v3.spec.ts` | `recording-v4.spec.ts`의 실제 합성 FFmpeg 영상·8구간/6국면·사건·offset·관찰 근거, 확정 잠금, 동시 변경 뒤 draft 보존/409, 새 회차 원자료 분리, 외부 회차 변경 시 이동 취소, reviewer 읽기 전용. `uploads-v4.spec.ts`의 묶음 부분 실패·응답 유실 후 동일 수신물 재사용, 3브라우저 연결 충돌·재접속·완료 파일 재전송 금지. |
| `preprocess.spec.ts`, `preprocess-v3.spec.ts` | `preprocess-v4.spec.ts`의 실제 3CAM 합성 클립·원본/AI 프레임·연속 오디오, 미확인 offset 제외·가림/신체/오디오 구별, 명시 재사용과 새 재시도, immutable batch, 입력 충돌·이전 입력 표시, 진행/실패/중단/조회 실패 및 reviewer 권한. |
| `survey.spec.ts`, `survey-v3.spec.ts` | `survey-v4.spec.ts`, `guidance.spec.ts`, `intake.spec.ts`의 28 원응답, 정상0·빈칸과 사유·역채점·원척도, 확정 결측과 D05 보류 구별, 임의 총점 금지, Forms 등록, 360px·reviewer 조회. 구판 부분평균/NA 기대값은 S1 정답으로 복사하지 않음. |
| `scoring-v3.spec.ts` | `scoring-v4.spec.ts`의 고정 입력·원코드, 0/음수/null 및 근거, 사람 독립 배정·제출 잠금, 실제 공개 전 접근 금지, 공개 후 review·최초 제출 보존, 동시 저장 충돌·보존본 읽기 전용. |
| `scoring-ai-v3.spec.ts` | `scoring-ai-v4.spec.ts`의 설정 불변 판본·명시 원관찰 범위·스키마 검증, 예정42호출·D04 대기, 실행/중지/재시도/재사용·부분실패·불명 과금, 권한 및 공개 철회. 실제 공급자 호출0. |
| `judgements-v3.spec.ts` | `judgements-v4.spec.ts`의 입력 고정·청취/발성량·자동 계산/사람 판단 분리·근거/반대근거·보류·동시 수정·보존판본. S1 계산식은 backend 원문 시험으로 별도 검증. |

공통 `context/guidance/integrity/notifications/intake` 5파일은 S1 fixture로 옮겨 72명 목록과 행사/참가자/회차 맥락, 미저장 입력, 목록 연결·손상자료 구별, 화면 내 알림, 등록/새로고침/모바일, 개발자 자료 차단·reviewer 쓰기 차단을 유지한다. `settings.spec.ts`의 실제 키 저장/폐기·화면/브라우저 저장소 비노출과 가짜 연결 응답은 그대로 유지한다. 새 `operations-v4.spec.ts`는 관리자 계정 생성/철회·열린 세션 만료·실제 임시 S1 HTTP 백업·전체 파일 hash/로그인 세션 제외·백업 상태/권한을 검사한다. 복원 자체는 종료가 필요한 CLI/backend 통합 시험의 범위다.

브라우저 전환의 대상 실행 결과와 최종 전체 실행 결과는 검증을 마친 뒤 이어 기록한다. 단순 skip을 통과로 계산하지 않는다.


- S1 브라우저 전환 보강9개는 모두 통과 근거를 확보했다. 최초 실행에서 Forms CSV/XLSX·빈 채점·보존 영상·설문·부분 실패 수신6개, 명시 기준영상 선택과 고유 수신물 선택/재시도 응답 확인 뒤 기록2·수신2개(41.7초), 운영 백업1개(16.0초)를 확인했다. 운영 시험은 실제 201 생성 응답, S1 입력 보존, 백업 전 파일 SHA-256 대조, 로그인 세션0, 직원 철회·권한·360px까지 검사한다. 로그인 완료 대기와 backup API/파일 계약에 대한 시험 가정을 실제 계약에 맞춰 수정했으며 제품 동작을 시험에 맞춰 바꾸지 않았다.
- 공통5파일10개는 acceptance 독립 담당이 S1 전환 후 모두 통과한 실행 근거를 확인했다. 현재 수집은 22파일40개, edition skip/fixme와 판본 환경변수 참조0이다. 최종 단일 전체 실행은 S17 통합을 포함하여 root가 별도 기록한다.
- 문서 cold review에서는 installer의 Enter가 기존 계정 존재를 확인한다는 잘못된 설명을 수정했다. 생략 가능하나 최초 admin·키관리 developer가 필요하고 실제 생성 CLI를 안내한다. 카탈로그 검증의 실행 없는 `import_catalogs_v4` 명령을 실제 `app.import_catalogs --spec 20261002 --check`로 정정하고 역사 v3는 explicit spec로 분리했다. Q26–Q28 감정의 일관성 역채점을 포함한 전체28문항을 안내한다.

### 통합 동결 전 추가 확인

- 앱 제품 버전을 backend/frontend 및 두 lockfile에서 0.3.0으로 일치시켜 구 v0.2.0 설치물과 구분했다. 의존성 버전은 변경하지 않았고 `uv lock --check --offline`이 통과했다.
- 전체 backend 663개(1201.612초)의 실패4/오류2는 안정 case_id를 추가한 삭제 이력 계약의 기존 시험 기대값과, 무관한 삭제 fixture가 보존 사례 ID를 재사용한 문제였다. 제품의 안정 ID 보호를 유지하며 시험만 수정했고 intake-v3/reset/settings/반복 삭제복원 36개(61.450초)가 통과했다. S17 최종 변경을 포함한 전체 회귀는 별도 최종 기록으로 남긴다.
- 마지막 독립 packaging/rehearsal cold review는 제품 allowlist·필수 S1 HTML/CSS/폰트·공통 worker import, CLI의 실제 S1 run kind와 request/revision, 새 설치 격리·재시작·손상 거절, 합성 리허설의 무공급자 실행을 검토했다. 수용이 필요한 추가 발견사항은 없었다.

### 단일 저장소의 전체 브라우저 통합 점검

첫 전체 S1 브라우저 실행은41개 중32개 통과/9개 실패(9.3분)였다. 그중 실제 제품 결함은 삭제·철회된 이전 연구 내보내기 한 건이 정상 항목 전체 목록을 실패시키는 문제였고, 같은 패턴의 참고자료 손상도 재현했다. S14의 항목별 차단 요약과 현재 권한 재검사로 수정하고 신규 backend6개를 통과했다. 새로고침 뒤 이전 성공 배너가 남는 독립 cold P2도 수정했다.

나머지는 공유 저장소를 쓰는 전체 실행의 시험 전제 문제였다. 기존 참가자 존재 시 닫힌 등록 패널을 명시 열기, 동일 문구의 참가자/상세 범위 지정, 수정된 비교 제목, Forms CSV를 JSON으로 읽지 않기(모든 파일 SHA검증은 유지), 실제 회차 변경 응답과 polling 반영 대기, 최초 목록 로드 후 Forms 패널 열기로 보완했다. 정상 제품 동작을 시험에 맞춰 약화하지 않았다. 실패를 관찰한 뒤 단독 통과로 대체하지 않고 선행 자료를 남긴 조합 실행과 전체41개를 다시 검증한다.

### 최종 브라우저·원본·문서 확인

- `frontend/`의 `npm run test:e2e`: **41개 전체 통과, 3.7분, skip0**. 비교→검수/export→외부비교→Forms/접수→운영 백업→기록/전처리→리포트/인쇄→AI/독립 채점→3브라우저 수신을 공유 저장소 순서로 통과했다. build 통과(57 modules), 외부 비교가 있는 모바일 HTML과 서버/브라우저 PDF 전6쪽 시각 검수를 완료했다.
- 목록 결함 수정 직전 backend 전체는679개(1083.446초)가 통과했다. 목록 수정6개를 포함한 최종 전체는 별도 아래에 기록한다. 확장된 패키지 allowlist 기존 시험도1개(0.010초) 통과했다.
- 커밋된 문서의 상대 링크302개 누락0, 원본12개 bytes/hash 일치, S1추출8개·역사v3추출6개 대조 통과, 전체 변경 whitespace 검사 통과다.
- 패키지 cold P2: README/PILOT이 참조하는 운영 범위·후속 문서가 기존 ZIP allowlist에서 누락됐다. 이번 S1의 추적된 운영 Markdown30개와 합성 검증PNG2개만 명시 범위로 포함한다. 고객 원본·개발용 시험·실측 스크립트는 제외하고, 개발 근거는 release.json의 commit에서 확인하도록 안내한다. 문서 원문bytes와 파일별 hash는 보존한다.

- 오프라인 문서 보완의 독립 cold는 실제 추적 파일+product allowlist로 Markdown30개/합성PNG2개와 상대문서·이미지237개 누락0을 확인했다. 고객 DOCX/XLSX·backend/frontend시험·benchmark개발스크립트 제외와 원문bytes/hash 보존도 확인했으며 신규 발견사항은 없었다.
