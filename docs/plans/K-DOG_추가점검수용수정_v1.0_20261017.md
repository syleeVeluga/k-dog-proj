# K-DOG 추가 점검 수용 수정 및 검증 기록

버전: v1.0 · 2026-10-17 · 기준: `main / 67c6f98` · 작업 브랜치: `veluga/fix-attachment-startup-install-race`

## 1 범위와 수용 판단

사용자가 추가 점검에서 확정한 다음 두 원인의 수정 → 검증 → 독립 cold review → 수용 보완 → 로컬·원격 병합을 승인했다. 초기 TypeScript 보고의 미검증 후보는 이번 수용 범위가 아니다.

| 항목 | 구체적 결함 | 수용 수정 | 관련 계약 |
| --- | --- | --- | --- |
| A01 | 완료 의견의 AI 해석이 생성한 `attachment_v4`를 구판 실행으로 분류한다. 정상 해석 기록이 있으면 CLI worker 시작이 exit 2로 거절되며, 첫 S1 초기화가 정상 실행·step·감사 기록을 삭제한다. | worker 시작 검사와 초기화의 S1 보존 대상에 `attachment_v4`를 포함한다. 구판이 이미 저장한 초기화 계획을 재사용할 때도 정상 S1 실행과 관련 감사 삭제 항목을 제외한다. | S01 이후 신규 S1 불변 결과 보존, AR-R10·AR-R11 |
| A02 | 설치 B가 설치 루트의 모든 `.tmp-*`를 지워 설치 A의 진행 중 파일을 삭제한다. | 호출별 `TemporaryDirectory`를 소유하고 자신의 staging만 정리한다. 같은 버전이 먼저 설치되면 완료된 대상의 기존 검증을 수행한다. | 배포 D03의 파일 검증·설치 대상 비파괴 |

새 평가 산식·권한 정책·공급자 호출 계약·의존성 변경은 없다. 운영 DB·실제 참가자 자료·외부 공급자는 검증에 사용하지 않는다. 기존에 다른 호출이 남긴 `.tmp-*`는 실행 여부를 구별할 수 없으므로 일괄 삭제하지 않는다. 이번 호출이 생성한 staging은 정상·검증 실패·압축 해제 예외에서 정리하며, 강제 프로세스 종료나 Windows 파일 점유 뒤 잔여 폴더는 자동으로 타 작업의 파일과 함께 지우지 않는다.

## 2 재현과 회귀

- `backend/tests/test_deployment_v4.py`에 실제 S1 완료 의견·기본 결과·합성 AI 응답으로 만든 정상 `attachment_v4`의 CLI worker 재시작 및 첫/반복 초기화 후 run·steps·output bytes·감사 기록 보존 시험을 추가했다.
- `backend/tests/test_issued_release.py`는 두 압축 해제 작업을 `Event`로 확정 순서에 겹쳐 다른 버전/같은 버전의 설치를 검증한다. 기존 검증 실패·경로 이탈 시험은 자기 staging만 제거하고 다른 staging은 보존하는 기대값으로 갱신했다.
- 제품 수정 전에 재시작 exit 2, 초기화 preview의 삭제 후보 1건, 동시 설치 A의 실패를 각각 assertion 실패로 확인했다(3 tests, failures 3, errors 0). 초기 적대적 probe에서도 실제 첫 reset 후 정상 run 삭제를 확인했다.
- 최초 수정 후 배포/설치 좁은 회귀는 8 tests OK였다. 같은 버전 동시 설치 추가 후 확대 회귀 및 source check 결과는 아래에 기록한다.

## 3 의존성 및 런타임 확인

확인일: 2026-10-17. 새 라이브러리 도입 없이 Python 3.14 표준 라이브러리의 임시 디렉터리 context manager를 사용한다. 현재 시험 런타임은 Python 3.14.2이며 프로젝트의 `>=3.14,<3.15` 범위다. 자동 정리·`dir`·`prefix`·`ignore_cleanup_errors` 동작은 [Python 3.14 문서](https://docs.python.org/3.14/library/tempfile.html#tempfile.TemporaryDirectory)로 확인했다.

| 라이브러리 | 공식 레지스트리 최신 안정판 | 선택한 잠금 버전 | 판단 |
| --- | --- | --- | --- |
| [FastAPI](https://pypi.org/project/fastapi/) | 0.143.3 | 0.141.1 | API 변경 없이 기존 fixture/CLI를 검증하므로 기존 프로젝트 잠금 유지 |
| [Pydantic](https://pypi.org/project/pydantic/) | 2.14.1 | 2.13.5 | 모델 API 변경 없이 기존 계약을 재사용하므로 기존 프로젝트 잠금 유지 |
| [cryptography](https://pypi.org/project/cryptography/) | 50.0.2 | 50.0.2 | 봉인·키 API 변경 없음, 기존 잠금이 최신 |

세 라이브러리의 레지스트리 Python 요구 범위는 현재 3.14 런타임을 허용한다. `pyproject.toml`/`uv.lock` 변경이나 설치·업그레이드는 수행하지 않았다.

## 4 검증 결과

- S1 source check: exit 0, 카탈로그·규칙·매핑 8개 source verified. G01/G04 실물 입력 workbook 미수령·물리 주소/수식 확인 대기·Excel import 비활성 경계는 유지한다.
- 최초 확대 회귀: `uv run --locked python -X utf8 -m unittest tests.test_deployment_v4 tests.test_reset_s1 tests.test_attachment_ai_v4 tests.test_issued_release -v` — **50 tests / 86.470초 / OK**. 초기화·구판 차단·원입력/원본·호출 계량·해석 판본·봉인/키·계정 발급·상이/동일 버전 동시 설치를 포함한다.
- 런처 회귀: `uv run --locked python -X utf8 -m unittest tests.test_packaging.LauncherTests -v` — **16 tests / 26.173초 / OK**. 실제 API/worker 시작·중복 실행·강제 종료·잠금 회수와 패키징 검사를 포함한다.
- cold review 보완 후: `uv run --locked python -X utf8 -m unittest tests.test_deployment_v4 tests.test_reset_s1 -v` — **22 tests / 17.760초 / OK**. 저장된 구판 계획 재사용 회귀를 추가했다. 위 실행과 겹치는 시험 수는 합산하지 않는다.
- 최종 관련 회귀 묶음: `uv run --locked python -X utf8 -m unittest tests.test_deployment_v4 tests.test_reset_s1 tests.test_attachment_ai_v4 tests.test_issued_release tests.test_packaging.LauncherTests -v` — **67 tests / 105.517초 / OK**. cold review 보완을 포함한 최종 제품 코드 기준이다. 프런트엔드 소스 변경은 없어 브라우저/UI 전체 시험은 실행 범위에 포함하지 않는다.
- `git diff --check`: 통과.

## 5 독립 cold review와 조치

1차 독립 검토에서 저장된 `s1.reset.plan`의 재사용 경로를 high·확신도 high로 지적했다. 기존 계획이 정상 애착 해석의 run/change IDs를 이미 담은 경우 새 `_plan` SQL을 거치지 않아서 삭제가 남았다. 정상 완료 해석 fixture와 저장 계획으로 별도 probe를 실행해 실행 삭제를 확인했고 수용했다.

`_protect_s1_runs`를 preview/execute에 적용하여 해당 삭제 항목을 실행 시 제외했다. 저장된 원본 계획 event는 수정하지 않고 고정 files 목록도 확대하지 않는다. 실제 현재 참조 closure로 run·steps·부모/output 파일을 보존한다. 새 회귀는 첫·반복 실행, 원본 plan 불변, run·steps·output bytes·감사 기록 보존을 확인한다.

2차 독립 검토: 기존 blocker 해소, 추가 actionable/미해결 지적 **0건**. 독립 배포 회귀 **5 tests / 10.688초 / OK**, 별도 probe에서 정상 run·case 대상 `detail.run_id` 감사 보존 및 원본 plan 불변을 확인했다. 설치의 모든 직접 호출자, 상이/동일 버전 동시 설치, staging rename 뒤 정리 범위도 재검토했다. 실제 제품 파일은 구현 담당만 수정했다.

## 6 병합 기록

수용 수정 및 최종 검증의 제품 코드 commit은 `256ec8479217f10b4c24b5f682db1a990f9eb2bc`이며 통합 이력은 [PR #105](https://github.com/syleeVeluga/k-dog-proj/pull/105)로 연결한다. 같은 PR의 후속 문서 commit은 이 통합 링크만 보완하며 제품 코드·시험 결과는 바꾸지 않는다. 해당 PR의 최종 merge commit을 원격·로컬 `main`의 일치 확인 기준으로 사용한다.

실제 배포 ZIP 발행·고객 전달은 이번 코드 병합 범위에 포함하지 않는다.
