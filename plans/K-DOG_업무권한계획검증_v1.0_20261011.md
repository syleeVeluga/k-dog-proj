# K-DOG 업무 권한 단순화 계획 검증 대장

버전: v1.0 · 2026-10-11 · 대상: 계획 문서 PR · 제품 AR01~AR07 구현/시험 미실행
상위: [전체 계획](K-DOG_업무권한단순화계획_v1.0_20261011.md), [Cold Review](K-DOG_업무권한계획ColdReview_v1.0_20261011.md).

## 1 문서 범위와 기준

- 조사 기준 d6dd58a, 문서 브랜치 veluga/access-audit-plan, 문서 작업 기준 f2b79d9.
- plans의 전체 계획 1개·개별 PR 7개·검증 대장·cold review 기록을 대상으로 한다.
- 진행 중인 로컬 U08 제품/시험/UIUX 문서 변경은 이 문서 PR에 포함하지 않는다.
- 코드 탐색은 Graft의 exhaustive 검색/호출 관계 및 HEAD 정확 범위로 확인했다. 별도 backend/UI·보관 범위 조사로 소유 조건·동의/삭제·복원 purge·설치 계정·테스트 정리의 누락을 보완했다.
- 새 라이브러리 설치·제품 프레임워크 API 사용·유료 호출·실자료 읽기/변경·고객 발송은 수행하지 않았다. 평가 원본의 hash 재검증은 이번 운영 정책 계획의 검증 근거에 포함하지 않는다.

## 2 실행 결과

| 검사 | 실제 결과 |
| --- | --- |
| 상대 문서/코드 링크 작업 파일 검사 | 문서 10개·상대 링크 82개, 누락 0 |
| staged/committed tree 상대 링크 | Git index 및 문서 commit 24b6053의 상대 링크 82개, 누락 0 |
| 개별 PR 7개·선행 DAG·AR-R01~R12 연결 | 개별 문서 7개 목적/변경/검증/인수/복구 확인, 위상 순서 AR01→AR02→AR03/AR04→AR05→AR06→AR07, 순환 0; R01~R12 담당 연결 검토 |
| 계획의 기존 시험 모듈·frontend 명령 대상 | 기존 Python 시험 모듈 25개·E2E 파일 10개 모두 존재. test_activity_v4는 AR02 미래 신규 생성 항목으로 명시 |
| 계획/제품/실측 완료 경계 | 전 문서에서 제품 구현 미착수·미실행 명시 |
| git diff --check | staged diff 검사 통과. 최초 EOF 빈 줄 7개 수정 후 재검증 |
| 독립 cold review 및 수용 건 수정 | P2 2건 수용 수정, 독립 재검토에서 두 건 해결·새 actionable 잔여 0. [별도 기록](K-DOG_업무권한계획ColdReview_v1.0_20261011.md) |
| 원격 PR·최종 head·병합 | [문서 PR #72](https://github.com/syleeVeluga/k-dog-proj/pull/72). 생성 후 head 24b6053·base f2b79d9·CLEAN/MERGEABLE·checks 없음 확인. 이 기록의 commit을 포함한 최종 head를 재확인하여 병합하며 최종 head/merge SHA와 병합 시각은 PR 메타데이터 및 작업 완료 응답을 따른다 |

계획 검증·cold review·수용 수정·최종 재검증을 완료했다. 초기 index 검사기의 Git 한글 경로 인용 처리를 core.quotepath=false로 바로잡아 누락 0을 확인했다. 최종 staged 문서 10개·상대 링크 82개 누락 0·plans 외 변경 0·diff check 통과를 확인했다. 앱 단위/전체 backend/E2E/ZIP 검증은 AR01~AR07 구현 시 수행할 미래 항목이다.

PR에 plans 10개만 포함되는 것을 원격 파일 목록으로 확인했다. 원격 CI/check가 없으므로 CI 통과로 표시하지 않는다. GitHub 연결 도구의 PR 생성 403은 로컬 GitHub CLI로 생성하여 해결했다. 기존 로컬 U08 작업 브랜치를 전환·커밋·병합하지 않고 문서 전용 worktree에서 수행했다.

## 3 검증 방법과 범위

PowerShell과 Git의 읽기 검사로 plans Markdown의 로컬 상대 링크를 추출해 실제 파일 및 Git index/committed tree에 존재하는지 검사한다. 원격 URL은 로컬 경로 검사에서 제외한다. 코드 줄 링크는 조사 기준을 표시하며 실제 구현 착수 시 최신 파일의 symbol/caller를 다시 확인한다. 문서가 인용한 제품 심볼의 수정이나 실행은 없다.

PR 7개의 순서/선행이 순환하지 않는지, 각 문서의 목적·상세 변경·검증·인수·복구가 있는지 확인한다. 고정 시험 명령의 기존 Python 모듈과 frontend 파일은 실제 경로를 확인하고 미래 생성 시험은 신규로 표시한다. 구 동의·삭제·배정 정책을 새 인수 기대값으로 재사용하지 않는지 검토한다.

계획 문서는 사용자 새 결정의 우선순위를 명시했다. 현행 앱의 AGENTS/운영 안내 변경은 AR06/AR07 제품 적용 때 함께 수행하도록 담당을 연결했으며 과거 시험 기록을 소급 수정하지 않는다.
