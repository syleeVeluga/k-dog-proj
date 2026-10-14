# PR-VC03 구간 CSV 가져오기

버전: v1.0 · 2026-10-14 · 상태: 계획 · 선행: [VC02](K-DOG_PR-VC02_4카메라식별과전처리기본값_v1.0_20261014.md) 병합 · 브랜치 제안: `veluga/vc03-segments-csv` · 제목 제안: `feat: fill S1 capture segments and offsets from the recording tool CSV`

상위: [전체 계획](K-DOG_4카메라구간CSV전환계획_v1.0_20261014.md) §4.2. 범위: VC-R04/R05. 형식 근거: [`segments.csv`](../확정%20영상%20및%20구분_20261014/segments.csv).

## 문제와 결과

촬영 기록 화면은 8구간 시작·끝과 다른 카메라 offset을 손으로 입력한다. 녹화 도구가 같은 값을 CSV로 내므로 이를 읽어 초안을 채운다.

결과: 「촬영 기록 (8구간)」의 실제 8구간 섹션에 「구간 CSV 가져오기」 파일 입력이 생긴다. 기준 영상을 고른 뒤 CSV를 선택하면 7구간의 시작·끝, 퇴장 시작, 다른 연결 영상의 offset이 채워지고 요약이 표시된다. 저장·확정은 기존 버튼과 서버 검증 그대로다. 백엔드 변경은 없다.

## 계약 (프런트 전용)

새 모듈 `frontend/src/segmentsCsv.ts`:

```ts
export type SegmentsCsvResult = {
  segments: { segment: SegmentId; start_sec: number; end_sec: number | null }[]; // 구간번호 순
  offsets: { camera_id: string; offset_seconds: number; spread: number }[];       // 기준 카메라 제외
  warnings: string[];                                                             // 이름 불일치·누락 구간·열 없음 등
};
export function parseSegmentsCsv(text: string, referenceCamera: string, linkedCameras: string[]): SegmentsCsvResult; // 형식 오류는 throw
```

- 입력: 파일 텍스트(UTF-8, BOM 제거), 기준 영상의 `camera_id`, 회차에 연결된 다른 영상의 `camera_id` 목록.
- 파싱: 첫 행을 머리글로 읽어 열 이름으로 접근한다. 따옴표·쉼표 포함 셀을 처리하는 작은 CSV 분리 함수를 포함한다(의존성 추가 없음).
- 대상 행: `종류 === '구간'`이고 `구간번호`가 1~8인 행. 같은 번호가 두 번이면 오류. `구간번호` k → `SEGMENTS_V3[k-1]`.
- 시작: `${referenceCamera}_영상초` 열. 열이 없으면 오류(「기준 영상 카메라 CAM? 열이 CSV에 없습니다」).
- 끝: 다음 번호 행의 시작. 8번 퇴장의 끝은 `null`. 시작이 비단조이면 오류.
- 누락 번호: 경고하고 해당 구간은 건드리지 않는다.
- `구간이름`이 `SEGMENTS_V3` 라벨의 앞글자와 다르면 경고(예 「낯선 사람」은 「낯선」과 일치로 본다).
- offset: 연결된 각 카메라 `CAMk`에 `CAMk_영상초` 열이 있으면 행별 `CAMk − 기준` 평균(소수 3자리)과 최대 편차(`spread`). 열이 없으면 경고. 편차가 0.5초를 넘으면 경고만 하고 값은 채운다(사용자 결정: 값 방어는 최소).
- `경과초(녹화시작기준)`·`시각`·`중단사유`·`취소대상순번`·`메모`는 읽지 않는다. `종류`가 `구간`이 아닌 행은 무시하고 종류 값을 경고에 나열한다(보완 요청의 근거).

## 화면 적용 (`RecordingPanelV4.tsx`)

- 실제 8구간 `details` 안에 `<input type="file" accept=".csv" aria-label="구간 CSV 가져오기">`와 요약 영역을 둔다. 기준 영상이 없거나 `camera_id`가 없으면 비활성.
- 적용 시 `change({...record, ...})`로 한 번에 반영한다.
  - `segments`: 파싱된 구간의 `start_sec`/`end_sec`를 채우고 `state`가 `not_performed`인 구간은 `performed`로 되돌리지 않고 경고만 한다.
  - `video_offsets`: 연결 영상 중 `camera_id`가 일치하는 것에 `{ offset_seconds, confirmed: true, note: 'segments.csv <파일명> SHA-256 <hash> · CAMk_영상초−CAM기준_영상초 평균, 편차 <spread>초' }`. 기준 영상 자신은 제외.
  - `procedure_note`: 끝에 `\nsegments.csv <파일명> SHA-256 <hash>` 추가(중복 방지: 같은 hash 줄이 있으면 생략).
  - `confirmed: false`(기존 `change`가 이미 보장).
- 해시는 `crypto.subtle.digest('SHA-256', bytes)`. 파일은 서버에 보내지 않는다.
- 요약: 「채움: 구간 7개 끝 유도, 퇴장 끝 미입력 / offset CAM2·CAM3·CAM4 / 채우지 못함: 걷기 6국면, 사건, 관찰 근거」 + 경고 목록. 형식 오류면 `role="alert"`로 표시하고 아무것도 바꾸지 않는다.
- 기준 영상을 바꾸면 기존 동작대로 구간 시각이 비워지므로 CSV를 다시 가져오게 안내한다.

## 변경 없는 것

- 서버 계약 [recording_v4.py:33-108](../../../backend/app/domain/recording_v4.py#L33-L108)·[160-266](../../../backend/app/domain/recording_v4.py#L160-L266), 저장 API, 길이·hash 검증, 확정 조건(걷기 6국면·사건 요구)은 그대로다.
- 걷기 국면·사건·관찰 근거·꼬리 선택·안전기지는 수동 입력이다.
- 샘플 CSV는 시험 fixture `frontend/tests/fixtures/segments-sample.csv`로 복사한다(개인정보 없음).

## 시험

| 파일 | 내용 |
| --- | --- |
| `frontend/tests/segments-csv.spec.ts` (순수 함수) | 샘플 → 기준 CAM1: entry 10.356~51.146 … stranger 250.732~299.898, exit 299.898~null; offsets CAM2 0.069, CAM3 −0.118, CAM4 −0.016(편차 ≤0.01). 기준 CAM3: 시작이 CAM3 열, offset CAM1 +0.118. BOM 유무, 열 순서 바꿈, 구간 누락(경고), 중복 번호(오류), 기준 열 없음(오류), `종류=중단` 행 무시+경고, 이름 불일치 경고 |
| `frontend/tests/recording-v4.spec.ts` 추가 시나리오 | 합성 4영상(CAM1~CAM4) 업로드·연결 → 촬영 기록 열기 → 기준 CAM1 선택 → CSV 선택 → 구간 입력값·offset 체크박스 확인 → 퇴장 끝 입력 → 저장 → 걷기 국면 없이 확정 시 기존 오류 메시지 → 국면·필수 사건 입력 후 확정 성공. 합성 영상 길이는 CSV 시각을 덮도록 ≥ 300초 대신, 시험 전용 짧은 CSV(시작 1·2·…·8초)를 별도 fixture로 둔다(`segments-short.csv`) |
| `frontend/tests/copy-guard.spec.ts` | 새 문구에 장치 연결·자동 판독 표현 없음 |

backend 시험 변경 없음. 기존 `test_recording_v4`의 길이 초과 422는 CSV 값이 영상 길이를 넘는 경우를 그대로 막는다.

## 검증과 완료 조건

- VC-T04: 위 시험 통과, `npm run build`. 샘플 CSV로 채운 초안이 수동 입력과 같은 JSON으로 저장된다(새 필드 없음).
- VC-T05: 걷기 국면·사건 없이 확정 불가, 수동 입력 뒤 확정.
- 실제 샘플 4MKV+CSV 로컬 확인은 VC04.

## 범위 밖

CSV 서버 보관 API, 걷기 국면·사건·중단 행 파싱(보완본 수령 뒤 별도 PR), offset 자동 검증 강화, 녹화 도구 수정.
