# PR-VC01 INSV·360 통합 MP4 경로 제거

버전: v1.0 · 2026-10-14 · 상태: #100 병합 완료 (`0cae5d3`) · 선행: 없음 · 브랜치 제안: `veluga/vc01-remove-insv-360` · 제목 제안: `refactor: remove INSV storage and external 360 MP4 paths`

상위: [전체 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md) §4.3·§5. 범위: VC-R01/R02.

## 문제와 결과

2026-10-14 사용자 결정으로 INSV 보관 전용 정책과 Studio 통합 MP4(`external_360_mp4`) 경로를 진행하지 않는다. 남겨 두면 업로드 화면·촬영 기록·전처리·API에 쓰지 않는 분기와 시험이 유지되고, VC02/VC03이 같은 파일을 고쳐야 하므로 먼저 제거한다.

결과: 영상 파일 구분은 「촬영 원본」·「변환 MP4」 둘이다. `.insv`는 접수하지 않는다. 외부 처리 metadata·`EXT360`·PATCH 정정·`storage_only`·독립 변환 CLI·MP03 설치 검증 스크립트가 사라진다. 기존 원본/변환본 계보, 불변 파일, 이전 판본, 업무 권한은 바뀌지 않는다.

## 제거 전 점검 (필수)

제거 뒤 앱은 `source_kind == external_360_mp4` 영상과 `.insv` 파일을 읽지 못한다(`extra=forbid`·literal 축소). 구현 첫 단계로 `app.manage`에 읽기 전용 점검 명령(예 `check-removed-media`)을 추가하여 다음을 센다.

- `cases` manifest의 `sessions[].videos[]` 중 `source_kind == "external_360_mp4"` 또는 `original_name`이 `.insv`인 항목
- `upload_receipts.request_json`의 `source_kind == "external_360_mp4"` 또는 `filename`이 `.insv`인 행
- 전처리 batch `source_metadata`에 위 영상이 포함된 결과

로컬 운영 DB와 배포 대상 DB에서 **0건**을 확인한 뒤 VC04 배포를 진행한다. 1건 이상이면 case/receipt 식별자만 보고하고 사용자가 처리(해당 입력 삭제·재등록)를 결정한다. 자동 삭제·이관·marker를 만들지 않는다. 점검 명령은 제거 PR에 포함하고 VC04 이후에도 유지한다.

## 파일별 변경

### backend

| 파일 | 변경 |
| --- | --- |
| [domain/media_v4.py:26-76](../../../backend/app/domain/media_v4.py#L26-L76) | `ExternalProcessingV4`, `ExternalMediaV4`(validator·serializer), `ExternalProcessingEditV4`, `external_media_reasons` 삭제. `UploadCreateV4`·`PreservedMediaRegistrationV4`·`StoredMediaV4`·`UploadReceiptV4`의 base를 `ContractV4`로 되돌리고 `external_processing` 필드 제거 |
| [domain/media_v4.py:79-181](../../../backend/app/domain/media_v4.py#L79-L181) | `source_kind` literal에서 `external_360_mp4` 제거. `media_status`는 `Literal["pending_probe"]`로 유지(저장 JSON 호환). `.insv`↔`storage_only` validator 제거. `Filename` 패턴에 `.insv`가 있으면 제거 |
| [uploads.py:74-86](../../../backend/app/uploads.py#L74-L86) | `_view`의 `external_processing`·INSV 판정 제거, `media_status="pending_probe"` 고정 |
| [uploads.py:336-384](../../../backend/app/uploads.py#L336-L384) | `link_receipt`의 `external_360_mp4`/`EXT360` 검사(L360) 제거 |
| [uploads.py:387-473](../../../backend/app/uploads.py#L387-L473) | `register_preserved_video`의 `external_processing` 전달·`.insv` media_status 분기 제거 |
| [uploads.py:476-534](../../../backend/app/uploads.py#L476-L534) | `_external_source`, `update_external_processing` 삭제. `recording_time_sources_v4` import 제거 |
| [uploads.py:102-122](../../../backend/app/uploads.py#L102-L122) | 업로드 생성 시 `.insv` 접수 허용 조건이 있으면 제거(확장자 목록은 `api.py:431-436`과 일치) |
| [api.py:48](../../../backend/app/api.py#L48), [484-487](../../../backend/app/api.py#L484-L487), [553-555](../../../backend/app/api.py#L553-L555) | import 정리, 영상 응답 `content_disposition_type="inline"` 고정, `PATCH /api/cases/{case_id}/videos/{video_id}/external-processing` 삭제 |
| [preprocess_v4.py:12](../../../backend/app/preprocess_v4.py#L12), [226-236](../../../backend/app/preprocess_v4.py#L226-L236), [282-289](../../../backend/app/preprocess_v4.py#L282-L289), [373](../../../backend/app/preprocess_v4.py#L373) | import, 재사용 시 외부 영상 검사, `storage_only`/외부 → `conversion_required` 분기, view reasons의 `external_media_reasons` 제거. `_recording`(L81-92)의 `validate_recording_timeline_v4` 호출 제거 |
| [domain/preprocess_v4.py:85](../../../backend/app/domain/preprocess_v4.py#L85) | `conversion_required` literal은 과거 batch 호환으로 유지하고 주석으로 사유를 남김 |
| [recording_v4.py:235-249](../../../backend/app/recording_v4.py#L235-L249) | `recording_time_sources_v4`·`validate_recording_timeline_v4` 삭제(callers: `_recording`, `validate_recording_media_v4`, 외부 시험뿐) |
| [recording_v4.py:252-266](../../../backend/app/recording_v4.py#L252-L266) | docstring과 `storage_only` 422 분기 제거 |
| [progress_v4.py:75](../../../backend/app/progress_v4.py#L75) | `storage_only` 필터 제거 |
| `manage.py` | 위 점검 명령 추가 |
| [scripts/benchmark_s1.py:362,424](../../../scripts/benchmark_s1.py#L362) | `insv`/`insv_followup` 상태 항목 제거 |
| `scripts/verify_mp4_package.py` | 삭제(MP03 전용) |
| `tools/insv_converter/` | 폴더 삭제(README·convert.py·test_convert.py). `scripts/build_release.py`는 참조하지 않음을 확인함 |

### frontend

| 파일 | 변경 |
| --- | --- |
| `src/ExternalProcessing.tsx` | 삭제. `cameraName`(7곳 사용)은 `src/types.ts`로 옮기고 `EXT360` 분기 제거 |
| [src/types.ts:8-17](../../../frontend/src/types.ts#L8-L17) | `MediaSourceKind`에서 `external_360_mp4`, `ExternalProcessing` 타입, `Video.external_processing`, `media_status`의 `storage_only` 제거 |
| [src/preprocessTypesV4.ts:2,38](../../../frontend/src/preprocessTypesV4.ts#L38) | import·`source_metadata.external_processing` 제거 |
| [src/UploadInbox.tsx](../../../frontend/src/UploadInbox.tsx) | 구분 option·`ExternalProcessingFields`·단일 MP4 제한·`accept`의 `.insv`·INSV 안내 문구(L94)·receipt 카드의 `storage_only`/EXT360 표시(L125,147-150) 제거 |
| [src/PreservedMediaRegistration.tsx](../../../frontend/src/PreservedMediaRegistration.tsx) | `external_360_mp4` 옵션·processing 입력·EXT360 분기 제거. 보존 영상 출처 등록 자체는 유지 |
| [src/PreprocessingPanelV4.tsx:7,159,163,171,176](../../../frontend/src/PreprocessingPanelV4.tsx#L159) | `ProcessingNotice`·외부 영상 표시·`storage_only` 필터·source_kind 라벨의 통합 MP4 제거 |
| [src/RecordingPanelV4.tsx:10,24,55,113,130](../../../frontend/src/RecordingPanelV4.tsx#L24) | import·`storage_only` 필터·INSV 보관 안내 제거 |
| [src/ScoreSheetsV4.tsx:214](../../../frontend/src/ScoreSheetsV4.tsx#L214) | `storage_only` 필터 제거 |

### 시험

| 파일 | 변경 |
| --- | --- |
| `backend/tests/test_external_media_v4.py`, `test_external_media_acceptance_v4.py`, `frontend/tests/external-media-v4.spec.ts` | 삭제 |
| [test_uploads_api_v4.py:58-66,119](../../../backend/tests/test_uploads_api_v4.py#L58-L66) | INSV storage_only 시험 삭제, 부모 파일명 `.insv` → `.mp4` |
| [test_uploads_v4.py:197-218,267-346,484-495](../../../backend/tests/test_uploads_v4.py#L197-L218) | 부모 `.insv` → `.mp4`, storage_only 단언 제거, 시험 이름 변경 |
| [test_preserved_media_v4.py:94-110](../../../backend/tests/test_preserved_media_v4.py#L94-L110) | `.insv` 보존 영상 단언 제거 |
| [test_progress_v4.py:29,55](../../../backend/tests/test_progress_v4.py#L29) | storage_only 영상 제거, 기대 수 조정 |
| [test_recording_v4.py:256-278](../../../backend/tests/test_recording_v4.py#L256-L278) | INSV 분기 제거 |
| [test_preprocess_v4.py:59,156-165,194,339](../../../backend/tests/test_preprocess_v4.py#L156-L165) | 기본 합성 데이터 이름·`raw.insv` → `.mp4`, "INSV와 디코드 실패" 시험을 디코드 실패만 남김 |
| [test_benchmark_s1.py:206](../../../backend/tests/test_benchmark_s1.py#L206) | `insv` 단언 제거 |
| [frontend/tests/uploads-v4.spec.ts:111-115](../../../frontend/tests/uploads-v4.spec.ts#L111-L115) | INSV 보관 전용 흐름 제거 |
| 새 시험 | `test_manage_check_removed_media.py`: 합성 DB에서 점검 명령이 0건/1건을 정확히 보고하고 아무것도 쓰지 않음. 기존 `media_status: "pending_probe"` JSON 로드 회귀 |

### 문서

| 파일 | 변경 |
| --- | --- |
| [docs/DEVELOPMENT.md:63-69](../../../docs/DEVELOPMENT.md#L63-L69) | 360/INSV/변환 도구/`verify_mp4_package` 단락 제거, 점검 명령 추가 |
| [docs/PILOT_OPERATIONS.md:144,157-161](../../../docs/PILOT_OPERATIONS.md#L157-L161) | INSV 문장과 360 통합 MP4 단락 제거 |
| [360 통합 MP4 계획](../360통합MP4업로드_20261012/K-DOG_360통합MP4업로드계획_v1.0_20261012.md) 상태 줄, [docs/archive/README.md](../../archive/README.md) | "2026-10-14 사용자 결정으로 제품 경로 제거(VC01)" 한 줄 추가. 본문은 이력으로 보존 |
| `tools/insv_converter/README.md`를 가리키는 archive 링크(S16 등) | 링크 대상이 사라지므로 commit 참조 텍스트(`commit 2f015c2의 tools/insv_converter/README.md`)로 바꾼다. 문장 의미는 바꾸지 않음 |
| AGENTS.md | 해당 없음(INSV 언급 없음). 변경 시 사용자 확인 |

## 작업 순서

1. 점검 명령 구현·시험 → 로컬 운영 DB 0건 확인 기록.
2. backend 계약 제거 → `uv run --locked python -X utf8 -m unittest discover -s tests -v` 전체 통과.
3. frontend 제거 → `npm run build` → 관련 E2E(`uploads-v4`, `recording-split-v4`, `preprocess-v4`, `recording-v4`, `scoring-ai-v4`, `copy-guard`, `scenario-staff`).
4. 스크립트·도구·문서 제거, archive 링크 정리.
5. `rg -i "external_360_mp4|EXT360|storage_only|insv|external_processing"`로 제품·시험·스크립트 0건 확인(역사 문서 `docs/archive/`·`docs/plans/360통합MP4업로드_20261012/` 제외). `graft build`·`graft check`·`git diff --check`.
6. 독립 cold review → 수용 반영 → push/PR.

## 검증과 완료 조건

- VC-T01: 위 5단계 grep 0건, 전체 backend/frontend 회귀 통과, 점검 명령 0건 기록.
- VC-T02: 기존 원본 3대 업로드·연결·촬영 기록·전처리·AI 합성·리포트 회귀 통과. `media_status: "pending_probe"`가 있는 기존 manifest/receipt JSON 로드. `received_conversion` 부모 검증 유지.
- 제거는 호출자 점검 뒤 수행하며(`graft callers`), 제거로 생긴 미사용 import/함수만 정리하고 인접 코드는 고치지 않는다.

## 범위 밖

CAM4·파일명 규칙(VC02), CSV 가져오기(VC03), 운영 DB의 실제 360/INSV 레코드 처리(있을 경우 사용자 결정), 배포 ZIP(VC04).

## 2026-10-14 구현 결과

구현과 검증·수용 내역은 [실행 기록 §2](K-DOG_4카메라구간CSV구현실행기록_v1.0_20261014.md#2-vc01)를 따른다. 점검 코드와 그 회귀는 제거 대상 literal을 식별해야 하므로 grep0 검사에서 명시 제외한다. 실제 로컬 운영 DB의 점검은 total0/exit0이며 외부 배포 DB는 배포 직전 별도 점검한다.
