# K-DOG PR-RP02 구현 Cold Review

버전: v1.0 · 2026-10-07 · 기준: `main / edc0d475` 대비 `veluga/rp02-attachment-ai` · 상태: 독립 검토·수용 수정·최종 회귀 완료

상위: [RP02](K-DOG_PR-RP02_AI애착판단_v1.0_20261007.md), [실행 기록](K-DOG_리포트구현실행기록_v1.0_20261007.md).

## 검토와 수용 결정

별도 리뷰 에이전트가 구현 commit `e5278af`의 실행·독립성·판본·예산·수리·공개·삭제·발급 소비 경계를 읽기 전용으로 검토했다. 저장소 밖 임시 DB와 합성 입력에서 재현한 세 건 모두 수용했다. 원본 고객 파일·참가자 자료를 변경하거나 실제 공급자를 호출하지 않았다.

| ID | 우선순위·발견사항 | 결정·적용 | 회귀 확인 |
| --- | --- | --- | --- |
| RP02-CR01 | P2. 완료 의견 해석 POST마다 새 요청 ID를 사용해 저장 후 응답 유실·재클릭에서 중복 실행·비용 가능 | 수용. basic/opinion/viewer fingerprint별 미확인 요청 ID 보존. 종료 후 명시 새 실행은 이전 run을 비우고 새 ID를 만들며 유실 회복에는 그 ID 유지 | `opinions-v4.spec.ts` RP02 시험에서 초기·재실행 응답 유실 주입, ID1=ID2·ID3≠ID1·ID3=ID4 |
| RP02-CR02 | P2. 별도 의견 해석은 영상 bytes/hash만 검사해 수신원장 취소 또는 연결 metadata 변경 뒤에도 채택 | 수용. 기존 `preprocess_v4._source_snapshot`의 live 수신·변환 부모 계보 검사와 반환된 부모 포함 모든 원파일 hash를 공통 guard/최종 채택에서 검증 | `test_receipt_cancelled_during_provider_blocks_adoption`, `test_receipt_camera_metadata_changed_during_provider_blocks_adoption` 및 기존 영상 hash 변경 거절 |
| RP02-CR03 | P2. 사람의 명시 완료 유형이 AI 기본을 대체해도 리포트 사유가 AI 출처로 기록됨 | 수용. 실제 최종 source가 AI 기본 또는 별도 의견 AI 해석인 경우에만 AI 사유 fact/claim 생성. 사람 원문은 의견 출처로 표시 | `test_human_override_has_no_ai_reason_claim_or_fact` 및 네 AI 유형의 리포트 연결 |

CR01의 첫 수정 재검토에서 종료 후 재실행의 유실 경계도 발견해 동일 항목에 반영했다. 독립 재검토에서 세 건의 해결 및 추가 중대 발견 없음이 확인됐다. 보류·불수용 발견사항은 없다.

변경 위치: [별도 실행](../../backend/app/attachment_runs_v4.py), [실제 출처의 리포트 근거](../../backend/app/report_profile_v4.py), [의견 실행 UI](../../frontend/src/FinalResultsV4.tsx).

## 검증과 한계

관련 계약·의견 시험 12개가 12.062초에 통과했다. 독립 검토자가 수신원장 취소·metadata 변경·사람 override 시험 세 개를 다시 실행해 통과했다. 수용 수정 후 backend 66개가 123.283초에 통과했고 frontend build·관련 E2E 7개(44.4초)도 통과했다. 마지막 재실행 유실 보완 후 RP02 E2E 1개가 8.1초에 재통과했다. 초기 확대 backend 171개·추가 실제 조립 시험과 명령은 실행 기록을 따른다.

독립 합성 검증에서는 의견 해석→최종본의 백업·복원과 현재 삭제 상태 재적용에 따른 run·final 제거도 통과했다. 실제 공급자 품질·교수 적절성·시간·가격은 미검증이며 RP05에서 구분한다. 과거 발급 bytes와 원관찰·계산·의견 원문을 보존한다.
