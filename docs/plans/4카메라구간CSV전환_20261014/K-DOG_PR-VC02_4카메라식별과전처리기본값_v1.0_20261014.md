# PR-VC02 4카메라 식별과 전처리 기본값

버전: v1.0 · 2026-10-14 · 상태: #101 병합 완료 (`45b0f7c`) · 선행: [VC01](K-DOG_PR-VC01_INSV360경로제거_v1.0_20261014.md) 병합 · 브랜치 제안: `veluga/vc02-four-cameras` · 제목 제안: `feat: support four fixed cameras and recording filename hints`

상위: [전체 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md) §4.1. 범위: VC-R03.

## 문제와 결과

서버는 `CAM4`와 `.mkv`를 이미 받지만, 화면 기본값·안내·파일명 제안은 CAM1~CAM3과 `원본1/2/3` 이름만 전제한다. 새 촬영은 `N_CAMk_설명.mkv` 4개 파일이다.

결과: 업로드 화면이 새 파일명에서 촬영 카메라 번호 1~4를 제안하고, 전처리 우선순위 기본값이 CAM1~CAM4가 되며, 합성 MKV가 업로드→등록→촬영 기록→전처리 클립 생성까지 통과함을 회귀로 고정한다. 카메라 수를 4로 강제하지 않는다. 원본 번호 대응(CAM1→1, CAM2→3, CAM3→2)은 유지하고 CAM4는 원본 번호 없음이다.

## 파일별 변경

| 파일 | 변경 |
| --- | --- |
| [backend/app/domain/preprocess_v4.py:33](../../../backend/app/domain/preprocess_v4.py#L33) | `camera_priority` 기본값 `("CAM1", "CAM2", "CAM3", "CAM4")`. 화면은 항상 명시 전송하므로 기존 request hash에 영향 없음. 기본값을 단언하는 시험이 있으면 갱신 |
| [backend/app/domain/media_v4.py:13](../../../backend/app/domain/media_v4.py#L13) `CAMERA_ORIGINALS` | 변경 없음(CAM4 미포함 → `source_original_number=None`) |
| [frontend/src/uploadGuess.ts](../../../frontend/src/uploadGuess.ts) | 규칙 추가: 어간이 `^\d+_CAM([1-9]\d*)_` 또는 `^CAM([1-9]\d*)(_\|$)`(NFKC, 대소문자 무시)이면 `{ original: null, camera: 'CAM<k>' }`. 기존 `원본1/2/3` 규칙 유지. 두 규칙이 동시에 맞는 이름은 제안하지 않음 |
| [frontend/src/UploadInbox.tsx:104,159-164](../../../frontend/src/UploadInbox.tsx#L104) | 안내: 「파일명 `6_CAM1_…`은 촬영 카메라 1번으로 제안」. 원본 번호 placeholder는 CAM4에서 「없음」. 숫자 입력 4 → `CAM4`는 현행 `CAM${n}` 변환으로 이미 동작 |
| [frontend/src/PreservedMediaRegistration.tsx:10,28,90](../../../frontend/src/PreservedMediaRegistration.tsx#L10) | 안내에 CAM4(원본 번호 없음) 추가, placeholder `CAM1 / CAM2 / CAM3 / CAM4` |
| [frontend/src/PreprocessingPanelV4.tsx:47](../../../frontend/src/PreprocessingPanelV4.tsx#L47) | 초기 우선순위 `['CAM1','CAM2','CAM3','CAM4', ...연결 영상]` |
| `frontend/src/types.ts` `cameraName` (VC01에서 이동) | 변경 없음. `CAM4`는 그대로 표시 |
| [docs/PILOT_OPERATIONS.md:144](../../../docs/PILOT_OPERATIONS.md#L144) | 파일명 규칙 두 가지와 CAM4 원본 번호 없음 안내(최종 문구는 VC04에서 통합) |

촬영 카메라 이름(복도-정면·테스트룸-입구·참여자-왼쪽·참여자-오른쪽)은 파일명에서 읽히는 설명이며 앱 식별자는 `CAMk`다. 이름 열을 저장하는 필드는 추가하지 않는다.

## 시험

| 파일 | 내용 |
| --- | --- |
| `frontend/tests/upload-guess.spec.ts` | `6_CAM1_복도-정면.mkv`→CAM1·원본 null, `6_CAM4_참여자-오른쪽.mkv`→CAM4, `cam2_x.mp4`→CAM2, `원본1_CAM3.mp4`→제안 없음, `6_CAM10_x.mkv`→CAM10(서버 검사 대상) |
| `frontend/tests/uploads-v4.spec.ts` | 4파일 업로드 → 제안 번호 확인 → 저장 → `camera_id` CAM1~CAM4, `source_original_number` 1/3/2/null |
| `backend/tests/test_preprocess_v4.py` | `setUpClass`의 ffmpeg 합성에 `-f matroska` MKV 샘플 1개 추가(오디오 없음). CAM4 MKV 포함 4대 전처리에서 클립 4개 생성, 오디오 없는 영상의 reason `audio_absent_or_unavailable`, 대표 오디오는 오디오 있는 영상만 |
| `backend/tests/test_uploads_v4.py` | CAM4 연결 시 원본 번호 null, 자동 대응 없음 |
| `frontend/tests/preprocess-v4.spec.ts` | 우선순위 표에 CAM4 행, 위/아래 이동 회귀 |

## 검증과 완료 조건

- VC-T03: 위 시험 통과, `npm run build`, backend 전체 회귀. 합성 MKV의 원본 FPS·AI용 1fps 클립 모두 생성.
- 원본 3대·`원본1/2/3` 파일명 흐름(`recording-split-v4`, `scenario-staff`) 회귀 유지.
- 실제 샘플 MKV 4개로의 로컬 확인은 VC04에서 수행한다.

## 범위 밖

CSV 가져오기(VC03), 카탈로그 `camera_mapping`·`camera_layout_status` 변경(고객 원본 추출값, 변경하지 않음), 오디오 없는 촬영 설정의 해결(운영).

## 2026-10-14 구현 결과

구현·검증·독립 검토 결과는 [실행 기록 §3](K-DOG_4카메라구간CSV구현실행기록_v1.0_20261014.md#3-vc02)를 따른다. 새 의존성0, 고객 카탈로그 변경0, 카메라 수 강제0이다.
