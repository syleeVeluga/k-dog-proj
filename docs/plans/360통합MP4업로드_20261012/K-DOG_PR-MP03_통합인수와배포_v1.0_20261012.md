# PR-MP03 통합 인수와 배포

버전: v1.0 · 2026-10-12 · 상태: 통합 인수 구현·독립 cold review 수용 수정 완료, 최종 전체/ZIP 검증 중 · 선행: MP01 #90·MP02 #91 병합 `befa18c` · 브랜치: `veluga/mp03-360-upload-acceptance`

상위: [전체 계획](K-DOG_360통합MP4업로드계획_v1.0_20261012.md). 범위: VM-R01~R08 종단 인수. 제목 제안: `test: verify prepared MP4 uploads and deployment compatibility`.

## 목표

새 통합 MP4 옵션을 사용한 ‘파일 한 개·원본 미등록’ 흐름과 기존 S1/변환 계보/3CAM·불변 파일·snapshot 보관을 함께 검증한다. 현재 사용자 환경에서 동작하는 업데이트 근거를 남긴다. 합성 기술 인수와 실제 Studio 파일의 호환/품질/시간 실측을 별도 기록한다.

## 변경 대상

[통합 순서](K-DOG_360통합MP4업로드계획_v1.0_20261012.md#41-es-선행-구현을-반영한-진행--2026-10-12-후속-결정)의 마지막 PR이다. ES01~03·MP01/02를 반영한 commit에서 조합 인수와 최종 전체 회귀/ZIP 설치를 검증한다. 앞선 PR별 성공은 해당 범위의 근거로 보존하고 최종 검증은 실제 최종 commit에 연결한다.

- 관련 backend/frontend 기존 시험과 필요한 최소 종단 fixture. 새 scoring/report 생성 코드를 복제하지 않고 기존 합성 fixture를 재사용한다.
- `docs/DEVELOPMENT.md`, `docs/PILOT_OPERATIONS.md`, 새 옵션의 실제 실행 기록과 이 폴더의 계획/검증 상태.
- `scripts/build_release.py`, `scripts/verify_release.py`, `backend/app/launcher.py`는 기존 배포 방식을 재사용한다. allowlist·필수 자산 누락이 실제 확인된 경우에만 최소 변경한다. 새 계획 폴더가 포함되면 민감자료가 함께 들어가지 않는지 확인한다.

## 종단 인수

| 인수 | 기준 |
| --- | --- |
| 하나의 외부 MP4 | 부모 receipt 0개로 업로드·등록·재시작/새로고침·download hash 동일. VM-T01/02/03 |
| 지원 단일 flat | 실제 프레임·오디오를 가진 합성 MP4와 확정 촬영 시각으로 전처리→불변 batch→기존 합성 공급자 분석/기존 S1 결과·리포트 fixture 연결. 실제 품질 골든값을 발명하지 않음 |
| 실제 360/미확인/편집 | 업로드/등록/내려받기 성공과 해당 파일의 영상 분석 입력 제한을 동시에 확인. mixed view의 정상 시간 근거는 유지하고 편집/미확인 기준·사건/관찰 시각 전파는 차단. 구형 batch·명시 재사용으로 제한 우회 없음. VM-T04/05 |
| 기존 자료 | 변경 전 정규 request JSON의 반복 업로드·source snapshot·compatibility hash·S1 판본·발급 bytes 유지, 기존 실제 부모 변환본·3CAM도 성공 |
| 공유 계정 | 접수 A→업로드 B→촬영/조회 C→개발자 일반 업무 D. 실제 actor·현재 세션·pin/lease·설정 경계 유지. 역할/소유/동의 승인 신설 없음 |
| 나중 확인/정정 | unknown 파일 등록→다른 업무 계정이 실제 metadata 확인→동일 video/hash·새 input revision→필요한 촬영 근거 재확정/새 전처리. 파일 재전송0, 원래 원장/hash·과거 S1 판본 보존. VM-T07 |
| 백업/복원/clean | 미등록/등록/실패/파생 파일·기존 request/changes row와 새 metadata를 snapshot 그대로 복원. 참조 검증 실패 전에 삭제하지 않음. 옛 purge/current ledger 병합 없음 |
| 배포 | 깨끗한 커밋의 portable/online ZIP·hash·신규 파일 포함/기존 자료 보존·새 종류 재시작 조회·설치 감독 종료. 새 종류를 모르는 옛 앱의 동일 DB 운영은 안내에서 제외 |

‘미지원 영상 전송0’은 해당 파일이 공급자 영상 요청으로 넘어가지 않는다는 뜻이다. 영상과 무관한 기존 사람 계산/리포트 업무를 일괄 금지하지 않는다. 제품 시험에서 사용하는 합성 공급자는 외부 요청0으로 검증한다.

## ES와 MP 조합 인수 — 구현 후 실행

아래 VM-ES-T01~04는 기존 VM-T01~08/ES-T01~18을 연결하는 추가 인수이며 기존 요구·시험 번호를 대체하지 않는다. MP01에 서버 회귀, MP02에 화면 회귀를 추가한 뒤 이 PR에서 합성 영상/계정·제어된 지연 응답·가짜 공급자로 종단 확인한다.

| ID | 흐름과 성공 조건 | 연결 |
| --- | --- | --- |
| VM-ES-T01 | flat/preserved 파일로 전처리 성공 후 metadata 정정. 과거 execution_id/원래 actor/완료 상태/result pointer·batch/hash·고정 metadata는 보존되고 현재 입력과 다름/outdated가 표시된다. 그 결과의 보존 조회는 가능하고 현재 입력의 무검증 재사용은 거절된다. 필요한 촬영 재확정과 새 전처리는 명시 동작이며 별도 실행 ID로 생성한다. AI의 이전 결과 유효성 배지도 현재 선택 run의 상태와 분리한다. | VM-T05/07, ES-T02/11/14/17 |
| VM-ES-T02 | 전처리 시작 후 처리 경계를 멈추고 다른 활성 계정이 metadata를 정정한다. 기존 guard가 변경 전 입력으로 결과를 게시하지 못하게 하고 실패/대체는 해당 시도에만 연결한다. 이전 성공·다른 시도의 결과는 그대로다. 정정/실패 확인 뒤 지연된 running 조회나 POST 응답이 반환되어도 최신 문맥/상태를 덮지 않으며 자동 새 실행은 없다. | VM-T05/07, ES-T03/04/11/17 |
| VM-ES-T03 | 정상 시간 근거/정상 영상과 미지원 통합본을 함께 등록해 명시 전처리한다. 정상 view의 클립은 유지되고 미지원 파일은 conversion_required와 구체 사유·해당 영상 전송0으로 남는다. 생성 batch의 실제 partial/complete 판정에 맞춰 내 목록/지정 상세를 표시하며 업로드 성공이나 과거 AI 게시 결과를 새 실행 완료로 표시하지 않는다. 1366/390px에서 EXT360은 기본 화면의 통합 영상 이름으로 표시하고 제한·부분 완료·다음 행동이 보인다. | VM-T04/07, ES-T09/12/14/18 |
| VM-ES-T04 | A 업로드→B 전처리/AI 시작→C metadata 정정·공유 상세 조회→B가 현재 입력으로 명시 새 실행. 내 목록의 원래 실행자는 B이며 A/C의 후속 행위로 바뀌지 않는다. 공유 조회/업무는 유지되고 과거/새 실행 ID·결과·입력판과 계정 전환/응답 유실 복구가 섞이지 않는다. 조회만으로 revision·원자료 열람·추가 실행/공급자 요청이 생기지 않는다. | VM-T07, ES-T01/04/07/10/16/17 |

ES에서 신설할 `backend/tests/test_preprocess_execution_v4.py`, `frontend/tests/preprocess-executions-v4.spec.ts`, `analysis-status-v4.spec.ts`와 실제 인계한 회귀 경로를 사용한다. 이 절의 체크는 모두 구현 후 실행 예정이며 문서 조정 시 제품 시험/실제 외부 AI 호출은 수행하지 않는다.

## 실제 파일 후속

사용자가 제공한 통합 MP4와 내보내기 정보는 저장소 밖 보호 경로에 둔다. 한 파일의 업로드/등록/재생/decode·길이·FPS·영상 스트림/오디오, projection/timeline의 사용자 기록과 실제 확인 범위를 남긴다. 일반 `<video>` 재생만으로 구면 시야·미세 행동 판독을 검증했다고 기록하지 않는다.

actual equirectangular 직접 AI 지원·원본 대비 품질·장시간 시각/오디오 정확도·GB급 업로드/전처리 시간은 [S16](../../archive/개발반영_20261003/K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md)과 [후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)의 E01~E05/P01을 따른다. 실제 파일이 없으면 항목별 미실행을 남긴다. 원본이 없는 통합본은 기술 호환성/시간 확인에 쓸 수 있지만 원본 대비 품질 비교 완료로 표시하지 않는다. 자료 부재가 업로드 옵션의 계약/합성 검증 완료를 막지는 않는다.

## 최종 실행 명령

```powershell
# backend/
uv sync --locked
uv run --locked python -X utf8 -m unittest discover -s tests -v
# frontend/
npm ci
npm run build
npm run test:e2e
# 저장소 루트
git diff --check
graft build
graft check
```

S1 source 자산을 변경하면 원본을 확보/기록된 hash 대조 후 `app.import_catalogs --spec 20261002 --check`도 실행한다. 이 계획은 scoring/catalog 자산 변경을 요구하지 않는다. 이미 성공한 전체 검사를 이유 없이 반복하지 않고 새 수정/실패·남은 우려가 있을 때만 재실행한다.

ZIP은 깨끗한 작업 트리에서 만들어 실제 설치를 검증한다. 아래 파일명은 새 산출물 예시이며 기존 결과를 덮어쓰지 않는다. 포터블 runtime/FFmpeg 준비와 online uv/FFmpeg 환경은 [개발 안내](../../DEVELOPMENT.md)를 따른다.

```powershell
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py releases/kdog-mp03-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py releases/kdog-mp03-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/build_release.py --variant online releases/kdog-mp03-online-windows-x64.zip
backend/.venv/Scripts/python.exe -X utf8 scripts/verify_release.py releases/kdog-mp03-online-windows-x64.zip
```

완료 문서에 exact commit/PR/merge·전체 성공/실패/skip·screenshot·ZIP SHA-256·실제 설치 범위·cold review/triage와 후속 상태를 기록한다. 이번 계획 작성 시에는 이 명령들을 실행하지 않는다. 고객 발행 패키지 생성·실제 배포/병합은 해당 실행 지시에 따른다.

## 실행 기록 — 착수 후 작성

- [ ] 새 종류와 기존 S1의 단일 실제 전체 검사 결과
- [ ] 공식 최신/선택 버전·필요 API/FFmpeg·lockfile 근거
- [ ] 독립 cold review·수용 수정·재검증
- [ ] portable/online 새 ZIP·해시·설치/재시작·실제 범위
- [ ] 운영 안내·완료 commit·미실측 항목별 인계
