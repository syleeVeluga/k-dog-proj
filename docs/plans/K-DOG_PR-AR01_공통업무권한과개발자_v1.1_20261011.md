# K-DOG PR-AR01 공통 업무 권한과 개발자

버전: v1.1 · 2026-10-11 · 상태: 구현·검증·독립 cold review·수용 수정·문서·병합 완료 (PR #75, merge `af91032`) · 선행: 없음
상위: [업무 권한 단순화 계획](K-DOG_업무권한단순화계획_v1.1_20261011.md). 조사 기준 `main / 7d0904e` (U08·U09 병합). 실제 착수 시 최신 호출 관계를 다시 확인한다.

실행 근거: [업무 권한 구현 실행 기록](K-DOG_업무권한구현실행기록_v1.0_20261011.md). 아래는 원계획이며 실제 구현·시험·수용 판단·후속 경계는 실행 기록을 따른다.

## 1 목표·현재 근거

reader=operator/reviewer/admin, writer=operator/admin, administrator=admin, developer=developer인 [API 정의](../../backend/app/api.py#L142-L157)가 개발자의 업무 접근도 막는다. [계정 모델](../../backend/app/input_models.py#L14-L42), [인증](../../backend/app/auth.py), [계정 UI](../../frontend/src/Users.tsx), [설정 검사](../../backend/app/settings_v4.py#L124-L127), [로컬 계정 CLI](../../backend/app/manage.py)를 함께 대상으로 한다.

목표는 하나의 로그인 업무 범위와 개발자 설정 범위 두 가지뿐이다. operator/reviewer/admin의 명칭이 권한 차이로 남지 않는다.

## 2 상세 변경

1. API의 업무 Depends와 각 모듈 내부 재검사를 모든 활성 로그인 계정으로 통일한다. 신규 일반 계정의 저장값은 기존 `operator`를 그대로 재사용하고 화면에는 공통 업무 계정으로 표시한다. 기존 reviewer/admin/operator는 권한 차이 없이 읽고 developer는 설정 구분만 추가한다. 새로운 role literal을 도입하지 않으며 input_models.Role·users.role CHECK와 FK/기존 계정값은 유지한다. 대규모 DB 역할 재작성은 하지 않는다.
2. 개발자도 전체 reader/writer/계정/백업/비교 업무가 가능하다. 공급자 키·모델/프롬프트/AI 단계 설정만 기존 개발자 전용을 유지한다.
3. 기존 웹 계정 생성·활성 관리 기능을 모든 업무 사용자에게 제공하고 기존 actor·대상·변경 action을 재사용한다. UI의 일반 역할 선택만 제거한다. 현재 없는 이름 변경·타인 비밀번호 편집·계정관리 승인 기능은 신설하지 않는다. 비밀번호/hash/session token은 기록하지 않는다.
4. 일반 계정 생성/수정으로 developer 값을 넣는 우회와 기존 개발자 계정 변경을 막는다. 개발자 발급/설정 계정 변경은 기존 로컬 경로를 유지한다. 이는 설정 보호 범위이며 업무 자료의 소유 권한을 되살리지 않는다.
5. 자신 또는 마지막 로그인 계정 변경의 제약이 있다면 업무 역할 유지 명분은 제거하고 로그인 연속성에 필요한 구체 조건만 남긴다. 사용자 동작을 다시 관리자 승인으로 연결하지 않는다.
6. `reset_s1._actor`, `maintenance.offline`, CLI actor 검사·발행/설치 계정 provisioning을 점검한다. S1 점수 초기화는 실행하지 않는다. 기존 `--admin`/admin bootstrap 저장값은 호환 내부 값으로 유지 가능하며 초기 업무 계정이라는 안내와 동일 업무 접근을 확인한다. 불필요한 패키지 포맷/CLI 역할값 재설계는 하지 않는다.
7. 계정 활성/세션은 요청한 실제 actor의 인증만 검증한다. 자료 작성자의 계정이 비활성이거나 과거 배정이 취소되었다는 이유로 다른 사용자의 자료 접근을 거절하지 않는다.

수정 전에 graft callers `create_app.roles`, `sheets_v4.manager`, `settings_v4._developer`, `auth.provision_accounts`를 확인한다. manager/owner 등 이름만 유지하면서 기존 정책을 숨기지 않는다. 후속 AR03/AR05가 자료 소유 조건을 제거할 때까지 계정 공통화와 소유 조건의 상태를 구분한다.

## 3 검증과 인수

backend에서 기존 4종 active 계정 각각 접수·수정·채점 API 입구·리포트 API 입구·계정·백업에 도달하는 동일 기대값을 검증한다. 신규 공통 계정의 operator 저장·계정 생성/로그인·발행/provision 재설치가 현 users CHECK/Role Literal로 성공하고 기존 reviewer/admin 계정의 값과 비밀번호가 그대로 유지되는지 확인한다. 미로그인/만료 세션은 401, 일반 계정의 key/settings 및 developer 승격은 거절, 개발자는 업무+설정 성공이어야 한다. 무효 계정은 요청 actor 인증에만 영향이 있어야 한다.

`uv run --locked python -X utf8 -m unittest tests.test_intake_api tests.test_settings tests.test_settings_v4 tests.test_issued_release -v`에 기존 assertion을 최신 정책으로 갱신한 관련 회귀를 실행한다. 신규 `test_business_access_v4.py`는 실제 HTTP 계정별 통합 시나리오로 작성한다. 단순 allowed tuple을 복사하는 시험은 만들지 않는다. UI 변경은 build와 계정/설정 화면의 관련 E2E로 확인한다.

완료: 일반 role에 의한 업무 403 제거, 개발자 업무+설정 정상, 설정 승격 우회 없음, 기록 actor 정확. 제품 코드·시험·운영 문서 중 관련 범위만 변경한다. 배포는 AR07까지 대기한다.

## 4 실패·복구

계정 삭제/재발급이나 비밀번호 일괄 변경을 하지 않는다. 기존 계정 문자열을 읽지 못하면 원인을 고치고 다시 검증한다. 전환 전 운영 백업으로 격리 복구하며 공유 업무 데이터를 역할별로 분할하는 대체안은 도입하지 않는다.
