# PR-VC04 통합 검증과 운영 문서

버전: v1.0 · 2026-10-14 · 상태: [#103](https://github.com/syleeVeluga/k-dog-proj/pull/103) 병합 완료(`73023b1`) · 선행: [VC01](K-DOG_PR-VC01_INSV360경로제거_v1.0_20261014.md)·[VC02](K-DOG_PR-VC02_4카메라식별과전처리기본값_v1.0_20261014.md)·[VC03](K-DOG_PR-VC03_구간CSV가져오기_v1.0_20261014.md) 병합 · 브랜치 제안: `veluga/vc04-four-camera-acceptance` · 제목 제안: `docs: record four-camera CSV acceptance and operations`

상위: [전체 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md) §6. 범위: VC-R06과 VC-R01~R05의 통합 회귀.

## 목표

세 PR을 합친 상태에서 전체 회귀, 실제 샘플 자료 로컬 인수, 설치 ZIP 검증, 운영 안내 갱신을 수행하고 실행 기록을 남긴다. 코드 변경은 인수 중 발견한 결함 수정으로 제한한다.

## 검증 항목

| 항목 | 명령·방법 | 완료 기준 |
| --- | --- | --- |
| backend 전체 | `uv run --locked python -X utf8 -m unittest discover -s tests -v` | 전부 통과, INSV/360 skip 없음 |
| S1 원본 검증 | `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check` | 통과(카탈로그 미변경 확인) |
| frontend | `npm ci`, `npm run build`, `npm run test:e2e`(PowerShell, dist 선행) | 전부 통과 |
| 제거 확인 | `rg -i "external_360_mp4\|EXT360\|storage_only\|insv\|external_processing" backend frontend/src frontend/tests scripts tools docs/*.md` | 0건(역사 문서와 읽기 전용 점검 명령·그 회귀 literal 제외) |
| 운영 DB 점검 | `app.manage check-removed-media`(VC01) 로컬 운영 DB | 0건 |
| 실제 샘플 로컬 인수 | `app.manage serve`(8000) → 「영상 파일 업로드」에서 `6_CAM1~4_*.mkv` 4개 업로드(파일명 제안 1~4 확인) → 참가자·회차 저장 → 「촬영 기록」에서 기준 CAM1, `segments.csv` 가져오기 → 퇴장 끝·걷기 수동 입력 → 저장·확정 → 전처리 실행 | 클립 4대 생성, 영상 범위가 있는 모든 view의 reason에 `audio_absent_or_unavailable`, 대표 오디오 없음(`no_usable_audio`), 원본 미리보기(Chromium). 외부 AI 호출 0건. 사용자가 승인하면 AI 분석 1회를 실행해 발성 7행 미관찰·나머지 항목 응답을 기록 |
| 처리 시간 | 위 인수에서 업로드(4×~330MB)·전처리 벽시계 기록 | 수치는 실행 기록에만 기록, 목표값을 만들지 않음 |
| 설치 ZIP | `scripts/build_release.py` 두 변형(portable·online) → 기존 ZIP 설치·감독·재시작 검증 절차 | `verify_mp4_package.py` 삭제 후 절차 문서 일치 |
| 문서 | `git diff --check`, 상대 링크 확인(`docs/`·archive 링크 포함), `graft build`·`graft check` | 깨진 링크 0 |

## 문서 변경

| 파일 | 내용 |
| --- | --- |
| [docs/PILOT_OPERATIONS.md:144-145](../../../docs/PILOT_OPERATIONS.md#L144-L145) | 영상 업로드: 고정 카메라 4대 MKV, 파일명 `N_CAMk_설명` 제안, CAM4 원본 번호 없음, 음성 녹음 카메라 필요. 촬영 기록: 「구간 CSV 가져오기」 절차, 채워지는 것/수동 입력(걷기 국면·사건·퇴장 끝), 가져온 offset 확인 해제 방법 |
| [docs/DEVELOPMENT.md](../../../docs/DEVELOPMENT.md) 전처리와 실행 절 | 4대 기본 우선순위, MKV 지원 범위(ffmpeg 디코드·클립 MP4), CSV 파서 모듈·fixture, 점검 명령 |
| [실측 후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md) E01·P01 | 2026-10-14 결정으로 E01(INSV 호환성) 종료, P01 카메라 구성은 4대 운영 결정·고객 확인 대기로 갱신(한 줄 추가, 본문 보존) |
| `docs/plans/4카메라구간CSV전환_20261014/K-DOG_4카메라구간CSV구현실행기록_v1.0_<날짜>.md` | VC01~VC04의 PR 번호·commit·검증 결과·독립 검토 수용 내역·실제 샘플 인수 기록·미실측 항목 |
| [전체 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md) 상태 줄 | 병합 결과로 갱신 |
| 메모리 `MEMORY.md` | 해당 없음(저장소 문서로 충분). 사용자 지시가 있으면 추가 |

## 인수 중 결함 처리

발견 결함은 이 PR에서 고치되 범위는 VC01~VC03의 요구로 한정한다. 새 요구(CSV 보완본, 오디오 카메라, 고객 확인)는 실행 기록의 대기 목록에 적고 구현하지 않는다.

## 완료 조건

- VC-T06 전부 통과, 실행 기록에 실제 명령·결과·시간·스크린샷(PNG, 개인정보 없음) 기록.
- 독립 cold review 수용 반영 후 push/PR. 병합 뒤 전체 계획 상태 갱신.
- 참가자 영상·CSV 원본은 커밋하지 않는다(MKV는 ignore, 샘플 CSV만 형식 근거로 커밋).

구현 결과와 실제 파일/합성 수동 입력의 구분은 [실행 기록 §5](K-DOG_4카메라구간CSV구현실행기록_v1.0_20261014.md#5-vc04)를 따른다. 전체 backend777건, E2E139건, 패키징20건 및 독립 cold review finding0을 확인했다.
