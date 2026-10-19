# PR-AC01 구간 CSV 초안 통합

버전: v1.0 · 2026-10-20 · 상태: **계획 / 구현·시험 미착수** · 기준: `bdc526f` · 직접 선행: 없음

브랜치 제안: `veluga/ac01-recording-csv-draft` · 제목 제안: `refactor: centralize recording CSV draft application`

상위: [전체 계획](K-DOG_아키텍처개선적용계획_v1.0_20261020.md). 요구 AC-R01·R02·R11·R12. 기존 근거: [VC03](../4카메라구간CSV전환_20261014/K-DOG_PR-VC03_구간CSV가져오기_v1.0_20261014.md).

## 1 문제와 완료 결과

`parseSegmentsCsv`는 CSV 형식·구간 시각·평균 offset을 해석하지만, 호출 화면이 미실시 보존·영상 연결·초안 병합·출처 중복 방지까지 알아야 한다. 해석 규칙과 초안 반영 규칙을 `segmentsCsv.ts` module에 함께 두어, 화면이 파일을 읽고 결과를 반영하는 interface로 줄인다.

완료 결과는 같은 CSV와 같은 촬영기록에서 현재와 같은 저장 JSON·요약·경고를 얻는 것이다. 걷기 국면·사건·관찰 근거·꼬리 선택은 기존 수동 입력을 유지한다.

## 2 파일별 변경 계획

| 파일 | 작업 | 확인 근거 |
| --- | --- | --- |
| [segmentsCsv.ts](../../../frontend/src/segmentsCsv.ts#L32) | 기존 parser를 유지하고 순수 초안 계산 함수·반환 타입 추가 | 직접 호출은 화면 importCsv와 parser 시험 |
| [RecordingPanelV4.tsx](../../../frontend/src/RecordingPanelV4.tsx#L89) | 현재 100~115행의 병합·메모·요약 계산을 module 호출로 대체 | bytes 읽기·hash·request/context 검사는 화면 소유 |
| [segments-csv.spec.ts](../../../frontend/tests/segments-csv.spec.ts) | parser 사례를 유지하고 초안 interface의 관찰 결과 시험 추가 | 순수 시험에 DOM·가상 API 필요 없음 |
| [recording-v4.spec.ts](../../../frontend/tests/recording-v4.spec.ts#L9) | 저장·확정 종단 유지, 늦은 파일 읽기/기준 영상 변경 회귀 보완 | 실제 촬영 화면 연결 검증 |
| 이 문서 | 실제 함수명·시험·cold review·commit 기록 | 계획 대비 차이를 설명 |

`recordingTypesV4.ts`·`types.ts`는 기존 타입을 가져오는 참고 대상이며 타입 형식 변경을 계획하지 않는다. 새 파일과 별도 adapter는 필요하지 않다.

## 3 interface와 책임

예정 이름은 `applySegmentsCsvDraft`이며 구현에서 이름은 조정 가능하다. 입력은 **현재 촬영기록, 연결 영상의 video_id/camera_id, CSV 텍스트, 파일명과 원 bytes의 SHA-256**이다. 반환은 **새 촬영기록과 기존 summary 형태(ends·offsets·warnings)**다. 파일·React state·네트워크·시계에 접근하지 않는 순수 함수로 둔다.

- 기준 영상은 기록의 `video_id`로 연결 영상 중에서 찾는다. 기준 camera가 없는 경우 현재 화면의 비활성/무반영 동작을 유지한다. 새로운 가상 camera 또는 기본 영상을 선택하지 않는다.
- module 내부에서 parser를 호출한다. 화면이 다시 segment/offset/출처 규칙을 계산하지 않는다. 기존 `parseSegmentsCsv` export는 직접 시험의 정당한 interface이므로 그대로 유지한다.
- 입력 객체·배열을 변경하지 않는다. 변경 대상만 새 객체로 만들고 반환 기록의 `confirmed`는 false다. 화면은 기존 `change`를 한 번 호출해 dirty와 편집 기준 revision을 함께 갱신한다.
- 화면은 `File.arrayBuffer`, strict UTF-8 decoding, `crypto.subtle.digest`와 오류 표시를 소유한다. 해시는 decoding/re-encoding한 텍스트가 아니라 원 bytes로 계산한다.
- 모든 비동기 작업 뒤 `csvRequest`, case/session, 기록 객체 동일성과 기준 영상 변경에 따른 request 무효화를 확인한 뒤 적용한다. module 호출 결과가 생겼다고 오래된 요청을 반영해서는 안 된다.

## 4 보존할 계산·표시 계약

1. 구간 번호 1~8, 열 이름 기반 해석, 인접 **다음 번호** 시작으로 끝 계산, 누락/퇴장 끝 null, 최소 형식 오류·경고·평균 소수 3자리·편차 0.5초 경고를 보존한다.
2. `not_performed` 구간은 시각/state 모두 기존 값으로 유지하고 기존 경고를 낸다. 누락 구간·CSV와 무관한 수동 사실도 유지한다.
3. 기준 영상 자신의 offset은 채우지 않는다. 연결 영상의 camera에 해당 offset이 있을 때만 교체하며, 나머지 기존 offset과 배열의 현재 유지/추가 순서를 보존한다.
4. 새 offset의 `confirmed: true`, 파일명·hash·camera 차이·편차를 담은 note 형식을 보존한다. 기존 출처 줄의 같은 hash 포함 판단도 현재 동작대로 유지한다.
5. `procedure_note`의 기존 수동 설명을 유지하고 같은 hash를 다시 가져올 때 출처 줄을 늘리지 않는다. 다른 파일명/동일 bytes도 현재 hash 기준을 따른다.
6. summary.ends는 실제 적용한 구간 중 끝이 있는 개수, summary.offsets는 현재 parser의 offset camera 목록이다. 초안 변경 목록으로 새로 해석하여 문구나 숫자를 바꾸지 않는다.
7. 형식 오류·잘못된 UTF-8·가져오는 동안의 편집은 현재 촬영기록을 변경하지 않는다. 자동 저장/확정이나 CSV 서버 업로드를 추가하지 않는다.

## 5 구현 순서

1. Graft callers로 parser/화면 참조를 재확인하고 기존 parser·화면 회귀를 기준 실행한다.
2. 합성 기록을 입력으로 현재 병합 결과를 특징화한다. 특히 미실시·누락·기존 offset·같은 hash·수동 사실을 고정한다.
3. `segmentsCsv.ts`에 순수 초안 동작을 구현하고 화면에서 한 번 호출한다. 비동기 guard의 위치와 기존 `change`·save의 revision 동작을 유지한다.
4. 이전 화면 병합 코드와 이번 변경으로만 쓰이지 않게 된 import/type을 제거한다. 다른 화면 정리는 하지 않는다.
5. 아래 시험·build, 화면 연결 검토, 독립 cold review와 수용 재검증을 수행한다.

## 6 시험과 완료 기준

| ID | 입력/상황 | 기대 결과·주 시험 |
| --- | --- | --- |
| AC-T01 | sample CSV, CAM1/CAM3, 뒤집힌 열·BOM·누락/오류 | 기존 parser 수치·경고 동일; `segments-csv.spec.ts` |
| AC-T02 | 미실시/누락 구간, 수동 사건·걷기·coverage·기존 offset 포함 기록 | 지정 필드만 변경, 입력 불변, confirmed=false, 현재 순서/요약 유지; 같은 파일 |
| AC-T03 | 동일 hash 반복·다른 hash·기준 영상 offset·동일 camera 연결 영상 | 출처 중복 없음, 기준 제외, 해당 영상만 교체; 같은 파일 |
| AC-T04 | 지연된 파일 읽기/hash 중 일반 편집, 또는 기준 영상/대상/회차 변경·새 CSV 선택·화면 해제 | 같은 요청 중 일반 편집은 입력/기존 summary를 보존하고 재선택 오류 표시·busy 종료. 요청 번호가 무효화된 문맥/기준 영상 변경·새 요청·화면 해제는 늦은 결과·busy/error/summary 무반영; `recording-v4.spec.ts` |
| AC-T05 | 합성 4영상 → CSV → 초안 저장 → 불충분 확정 → 수동 보완 확정 | 저장 JSON 동일, 기존 서버 검증 실패/성공·revision 충돌 유지; `recording-v4.spec.ts` |

지연은 확정 순서의 Promise/브라우저 fixture로 만들며 sleep 시간 경쟁에 의존하지 않는다. 기준 데이터는 기존 합성 fixture를 사용한다.

```powershell
# frontend/ — 구현 전 기준 및 구현 후
npm run test:e2e -- segments-csv.spec.ts recording-v4.spec.ts recording-split-v4.spec.ts
npm run build
# 저장소 루트
git diff --check
graft check
```

순수 초안 interface에서 확인한 내부 병합 사례를 화면에서 모두 반복하지 않는다. 화면은 비동기 보호·저장 연결·확정 흐름을 검증한다. 새 동작의 interface가 기존 규칙을 충분히 숨기는지 deletion test로 확인한다.

## 7 위험·되돌림·완료 기록

주요 위험은 출처 문자열·배열 순서·summary 의미의 우발적 변경, 비동기 guard 이전의 state 반영이다. 같은 fixture의 전체 관련 JSON 비교와 지연 시험으로 확인한다. 실패하면 AC01 코드만 되돌린다. 저장 형식 변경이 없으므로 촬영 입력을 재작성하거나 삭제하지 않는다.

- [ ] AC-T01~T05 및 관련 회귀·build 통과
- [ ] 화면에 초안 병합 규칙 중복 없음, 기존 parser 사례 유지
- [ ] 의존성 공식 확인·독립 검토·수용 수정과 재검증 기록
- [ ] source/문구 변경 시 해당 화면 캡처 및 commit/PR 근거

| 실행 항목 | 결과 |
| --- | --- |
| 기준/구현 commit·PR | 미실행 |
| 시험 명령·건수·시간·결과 | 미실행 |
| cold review·발견사항 조치 | 미실행 |
| 계획 대비 변경·후속 | 미실행 |
