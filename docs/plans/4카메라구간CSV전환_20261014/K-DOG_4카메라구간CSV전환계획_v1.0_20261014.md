# K-DOG 4카메라 영상·구간 CSV 전환 계획

버전: v1.0 · 2026-10-14 · 조사 기준 commit: `2f015c2` · 상태: VC01 #100·VC02 #101 병합 완료 / VC03 구현·검증·독립 검토 완료 / VC04 계획 · 샘플 자료: [`docs/plans/확정 영상 및 구분_20261014/`](../확정%20영상%20및%20구분_20261014/segments.csv)

## 1 사용자 결정과 범위

2026-10-14 사용자는 다음을 결정했다.

1. **INSV/360 통합 MP4 진행 형식을 진행하지 않는다.** 2026-10-04 INSV 보관 전용 정책과 2026-10-12 [360 통합 MP4 계획](../360통합MP4업로드_20261012/K-DOG_360통합MP4업로드계획_v1.0_20261012.md)(MP01~MP03, PR #90~#92 병합)으로 들어간 제품 경로를 **제거 확정**한다.
2. **고정 카메라 4대의 MKV 영상**과, 녹화 도구가 만드는 **구간 CSV(`segments.csv`)**를 촬영 자료로 사용한다. 샘플은 `6_CAM1_복도-정면.mkv` … `6_CAM4_참여자-오른쪽.mkv` 4개와 `segments.csv` 1개다.
3. CSV는 현재 형식 그대로 활용한다. 값이 틀린 경우의 방어 설계는 과한 고민으로 보고 **최소 형식 검증 + 초안 채우기 + 기존 저장 경로**로 구현한다. 형식 보완(걷기 국면·사건·중단 행)은 별도 요청 사항이며 이번 범위의 선행 조건이 아니다.
4. 같은 날 첫 분석(수정 범위·가치 판단)을 수용해 반영한다.

범위 밖: 고객 산식·관찰창·채점 규칙 변경, 원본 `docs/요구사항_20261003/` 재대조, 실제 공급자 품질·현장 인수, 녹화 도구 자체의 수정.

## 2 샘플 자료에서 확인한 사실 (2026-10-14, ffprobe)

| 파일 | 내용 |
| --- | --- |
| `6_CAM1_복도-정면.mkv` | H.264 1920×1080 30fps, 336.9초, 340,507,193 bytes, **오디오 스트림 없음** |
| `6_CAM2_테스트룸-입구.mkv` | H.264 1920×1080 30fps, 337.0초, 오디오 없음 |
| `6_CAM3_참여자-왼쪽.mkv` | H.264 1920×1088 30fps, 329.2초, 오디오 없음 |
| `6_CAM4_참여자-오른쪽.mkv` | H.264 1920×1080 30fps, 336.9초, 오디오 없음 |
| `segments.csv` | UTF-8 BOM, 13열, 8행(`종류=구간`, 구간번호 1~8: 입장·기준·혼자·재회·무시·걷기·낯선 사람·퇴장). 각 행은 **시작 시각만** 가지며 `경과초(녹화시작기준)`과 `CAM1_영상초`~`CAM4_영상초` 열이 있다. `중단사유`·`취소대상순번`은 비어 있다 |

- 카메라별 영상초 차이는 8행에서 일정하다(CAM1 기준 CAM2 +0.069초, CAM3 −0.118초, CAM4 −0.016초, 편차 0.01초 이내). 따라서 다른 카메라 offset을 CSV에서 계산할 수 있다.
- 구간 끝 시각은 없다. 끝은 다음 구간 시작으로 유도하고, 마지막 퇴장 끝은 CSV에 없으므로 운영자가 입력한다.
- 4개 MKV는 `.gitignore`의 `*.mkv`로 이미 제외된다. `segments.csv`는 개인정보가 없는 형식 근거이므로 같은 폴더에 커밋한다.
- 오디오가 없으면 현행 [preprocess_v4.py:376-383](../../../backend/app/preprocess_v4.py#L376-L383)에서 대표 오디오가 선택되지 않고 발성 관련 7행(바6, 개11, 개60, 개47~개50)은 미관찰로 처리된다. 이는 앱 수정 대상이 아니라 **촬영 설정(최소 1대 음성 녹음)**으로 해결한다. 이번 계획은 오디오 없는 입력도 기존 규칙대로 미관찰 처리함을 확인만 한다.

## 3 현행 코드 근거

Graft `ask/grep/callers/skeleton`과 exhaustive `rg`로 확인했다.

| 코드 범위 | 현재 사실 | 이번 영향 |
| --- | --- | --- |
| [media_v4.py:10](../../../backend/app/domain/media_v4.py#L10) `MediaKey` | `camera_id`는 `^[A-Za-z0-9_-]+$` 일반 패턴 | `CAM4` 서버 변경 없이 통과 |
| [media_v4.py:13](../../../backend/app/domain/media_v4.py#L13) `CAMERA_ORIGINALS` | CAM1→원본1, CAM2→원본3, CAM3→원본2 (S1 원본 D01 대응) | CAM4는 원본 번호 없음(null 허용). 사양 카탈로그 `resources/rules/preprocess-v4.json`의 `camera_mapping`은 원본 추출값이므로 변경하지 않음 |
| [media_v4.py:26-76](../../../backend/app/domain/media_v4.py#L26-L76) | `ExternalProcessingV4`, `ExternalMediaV4`, `ExternalProcessingEditV4`, `external_media_reasons`, `EXT360` 규칙 | VC01 제거 |
| [media_v4.py:136-181](../../../backend/app/domain/media_v4.py#L136-L181) | `media_status: pending_probe \| storage_only`, `.insv`↔`storage_only` validator, `source_kind` literal에 `external_360_mp4` | VC01: `storage_only`·`external_360_mp4` 제거. `media_status` 필드 자체는 기존 저장 JSON 호환을 위해 `pending_probe` 단일 literal로 유지 |
| [uploads.py:74-86](../../../backend/app/uploads.py#L74-L86), [336-384](../../../backend/app/uploads.py#L336-L384), [387-473](../../../backend/app/uploads.py#L387-L473), [476-534](../../../backend/app/uploads.py#L476-L534) | receipt view의 INSV 판정, link의 EXT360 검사, 보존 영상 등록의 storage_only, `_external_source`/`update_external_processing` | VC01 제거·단순화 |
| [api.py:48](../../../backend/app/api.py#L48), [484-487](../../../backend/app/api.py#L484-L487), [553-555](../../../backend/app/api.py#L553-L555) | import, storage_only attachment 분기, `PATCH …/external-processing` | VC01 제거 |
| [api.py:431-436](../../../backend/app/api.py#L431-L436), [UploadInbox.tsx:86](../../../frontend/src/UploadInbox.tsx#L86) | `.mkv` 이미 허용 | MKV 서버 변경 없음 |
| [preprocess_v4.py:226-236](../../../backend/app/preprocess_v4.py#L226-L236), [282-289](../../../backend/app/preprocess_v4.py#L282-L289) | 재사용 시 외부 영상 검사, storage_only/external → `conversion_required` | VC01 제거. `ViewWindowV4.availability`의 `conversion_required` literal은 과거 batch JSON 호환을 위해 유지 |
| [recording_v4.py:235-249](../../../backend/app/recording_v4.py#L235-L249), [252-266](../../../backend/app/recording_v4.py#L252-L266) | 외부 영상 시간 앵커 검사, INSV 관찰 시각 금지 | VC01: `validate_recording_timeline_v4`·`recording_time_sources_v4`는 외부 영상 전용(callers: `_recording`, `validate_recording_media_v4`, 외부 시험)이므로 제거 |
| [progress_v4.py:75](../../../backend/app/progress_v4.py#L75) | storage_only 제외 | VC01 단순화 |
| [domain/preprocess_v4.py:33](../../../backend/app/domain/preprocess_v4.py#L33), [PreprocessingPanelV4.tsx:47](../../../frontend/src/PreprocessingPanelV4.tsx#L47) | 카메라 우선순위 기본 CAM1~3 | VC02: CAM4 추가 |
| [uploadGuess.ts](../../../frontend/src/uploadGuess.ts), [UploadInbox.tsx:104,159-164](../../../frontend/src/UploadInbox.tsx#L104), [PreservedMediaRegistration.tsx:10,28,90](../../../frontend/src/PreservedMediaRegistration.tsx#L10) | 파일명 원본1/3/2 → CAM 제안, 안내 문구 | VC02: `N_CAMk_설명` 파일명 규칙 추가, 4대 안내 |
| [RecordingPanelV4.tsx:21-28,136-145,172-178](../../../frontend/src/RecordingPanelV4.tsx#L21-L28) | 8구간 시작·끝, 다른 영상 offset을 수동 입력. 저장은 `PUT …/recording-s1` | VC03: CSV 초안 채우기. 서버 계약 [recording_v4.py:33-49,98-108,160-266](../../../backend/app/domain/recording_v4.py#L33-L49) 변경 없음 |
| [catalog_v4.py:42-44](../../../backend/app/domain/catalog_v4.py#L42-L44) `SEGMENTS` | entry·baseline·alone·reunion·ignore·walk·stranger·exit 순서 | VC03: 구간번호 1~8 → 같은 순서 |
| `scripts/verify_mp4_package.py`, [benchmark_s1.py:362,424](../../../scripts/benchmark_s1.py#L362), `tools/insv_converter/` | MP03 설치 검증, INSV 상태 보고, 독립 변환 CLI | VC01 삭제·정리 |
| [scoring_ai_v4.py:172-175](../../../backend/app/scoring_ai_v4.py#L172-L175) | 창별 가용 클립을 모두 공급자에 전송 | 4대면 3대 대비 전송량 약 4/3배. 코드 변경 없음, 운영 비용 기록 |

INSV/360 참조는 제품·스크립트·도구 19개 파일, 시험 11개 파일, 문서 2개(`DEVELOPMENT.md`, `PILOT_OPERATIONS.md`)에 분산되어 있다. 전체 목록은 [VC01](K-DOG_PR-VC01_INSV360경로제거_v1.0_20261014.md)에 둔다.

## 4 계약 결정

### 4.1 카메라 구성 (D01 운영 결정)

| 식별자 | 샘플 파일 | 원본 번호 |
| --- | --- | --- |
| CAM1 | `6_CAM1_복도-정면.mkv` | 1 (기존 대응 유지) |
| CAM2 | `6_CAM2_테스트룸-입구.mkv` | 3 (기존 대응 유지) |
| CAM3 | `6_CAM3_참여자-왼쪽.mkv` | 2 (기존 대응 유지) |
| CAM4 | `6_CAM4_참여자-오른쪽.mkv` | 없음(null) |

- S1 원본 D01은 CAM1 입구/CAM2 중앙 360/CAM3 반대편 3대 구성이었다. 4대 고정 카메라는 **운영 결정**으로 기록하며 고객 원본·카탈로그(`camera_mapping`, `camera_layout_status: provisional_D01`)를 재작성하지 않는다. [실측 후속 대장 P01](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)의 "최종 카메라 구성 확정"은 이 결정으로 갱신하되 고객 확인 상태는 별도 표시한다.
- 파일명 `N_CAMk_설명.확장자`(N=녹화 회차, k=1~4)는 촬영 카메라 번호 제안 규칙으로 추가한다. 기존 `원본1/2/3` 규칙은 유지한다. 두 규칙 모두 제안이며 서버 검사는 그대로다.
- 카메라 수를 4로 고정하지 않는다. 우선순위 기본값만 CAM1~CAM4로 넓히고 실제 연결된 영상으로 동작한다.

### 4.2 구간 CSV

- 입력은 녹화 도구의 현재 형식이다. 열은 **머리글 이름**으로 읽어 열 순서·추가 열에 영향받지 않게 한다. BOM을 제거한다.
- 사용하는 행: `종류 == 구간`이고 `구간번호`가 1~8인 행. `구간번호` → `SEGMENTS` 순서(1 입장=entry … 8 퇴장=exit). `구간이름`은 교차 확인용으로만 쓰고 불일치는 경고로 표시한다.
- 기준 영상은 촬영 기록 화면에서 선택한 영상이며 그 `camera_id`(예 CAM1)의 `CAMk_영상초` 열이 구간 시작이다. `경과초(녹화시작기준)`·`시각` 열은 저장하지 않는다.
- 구간 끝 = 다음 구간 시작. 퇴장 끝은 null로 두고 운영자가 입력한다. 상태는 모두 `performed`이며 누락 구간은 값을 비운 채 두고 경고한다(미실시 사유를 발명하지 않음).
- 다른 연결 영상의 offset = `CAMk_영상초 − CAM기준_영상초`(8행 평균, 소수 3자리). 비고(`note`)에 CSV 파일명·SHA-256·계산 열을 적고 `confirmed=true`로 채운다. 운영자는 기존 체크박스로 해제할 수 있다. 이 결정은 "틀린 값 방어는 과한 고민"이라는 사용자 판단에 따른 것이며, 서버의 기존 길이·hash 검증([recording_v4.py:252-286](../../../backend/app/recording_v4.py#L252-L286))은 그대로 적용된다.
- 걷기 6국면·재회/낯선 사람 사건·관찰 근거·꼬리 선택은 CSV에 없으므로 수동 입력이 유지된다. 가져오기 결과 요약에 "채우지 못한 항목"으로 표시한다.
- 출처는 `procedure_note` 끝에 `segments.csv <파일명> SHA-256 <hash>` 한 줄을 덧붙인다. CSV 파일 자체를 서버에 보관하는 업로드 API는 만들지 않는다.
- 저장은 기존 `PUT /api/cases/{case_id}/sessions/{session_id}/recording-s1`이며 백엔드 변경은 없다.

### 4.3 제거 후 보존 규칙

- 기존 원본 업로드·변환 MP4(`received_conversion`) 계보, 불변 파일, 이전 판본, 업무 권한 결정은 그대로다.
- `media_status` 필드는 저장된 manifest/receipt JSON(`extra=forbid`)과의 호환을 위해 남기고 값만 `pending_probe`로 제한한다. `ViewWindowV4.availability`의 `conversion_required` literal도 과거 batch 호환을 위해 남긴다.
- 운영 DB에 `source_kind == external_360_mp4` 영상이나 `.insv` receipt/영상이 있으면 제거 후 앱이 해당 case/receipt를 읽지 못한다. VC01에서 점검 명령을 두어 **0건 확인 뒤** 배포하고, 있으면 보고 후 사용자가 처리 방법(해당 입력 삭제·재등록)을 결정한다. 자동 삭제·이관은 하지 않는다.
- 이전 앱(360 종류 포함)을 같은 운영 DB에 병행 실행하지 않는다는 기존 안내는 유지한다.

## 5 PR 분할과 선행

| PR | 목표 | 선행 | 상태 |
| --- | --- | --- | --- |
| [VC01 INSV·360 경로 제거](K-DOG_PR-VC01_INSV360경로제거_v1.0_20261014.md) | 종류·metadata·PATCH·storage_only·도구·시험·문서 제거, 운영 DB 점검 | 없음 | #100 병합(`0cae5d3`) |
| [VC02 4카메라 식별과 전처리 기본값](K-DOG_PR-VC02_4카메라식별과전처리기본값_v1.0_20261014.md) | CAM4 우선순위 기본값, 파일명 규칙, 안내 문구, MKV 합성 회귀 | VC01 | #101 병합(`45b0f7c`) |
| [VC03 구간 CSV 가져오기](K-DOG_PR-VC03_구간CSV가져오기_v1.0_20261014.md) | 촬영 기록 화면의 CSV 초안 채우기, 파서 시험, E2E | VC02 | 구현·검증·독립 검토 완료, 병합 준비 |
| [VC04 통합 검증과 운영 문서](K-DOG_PR-VC04_통합검증과운영문서_v1.0_20261014.md) | 전체 회귀, 실제 샘플 4MKV+CSV 로컬 인수, ZIP, 운영 안내 | VC01~VC03 | 계획 |

VC01을 먼저 두는 이유는 `UploadInbox.tsx`·`RecordingPanelV4.tsx`·`PreprocessingPanelV4.tsx`가 VC02/VC03과 같은 파일이라 제거 뒤 작업해야 충돌과 되살아난 코드를 피하기 때문이다. VC02와 VC03은 작은 PR이지만 각각 독립 검토·검증을 거친다.

## 6 추적과 완료 기준

VC-R/VC-T는 이번 사용자 결정의 보조 식별자이며 고객 R01~R25/T01~T32를 재정의하지 않는다.

| 요구 | 구현 PR | 인수 |
| --- | --- | --- |
| VC-R01 INSV/360 경로가 제품·API·UI·도구·문서에서 사라짐 | VC01 | VC-T01 `external_360_mp4`·`EXT360`·`storage_only`·`insv` 참조 0건(역사 문서 제외), 전체 회귀 통과, 운영 DB 점검 0건 |
| VC-R02 기존 원본/변환본·판본·권한·불변 파일 보존 | VC01 | VC-T02 기존 upload/preprocess/recording/report 회귀, 저장된 `media_status: pending_probe` JSON 로드 |
| VC-R03 4대 카메라 MKV 업로드·등록·전처리 | VC02 | VC-T03 CAM4 등록(원본 번호 null), 우선순위 4대, 합성 MKV 클립 생성, 파일명 규칙 제안 |
| VC-R04 구간 CSV로 8구간 시작·끝·offset 초안 채우기 | VC03 | VC-T04 샘플 CSV → 7구간 끝 유도·퇴장 끝 null·3개 offset·출처 한 줄, 기준 카메라 변경, 형식 오류 거절, 기존 저장·확정 검증 통과 |
| VC-R05 CSV가 못 채우는 항목의 수동 입력 유지 | VC03 | VC-T05 걷기 국면·사건 없이 확정 불가 메시지, 수동 입력 뒤 확정 |
| VC-R06 실제 샘플 종단과 운영 안내 | VC04 | VC-T06 로컬 8000 포트에서 샘플 4MKV+CSV 업로드→기록→전처리(오디오 없음 사유 표시)까지, 외부 AI 호출 0건 또는 사용자 승인 1건, ZIP 설치 검증, 운영 문서 갱신 |

## 7 확인 대기와 범위 상한

- 녹화 도구 CSV의 `종류` 값 전체, 중단/취소 행 의미, 퇴장 끝 행, 걷기 국면·사건 행은 **보완 요청 사항**이다. 받으면 VC03 파서를 열 이름 기준으로 확장하고 별도 PR로 계획한다.
- 4대 구성의 고객 확인, 음성 녹음 카메라 지정은 운영팀 확인 대기다. 확인 전에도 VC01~VC04는 진행 가능하다.
- MKV 원본의 브라우저 재생은 Chromium 계열에서만 확인한다. 전처리 클립은 MP4이므로 미리보기에 영향이 없다.
- 실제 공급자 품질·처리 시간(E02~E05)은 이번 범위에서 측정하지 않는다. E01(INSV 호환성)은 결정에 따라 **종료**로 기록한다.

## 8 버전 확인·검토·실행 기록

계획 단계는 라이브러리를 설치하거나 앱을 실행하지 않았다(ffprobe 읽기 전용 조사만 수행). 각 PR 착수 시 AGENTS 규칙대로 공식 릴리스·registry로 최신/선택 버전·호환·확인일을 기록한다. 새 의존성은 예정에 없다(CSV 파싱은 표준 문자열 처리, 해시는 Web Crypto).

각 PR은 구현 → 관련 검사 → 독립 cold review → 수용/보류/거절 기록 → 수용 수정/재검증 → 문서 → push/PR 순서를 따른다. 실제 결과는 이 폴더의 실행 기록(`K-DOG_4카메라구간CSV구현실행기록_v1.0_<날짜>.md`)에 연결한다. 계획 수립 완료는 제품 구현·시험 완료를 뜻하지 않는다.

실제 구현·검증과 검토 수용 결과는 [구현 실행 기록](K-DOG_4카메라구간CSV구현실행기록_v1.0_20261014.md)을 따른다.
