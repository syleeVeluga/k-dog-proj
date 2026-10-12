# PR-MP01 외부 처리 MP4 계약과 보관

버전: v1.0 · 2026-10-12 · 상태: 계획, 미구현 · 선행: `1702f2b` · 브랜치 제안: `veluga/mp01-external-360-media`

상위: [전체 계획](K-DOG_360통합MP4업로드계획_v1.0_20261012.md). 범위: VM-R01~R07의 서버 계약. 제목 제안: `feat: accept externally prepared 360 MP4 inputs`.

## 문제와 결과

현재 `received_conversion`은 등록된 실제 부모를 요구하고 `StoredMediaV4`가 같은 조건을 다시 검사한다. 이를 변경하지 않고 `external_360_mp4` 종류를 추가하여 외부 원본 없이 MP4 자체를 입력 자료로 보관·등록한다. 미지원 360 배치/시간 편집 입력을 서버가 먼저 구분한다. 화면 옵션은 MP02에서 노출한다.

## 대상 파일과 변경 범위

| 파일 | 필요한 변경 |
| --- | --- |
| `backend/app/domain/media_v4.py` | 작은 외부 처리 metadata 모델, UploadCreate/Receipt/StoredMedia/PreservedRegistration의 새 종류와 종류별 validator. 기존 종류 부모 요구 유지 |
| `backend/app/uploads.py` | 생성/조회/등록/동일 hash 비교/기존 보존 영상 출처 등록/다운로드에 metadata 전파·교차 검증. 새 종류의 EXT360/null 원본 번호. 기존 반복 요청 정규 JSON 보호 |
| `backend/app/input_models_v4.py`, `backend/app/api.py` | SessionV4 union/입출력 검증·현재 actor.external_processing만 새 S1 입력 판본으로 확인/정정하는 작은 PATCH API와 typed 요청 |
| `backend/app/preprocess_v4.py` | 출처 snapshot·metadata 비교·호환 hash, 새 종류의 projection/timeline 검사·파일별 제한 사유. 구형 batch/명시 재사용도 검사 |
| `backend/app/domain/preprocess_v4.py`, `backend/app/scoring_ai_v4.py` | 기존 availability/reasons와 clips_for를 재사용. 실제 우회가 확인된 경우에만 필요한 검증 추가. 산식/관찰창/AI 프롬프트 변경 없음 |
| `backend/app/recording_v4.py`, `backend/app/capture_v4.py` | edited/unknown 입력의 실제 시간 앵커 사용을 확정/전처리에서 검증. 초안 보존·현재 actor/판본 재검사. projection과 timeline 검사 분리 |
| `backend/app/maintenance.py` | 참조 검증이 새 metadata를 파일 경로로 오인하지 않는지 검사. 임의 문자열/노트는 자료 참조가 아님 |
| `backend/app/capture_v4.py`, `backend/app/report_runs_v4.py`, `backend/app/exports_v4.py` | Graft로 확인한 StoredMedia 소비자. 새 종류의 source/hash/pin을 읽는지 검토하며 일괄 재작성 없음 |
| 관련 backend tests | 계약·API·단일 영상·업로드/보관·미지원 입력/재사용 회귀 |

DB의 upload_receipts는 종류를 request JSON에 저장한다. 새 enum을 위한 테이블 재구축·기존 DB 덤프/재삽입을 계획하지 않는다. 필요성이 확인되지 않은 추상 media registry·원본 이관 기능은 만들지 않는다.

## 구현 순서

1. 새 종류만 MP4 + external_processing + 부모 없음/conversion 없음으로 받는다. metadata는 projection/timeline와 선택 tool_name/tool_version/note만 사용한다. 없는 값은 unknown/null이다. 원본/기존 변환본/app_derived는 기존 규칙대로 검사한다.
2. 새 필드가 없는 기존 자료를 읽고 쓰는 parser·정규 직렬화 계약부터 회귀로 고정한다. 확장 필드는 새 종류에만 포함하여 기존 receipt의 request_hash·기존 배치 호환 hash가 default null 때문에 달라지지 않게 한다. 기존 저장 JSON/bytes/hash는 수정하지 않는다.
3. 수신 점유·실제 크기/hash·fsync·중단/실패·로그인 재검사·같은 ID 재시도를 재사용한다. 조회 응답에 외부 처리 정보와 원본 미등록이라는 의미를 제공한다. 업로드 응답의 analysis_ready=false는 유지한다.
4. 파일별 참가자/회차 저장에서 서버가 새 종류의 camera_id=EXT360과 source_original_number=null을 검사한다. 실제 camera/원본 번호 매핑을 실행하지 않는다. 같은 hash라도 종류·external_processing·부모/변환 정보가 다르면 충돌로 처리한다. 링크 idempotency 비교와 보존 영상 등록 비교 모두 같은 원칙을 사용한다.
5. unknown으로 등록한 정보는 `PATCH /api/cases/{case_id}/videos/{video_id}/external-processing`의 후보 계약으로 확인/정정한다. session_id·expected_revision·typed metadata만 받아 같은 파일의 새 manifest/input revision과 기존 changes 사건을 기록한다. 원래 upload request_json/hash·link_json·bytes·kind/부모/camera/원본 번호는 불변이다. 같은 SHA-256 재업로드로 provenance 변경을 우회하지 않는다. stale revision·회차 변경·현재 actor/세션·hash 변조를 재검사한다.
6. source snapshot에서 request 원장의 불변 파일/계보와 effective metadata를 구분한다. 유효 metadata는 **현재 또는 명시 고정된 input manifest 판본**에서 읽고 해당 manifest의 실제 hash와 보호된 입력 revision을 확인한다. 이를 원래 request metadata와 무조건 동등 비교하여 정상 확인/정정을 거절하지 않는다. compatibility hash에는 해당 판본의 유효 metadata를 포함한다. 정정 후 옛 batch/실행을 새 정보로 소급 활성화하지 않고 새 전처리를 명시 요청한다.
7. 새 종류에서 flat+preserved만 영상 클립 처리 후보로 사용한다. equirectangular/unknown projection, edited/unknown timeline은 해당 view의 conversion_required와 구체 reasons로 남기며 그 파일의 클립/영상 전송을 생성하지 않는다. edited/unknown 파일이 기준 영상 또는 공통 관찰창의 사건/관찰 근거·확인 offset의 실제 시간 앵커가 되는 것도 확정/전처리에서 막는다. 값 없는 초안/미확인 offset 목록은 실제 시간 근거와 구분한다. equirectangular+preserved는 시간 근거로 사용할 수 있고 영상 클립은 별도 제한한다. metadata timeline 정정으로 이미 쓰인 시간 근거가 달라지면 recording 검토/재확정이 필요하다. 다른 정상 입력 view와 관계없는 사람 업무는 유지한다. 공통 `validate_recording_media_v4`의 capture.save·judgements.create·sheets.assign/revise 호출자도 회귀로 확인한다.
8. 같은 파일의 보관·미등록/등록/실패 상태와 정정 전후 입력 판본, batch/source 파일 참조를 backup/clean/restore로 검증한다. current deletion ledger 병합/purge·새 owner/동의 조건을 넣지 않는다.

## 인수 시나리오

| ID | 실제 구현 시 검사 |
| --- | --- |
| VM-T01 | 원본 receipt 0개에서 MP4 하나 업로드→complete→대상/회차 등록→GET/download. bytes/hash 동일, 원본 업로드 요구 없음 |
| VM-T02 | 새 종류 비MP4·다른 종류의 metadata·가짜 부모·잘못된 hash/실제 크기·완료 파일 변조 거절. unknown/null은 사실대로 저장 |
| VM-T03 | EXT360/null 원본 번호, 동일 파일/metadata 반복은 하나, 출처 변경은409, 다른 대상/회차·stale revision 실패 후 완료 파일 보존 |
| VM-T04 | 새 종류의 flat/360/unknown × preserved/edited/unknown 전 조합. flat 단일 파일은 실제 전처리 clip/원본 시각·실제 frame/audio 확인. 미지원 파일은 영상 공급자 전송0. 정상 기준+편집 파일의 사건/관찰 근거+확정 offset, 편집 기준+정상 view도 잘못된 창을 생성하지 않음. equirectangular+preserved의 정상 시간 근거와 무관한 사람 업무는 유지 |
| VM-T05 | 변경 전 형식의 실제 정규 request JSON fixture로 동일 ID 재시도/실패 재시도/완료 응답 유실 복구. 같은 구형 S1 manifest/batch의 hash·판본·명시 재사용 보존. metadata 조작 및 batch 재사용 우회 거절. metadata 정정 뒤 옛 pin 제공/실행은 당시 정보로 유지 |
| VM-T06 | metadata의 note/tool 값이 ref/storage_ref 같은 문자열이어도 파일로 탐색하지 않음. 새/구 종류 미등록·등록 파일과 고정 batch hash/DB snapshot을 backup/restore/clean으로 검증. 참조 유실 시 clean은 삭제하기 전에 실패 |
| VM-T07 | unknown 등록→같은 video/hash의 metadata 확인→새 revision→명시 전처리 가능. 새 업로드/가짜 부모 없음, 원래 request_json/hash·link_json·이전 manifest 동일. 같은 정보 재시도/stale/세션·actor 변경 거절, flat/preserved→edited 정정 시 오래된 시간 근거와 batch를 그대로 쓰지 않음 |

기존 카메라 3개 업로드·변환 부모 체인·동일 크기 변조·현재 actor 비활성·세션 변경·lease/token·중단·예산·고정 출처 회귀를 유지한다. 영상 입력 미지원과 전체 AI/리포트 업무 금지는 다르다. 사람 원자료로 가능한 기존 계산·리포트까지 임의로 막지 않는다.

## 검증 명령과 인계

`backend/`에서 기존 파일에 회귀를 추가한다. 새 모듈이 꼭 필요하면 파일을 만든 뒤 명령을 추가한다.

```powershell
uv run --locked python -X utf8 -m unittest tests.test_uploads_v4 tests.test_uploads_api_v4 tests.test_preserved_media_v4 tests.test_recording_v4 tests.test_recording_api_v4 tests.test_preprocess_v4 tests.test_preprocess_api_v4 tests.test_intake_v4 tests.test_retention_v4 tests.test_business_access_v4 -v
```

발견된 scoring/report/export 소비자 변경이 있으면 해당 시험을 추가한다. MP01 완료는 새 업로드 API/저장/보관·서버 분석 경계와 관련 회귀 통과이며 실제 Studio 파일 품질/처리시간 완료가 아니다. MP02에 typed 요청/응답·사용자 표시 사유·EXT360 표시·고정 요청 재시도 규칙을 인계한다. 라이브러리/프레임워크 확인은 상위 §7을 적용한다.

## 실행 기록 — 착수 후 작성

- [ ] commit/PR·변경 파일과 실제 적용 계약
- [ ] 최신/선택 버전·공식 근거·잠금 파일 여부
- [ ] 관련 회귀·hash/출처/재사용·현재 actor 검증
- [ ] 독립 cold review·발견 수용/보류/거절·재검증
- [ ] MP02 인계·실측 대기와 구현 완료 구분
