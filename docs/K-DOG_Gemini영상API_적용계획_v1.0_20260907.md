# K-DOG Gemini 영상 API 신규 기능 적용 계획

버전: v1.0 · 2026-09-07

## 수용 범위

Gemini 모델을 `gemini-3.8-flash`로 지정하고, 영상 입력의 처리 방식을 `static`(기존 고정 프레임 추출)과 `agentic`(모델이 타임라인을 직접 탐색)에서 선택한다. 영상별 직접 평가 단계의 기본값은 `agentic`으로 하고 `static`을 설정으로 유지한다. `thinking_level`과 `media_resolution`을 개발자 설정에 노출한다. 샘플링 관련 계약(프롬프트 문구·프롬프트 컨텍스트·근거 품질 플래그)은 처리 방식에 맞추어 갱신한다. `store=false`와 원격 파일 삭제, 실행별 설정 스냅샷 고정은 변경하지 않는다. 기존 run의 설정·산출물·플래그는 그대로 보존한다.

영상별 직접 평가 변경 계획의 방향은 그대로 유지한다. 영상 파일마다 행동 55항목과 원문 선택지를 전부 제공하여 각 영상을 독립 평가하고, 항목별로 결과를 병합하며, 선택지가 다른 항목만 영상별 한 차례 재검토한 뒤 해결되지 않으면 보류한다. 이 계획은 그 구조를 바꾸지 않고 한 영상 한 호출의 내부 샘플링 방식과 모델·추론 설정만 바꾼다. 영상당 호출 수·병합 규칙·재검토 범위는 [변경 계획 v1.1](K-DOG_영상별평가_변경계획_v1.1_20260908.md)의 사건 원장·분기 분할이 정하며, 그 세 호출 모두에 이 문서의 요청 계약을 적용한다. 재검토 호출이 전달하는 `focus_intervals`는 `agentic` 탐색의 우선 구간 지시로 그대로 쓰인다.

`agentic`은 장편에서 토큰을 최대 88% 절감하고 품질이 약 7% 높다고 문서가 밝히므로 항목 전체를 한 영상에 제공하는 현재 방식에 유리하다. 다만 구조화 출력과의 병용은 문서에 명시되지 않는다. 따라서 두 방식을 모두 구현하고 **기본값은 검증된 `static`을 유지**하며, `agentic`은 개발자 설정에서 선택한다. 합성 샘플 provider 시험으로 병용을 확인한 뒤 운영 기본값을 바꾼다. 실호출 없이 미검증 경로를 기본값으로 배포하지 않는다.

## 샘플링 계약 갱신

`agentic`은 `fps`·클리핑을 지원하지 않으므로 fps를 전제한 세 곳을 처리 방식 기준으로 바꾼다.

1. 설정: `Pipeline.processing_mode: Literal["static", "agentic"]`을 추가한다. `fps`는 `static`에서만 유효하며 `agentic`과 동시 지정을 `model_validator`에서 거절한다. 기존 저장 초안은 `static`으로 읽는다.
2. 프롬프트 컨텍스트: `sampling_fps: 1.0` 대신 `sampling: {"mode": "static", "fps": 1.0}` 또는 `sampling: {"mode": "agentic"}`을 전달한다.
3. 프롬프트 문구: `sampling_fps`를 설명하는 두 문장을 처리 방식별 문구로 교체한다. `agentic`에서는 모델이 필요한 구간의 프레임·오디오·전사를 직접 선택해 확인하며, 확인하지 못한 구간을 채우지 않고 `coverage`·`coverage_reason`에 남긴다는 지시를 유지한다. 프레임 순번을 초로 쓰지 말라는 금지와 모든 시각이 원본 시작 기준 0~`duration_sec`라는 제약은 두 방식 모두 유지한다.
4. 근거 품질 플래그: `sampling_{fps}fps`를 `sampling_static_{fps}fps` 또는 `sampling_agentic`으로 바꾼다. 관찰 범위의 근거는 플래그가 아니라 항목별 `coverage`가 담당한다.

프롬프트와 설정이 바뀌면 `apply_snapshot`의 단계 해시가 달라져 `prompt_version`·`config_version`이 자동으로 분기한다. 별도 버전 문자열을 손으로 올리지 않는다.

## 요청 계약 갱신

`interactions` 요청에서 다음을 바꾼다.

- 영상 파트: `"processing": {"type": "static", "fps": ...}` 또는 `"processing": "agentic"`. `agentic`은 객체가 아닌 문자열이다.
- `generation_config`: `max_output_tokens`에 `thinking_level`과 `media_resolution`을 조건부로 추가한다. `thinking_level`은 `low|medium|high`만 허용하고 `minimal`은 설정 단계에서 배제한다. `gemini-3.8-flash`는 `minimal`을 오류로 반환한다.
- `media_resolution`은 `generation_config` 전역으로만 지정한다. 파트별 지정은 Gemini 3 전용이며 필드명이 문서 간 상이해 사용하지 않는다.
- `temperature`·`top_p`·`top_k`·`candidate_count`는 계속 전송하지 않는다.
- `Api-Revision` 헤더를 고정 값으로 pin 한다. 헤더 없이 동작하더라도 계약 변동에 영향받지 않게 한다.
- `background=true`는 채택하지 않는다. `store=false`와 비호환이며 참가자 영상 기반 상호작용을 공급자에 저장하지 않는다는 현재 방침과 충돌한다. 대신 `interactions` 호출의 소켓 타임아웃만 900초로 상향한다. 파일 업로드·상태 조회 호출의 120초 타임아웃은 유지한다.

## 사용량·비용 계량

`agentic`은 탐색 추론을 `total_thought_tokens`, 필요 시 적재한 프레임·오디오·전사를 `total_tool_use_tokens`로 계상한다. `token_meters`가 `*token*` 정수를 자동 수집하므로 기록에는 문제가 없으나, 현재 원가 추정은 단가에 등록된 계량만 확인하고 등록되지 않은 신규 계량을 조용히 제외한다. 단가에 없는 token 계량이 사용량에 존재하면 해당 호출을 `unpriced_or_uncertain_calls`로 계상하도록 판정을 보완한다. `gemini/gemini-3.8-flash` 단가와 `as_of`를 등록한다. 도입가는 2026-12-31까지이며 2027-01-01부터 표준 단가가 적용되므로 `as_of`와 함께 명시한다.

## 구현 순서와 완료 기준

1. 설정 계약 확장: `processing_mode`·`thinking_level`·`media_resolution` 추가와 상호배타 검증 → 검증: `agentic`+`fps` 동시 지정 거절, `thinking_level="minimal"` 거절, 기존 초안의 `static` 기본 해석, 스키마 시험 통과.
2. 요청 계약 갱신: 영상 파트·`generation_config`·헤더·타임아웃 → 검증: 요청 본문 단정을 처리 방식별로 분기하고 `store=false` 유지와 키 미노출을 재확인한다.
3. 샘플링 계약 갱신: 프롬프트 문구·컨텍스트·품질 플래그 → 검증: 신규 플래그 단정, 관찰 시각의 `0~duration_sec` 제약과 측정 구간 포함 검증 회귀.
4. 사용량·비용: 신규 계량 수집과 미등록 계량의 불확실 처리 → 검증: `total_thought_tokens`·`total_tool_use_tokens`가 포함된 사용량에서 단가 미등록 시 원가 추정이 완전으로 표시되지 않음을 시험한다.
5. 실호출 검증: 합성 샘플 provider 시험으로 `agentic`과 구조화 출력의 병용을 확정한다. 허용된 실제 3영상으로 `static`/`agentic`을 같은 설정에서 비교하고 항목 선택지 일치율, 보류율, 토큰, 지연을 기록한다. 병용이 불가하면 기본값을 `static`으로 되돌리고 1~4의 설정·계량 변경만 유지한다.
6. frontend 타입·입력 필드와 build/e2e, 기존 실행 회귀, 독립 cold review 후 commit·push.

## 유지할 규칙

영상마다 전체 평가 항목을 제공하고 영상별 평가를 항목별로 다시 병합하는 구조를 유지한다. 영상 파일 결합·전체 자동 동기화는 하지 않으며, 평균·최댓값·다수결·모델 자신감으로 선택지를 정하지 않는다. 원문 55항목·선택지·점수와 DOG-12/OWN-14 보류는 변경하지 않는다. 실행별 설정 스냅샷 고정, 성공 단계 재사용, 호출 예산, 점유·중지·삭제 검사를 유지한다. `store=false`, 원격 파일 삭제, 키 비저장, 사용량의 키·URL·파일명 삭제를 유지한다. 관찰 범위 없이 채점하지 않으며 한 시야의 가림·미녹화를 검사 미실시로 판단하지 않는다. 기존 run의 산출물·플래그·버전 문자열은 재작성하지 않는다.

## 영향 파일

- [backend/app/gemini.py](../backend/app/gemini.py): `interaction_request`(80), `configuration`(113), 소켓 타임아웃(144), 영상 파트(242)
- [backend/app/settings.py](../backend/app/settings.py): `StageConfig`(19), `Pipeline`(26), `fps`(33), `apply_snapshot`(195)
- [backend/app/worker.py](../backend/app/worker.py): 관찰 컨텍스트(184), 품질 플래그(195), 영상별 컨텍스트(331), 품질 플래그(351)
- [backend/app/video_evaluation.py](../backend/app/video_evaluation.py): `PROMPT`의 샘플링 문구(18~19), `context`(42~49)
- [backend/app/usage.py](../backend/app/usage.py): 단가 판정과 불확실 처리
- [backend/app/developer_sample.py](../backend/app/developer_sample.py): 합성 샘플의 처리 방식 전달(41~44)
- [frontend/src/DeveloperSettings.tsx](../frontend/src/DeveloperSettings.tsx): `Pipeline` 타입(7), 한도 입력(66)
- 시험: `test_observation.py`(428~430), `test_settings.py`(131), `test_video_evaluation.py`(72, 179), `pilot_scenario.py`
- 문서: [M2 구현기록](K-DOG_M2_구현기록_v1.0_20260906.md), [M3 구현기록](K-DOG_M3_구현기록_v1.0_20260906.md), [영상별평가 구현검증](K-DOG_영상별평가_구현검증_v1.0_20260907.md)

## 미확인 항목

- `agentic`과 `response_format` 스키마 강제의 병용: 문서에 기재가 없다. 5단계 합성 시험으로 확정하며 계획의 게이트로 둔다.
- `agentic`의 실제 지연 상한: 문서는 스트리밍 또는 백그라운드를 권고하나 상한을 밝히지 않는다. 타임아웃 값은 5단계 실측으로 정한다.
- 영상 파트별 해상도 필드명이 안내 문서(`media_resolution`)와 API 참조(`resolution`)에서 다르다. 전역 지정만 사용해 회피한다.
- `Api-Revision` 헤더의 필수 여부. 값이 명시된 예시가 있으므로 pin 한다.

## 의존성 확인

2026-09-07 확인. 신규 의존성을 추가하지 않으며 잠금 버전을 유지한다. Gemini 계약은 [영상 이해](https://ai.google.dev/gemini-api/docs/video-understanding), [최신 모델](https://ai.google.dev/gemini-api/docs/latest-model), [모델 목록](https://ai.google.dev/gemini-api/docs/models), [미디어 해상도](https://ai.google.dev/gemini-api/docs/interactions/media-resolution), [구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output), [백그라운드 실행](https://ai.google.dev/gemini-api/docs/background-execution), [Interactions API 참조](https://ai.google.dev/api/interactions-api)의 현재 REST 계약을 따른다. `gemini-3.8-flash`는 2026-09-02 정식 공개이며 컨텍스트 1M, 최대 출력 64k, 기본 `thinking_level`은 medium이다. 현재 설정 상한 65536과 일치하므로 출력 한도는 조정하지 않는다. 실제 검증 도구 버전과 결과는 구현 기록에 남긴다.
