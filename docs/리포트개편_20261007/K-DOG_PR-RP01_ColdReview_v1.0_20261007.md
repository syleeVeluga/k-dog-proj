# K-DOG PR-RP01 구현 Cold Review

버전: v1.0 · 2026-10-07 · 기준: `main / aa3f3ac` 대비 `veluga/rp01-survey-policy` · 상태: 독립 검토·수용 수정·재검증 완료

상위: [RP01](K-DOG_PR-RP01_설문응답정책_v1.0_20261007.md), [실행 기록](K-DOG_리포트구현실행기록_v1.0_20261007.md).

## 검토와 수용 결정

별도 리뷰 에이전트가 계획·변경 코드·원입력/산출 판본·hash/권한/삭제 보호를 읽기 전용으로 검토했다. 검증을 통과한 구현에 대해 cold review를 수행하고, 재현한 항목만 수용했다. 저장소 밖 합성 임시 자료와 실제 이전 `main` 함수로 생성한 과거 S1 저장 형식을 사용했다. 실제 참가자 자료·공급자 호출은 사용하지 않았다.

| ID | 우선순위·발견사항 | 결정·적용 | 검증 |
| --- | --- | --- | --- |
| RP01-CR01 | P2. 연구 내보내기 설문은 새 정책으로 계산하지만 `_assets`는 구 정책만 hash로 고정함. 설문·자체 비교 CSV/XLSX에 정책 식별 열도 없음 | 수용. 신규 내보내기 자산을 새 정책으로 pin하고 응답/영역/비교 행에 `survey_version`/`policy_version` 추가 | `test_rp01_exports_pin_actual_policy_and_csv_xlsx_policy_columns`, `test_rp01_policy_change_after_render_cannot_adopt_export` |
| RP01-CR02 | P2. 구 정책 집단과 새 정책 개인 설문을 같은 연구 ZIP으로 저장·다운로드할 수 있음 | 수용. 신규 `_snapshot`에서 자체/외부 비교와 산출 설문의 문항·정책 판본 일치 검사 | `test_rp01_previous_cohort_cannot_join_new_export`, 기존 정확한 외부 범위·철회 회귀 |
| RP01-CR03 | P2. 리포트 hash 계산은 새 정책을 쓰지만 파일 stamp는 구 정책만 포함하여 hash 검사 뒤 새 정책 파일 교체를 놓침 | 수용. 설정에 pin한 정확한 정책 자산을 stamp/hash 검사. 기존 정책 읽기도 해당 자산으로 검증 | `test_rp01_new_policy_file_is_stamped_and_late_change_is_rejected` |
| RP01-CR04 | P2. CR03 수정으로 구 정책 설정 검증이 정상화되면서 기존 발급본에 최신 정책 재생성 안내가 사라짐 | 수용. 과거 설정의 유효성 검증과 최신 runtime 정책과의 차이 판단을 분리 | `test_rp01_previous_policy_report_keeps_bytes_and_requests_regeneration` |

변경 위치는 [내보내기](../../backend/app/exports_v4.py), [내용 자산 선택](../../backend/app/report_profile_v4.py), [리포트 자산·재생성 안내](../../backend/app/report_runs_v4.py)다. 수용 경계 재검토에서 기존 3건의 해결과 CR04의 수정 전/후 재현을 확인했고 추가 중대 결함은 발견하지 않았다. 보류·불수용 발견사항은 없다.

## 재검증과 한계

수용 수정 후 관련 backend 74개가 101.767초에 통과했다. CR04 이후 해당 신규 시험 1개가 3.294초에 통과했고 기존 입력/의견 변경 및 템플릿 변경에 대한 발급 bytes 보존 회귀도 통과했다. 전체 RP01 초기 확대 회귀·frontend·원본 검증은 실행 기록을 따른다.

독립 재현에서는 실제 이전 main 함수로 저장한 구 정책 집단의 조회와 export/report 다운로드 bytes 보존을 확인했다. 자동 회귀에는 백업·복원·삭제 이력·철회 검사를 포함했다. 모든 과거 운영 발급본을 실제 데이터로 재검수하거나 교수님 기준을 확인한 것은 아니다. 최종 원격 검사·병합 상태는 실행 기록과 PR에서 별도로 확인한다.
