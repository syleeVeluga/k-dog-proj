# K-DOG 360 통합 MP4 계획 Cold Review

버전: v1.0 · 2026-10-12 · 상태: 독립 검토·수용 수정·재검토 완료 · 기준 코드: `1702f2b` · 상위: [전체 계획](K-DOG_360통합MP4업로드계획_v1.0_20261012.md)

## 검토 기준

사용자 요청한 단일 통합 MP4 업로드 옵션이 원본 사전 등록 없이 완료되는지, 출처/시각/투영의 사실을 발명하지 않는지, 기존 부모 계보·S1 판본/hash·actor·snapshot 보관을 유지하는지 검토한다. 계약/저장·UI·통합 인수의 PR 선행, 실제 360 품질과 합성 기술 인수의 분리, 불필요한 SDK/승인/마이그레이션 확대도 확인한다.

기존 [계획 Cold Review](../K-DOG_업무권한계획ColdReview_v1.1_20261011.md)의 작성자와 다른 reviewer 절차를 사용한다. reviewer는 계획·기준 코드를 읽기 전용으로 검토하며 제품을 구현하거나 앱/실자료/공급자를 실행하지 않는다. actionable 발견별 수용/보류/거절과 수정 뒤 확인을 이 문서에 기록한다.

## 발견과 결정

작성자와 다른 독립 reviewer `cold_mp4_plan_review`가 계획6개와 Graft로 조회한 기준 코드의 업로드·전처리·촬영 시각 검증/호출자를 읽기 전용 검토했다. actionable 발견 2건(P1 1·P2 1)을 모두 수용했다. 보류/거절은 없다.

| ID / 등급 | 발견과 코드 근거 | 수용 수정·계획 인수 |
| --- | --- | --- |
| CR-MP01 / P2 | unknown으로 먼저 등록한 동일 파일의 나중 확인 경로가 없었다. 새 요청 재업로드 안내와 동일 hash의 metadata 차이409가 충돌. `uploads.link_receipt:358–363`, `register_preserved_video:415–416,448–451`의 기존 출처 불변 계약이 실제 근거 | 원래 업로드 원장/bytes/kind/계보를 유지하고 external_processing만 같은 video/hash의 새 S1 입력 revision/기존 changes actor로 확인·정정하는 작은 PATCH/API/UI. raw declaration과 pinned effective metadata의 검증을 분리하고 old batch는 stale/새 전처리 명시. 전체 §3.3, [MP01](K-DOG_PR-MP01_외부처리MP4계약과보관_v1.0_20261012.md) 구현5–6/VM-T07, [MP02](K-DOG_PR-MP02_단일파일업로드화면_v1.0_20261012.md) 흐름7, [MP03](K-DOG_PR-MP03_통합인수와배포_v1.0_20261012.md) 정정 인수 |
| CR-MP02 / P1 | 편집/미확인 통합본의 클립을 제외해도 그 파일의 기준/사건 시각이 정상 view 관찰창을 잘못 만들 수 있었다. `recording_v4.validate_recording_media_v4:235–268`은 storage_only/hash/길이만 확인. `RecordingV4.event_times`→`build_windows_v4`→`preprocess_v4._prepare_clips:282–283`의 시각 전파가 실제 근거 | 기준 영상뿐 아니라 사건·관찰 근거·확인 offset의 실제 시간 앵커도 확정/전처리에서 검증. 초안/값 없는 미확인 목록과 실제 시간 의존성 구분, 정상 시간 근거로 변경·재확정 안내. equirectangular+preserved의 시각 근거 및 무관한 사람 업무 유지. 전체 §3.3, MP01 구현7/VM-T04, MP02 흐름6, MP03 mixed view 인수 |

CR-MP02의 공통 validator callers는 `capture_v4.save`, `judgements_v4.create`, `sheets_v4.assign/revise`다. 이를 구현 회귀에 포함해 파일별 기술 제한이 전체 사람 업무 차단으로 확대되지 않게 했다.

## 최종 상태

수용 수정 후 같은 reviewer가 전체·MP01·MP02·MP03와 이전 코드 근거를 대조하여 **기존 발견 2건의 계획 수준 해결, 신규 actionable0**을 확인했다. 별도 입력 종류·기존 부모 불변·EXT360 의미·기존 JSON/hash 보존·파일별 서버 제한/재사용·snapshot 보관·공통 업무·UI 요청 고정·3PR 선행·실측 분리를 함께 확인했다.

reviewer는 파일을 편집하거나 제품 구현·앱 시험·공급자 호출을 수행하지 않았다. Graft는 wiring sync OK를 반환했으며 concept manifest 부재는 심층 요약 미생성 상태로 구분했다. 이번 작업은 코드 변경이 없어 graph build를 실행하지 않았다. 문서 검증은 별도 검증 기록을 따른다.

실제 Studio 파일의 projection·편집 시각·코덱·오디오·품질은 계속 미확인이다. 이 계획 검토 완료는 MP01~MP03 구현·제품 시험·실제 품질·배포 완료가 아니다.
