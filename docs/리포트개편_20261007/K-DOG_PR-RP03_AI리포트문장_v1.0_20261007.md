# PR-RP03 AI 리포트 문장 생성과 실행 연결

버전: v1.0 · 2026-10-07 · 상태: 계획·미구현 · 선행: RP02

상위: [수용안 적용 계획](K-DOG_리포트수용안적용계획_v1.0_20261007.md). 연결: A02/A06, G02/P08, R18/R21~R23, T16/T27/T31, RP-T06~08.

브랜치 제안: `veluga/rp03-report-narrative` · PR 제목: `feat: generate report narratives from pinned evidence`

## 문제와 목표

현재 리포트는 고정 템플릿 중심이며 자유 문장은 `deferred_S16`, 문장은행은 `pending_G02`다. 회신에 따라 확인된 사실·최종 판단에 근거한 설명·총평·실천 조언을 AI가 생성하게 한다. 126개 후보는 선택 자료이며 전 항목의 문장 생성 또는 별도 문장은행 구축을 요구하지 않는다.

## 변경 범위

| 기존/제안 파일 | 변경 내용 |
| --- | --- |
| 신규 제안 `backend/app/report_narrative_v4.py`, `resources/report/content-20261007.json` | 근거 선택·구조화 문장 응답·생성 지침·검증. 기존 파일의 출처/판본과 구분 |
| `backend/app/report_profile_v4.py`, `backend/app/domain/report_profile_v4.py` | 사실 profile과 AI 문장 결과/출처를 분리. G02 제공 대기를 새 생성 상태로 변경 |
| `backend/app/report_runs_v4.py`, `backend/app/domain/report_runs_v4.py`, `backend/app/worker.py` | content 단계 AI 실행, 입력/출력 hash, 검증·재사용·게시 연결 |
| 기존 공급자 전송·설정·예산 모듈, `backend/app/maintenance.py` | 보호장치를 재사용한 텍스트 요청, 새 산출물의 백업·삭제 참조 |
| 신규 제안 `backend/tests/test_report_narrative_v4.py`, 기존 내용/검증/실행/API 시험 | 생성 성공·실패·수리·입력변경·중복·출처·내용 고정 검증 |

## 구현 순서

1. RP01 설문과 RP02 최종 결과에서 허용 근거를 구성한다. 근거 ID·관찰/설문 구분·사용할 계산값·유형·완료 의견·보류 사유만 전달하고 견본 사례·내부 메모·미확정 수치를 제외한다.
2. 반환 구조는 결과별 설명, 필요한 세부 설명, 총평, 근거 있는 실천 1~3개 및 각 문장의 근거 ID로 제한한다. 근거가 없으면 해당 영역의 자료 부족 설명을 사용하며 3개 조언을 억지로 채우지 않는다. 완료 D39와 영역 의견의 우선순위를 유지한다.
3. AI는 척도·분모·백분위·확률·새 최종 유형을 생성하지 않는다. 수치는 프로그램이 고정한 값을 사용한다. 읽기 쉬운 문장 길이·친근한 어조는 지침과 테스트 예제로 관리하고 교수 피드백을 지침 판본에 반영한다.
4. 신규 AI 산출물은 `content_v4` 계열 실행 단계의 불변 결과로 저장한다. **고정 입력 profile을 덮어쓰지 않는다.** 현재 `process`의 게시 profile==입력 profile 검사는 생성 내용의 별도 hash/ref와 원근거 연결 검사로 개정해야 한다. 입력 snapshot→생성 결과→검증 결과→HTML/PDF/manifest의 연결을 모두 고정한다.
5. 모델/프롬프트/근거/최종 의견/설문 정책이 바뀌면 내용 재사용을 거절한다. 단순 렌더·다운로드는 이미 저장된 문장을 사용하고 AI를 재호출하지 않는다. 명시적 재생성만 새 실행으로 만든다.
6. 알 수 없는 근거 ID, 유형 불일치, 숫자 변조, 누락을 0으로 표현, 내부 메모/예시 문구, HTML 삽입을 검사한다. 문자열·스키마 검사만으로 모든 의미적 오류를 잡는다고 가정하지 않으며 교수 검토 사례를 추가한다.
7. 공급자/계약 검증 실패는 실패 또는 검토 필요로 표시하고 정상 AI 작성 완료로 위장하지 않는다. 이미 검증된 동일 입력 결과의 재사용은 기존 명시 재사용 규칙에 따른다. 데이터 부족과 공급자 장애를 구분한다.

## 검증과 완료 조건

- RP-T06~08과 카드/총평/실천의 동일 최종 유형, 허용 근거만의 사용을 검증한다.
- 응답 유실·timeout·취소·삭제·만료 token·수정 경합에서 중복 과금/오채택 방지 계약을 유지한다. 새 AI 단계를 호출 예약·사용량·상태 화면에 포함한다.
- HTML/PDF 렌더링 전후의 내용 hash가 같으며 교수 수정 후에는 새로운 지침/실행 판본을 사용한다.
- 상태 `pending_G02` 제거만으로 끝내지 않고 실제 공급자 adapter와 fixture 종단 시험을 갖춘다. 실제 공급자 품질 확인은 RP05로 분리한다.

구현 후 backend에서 `uv run --locked python -X utf8 -m unittest tests.test_report_narrative_v4 tests.test_report_content_v4 tests.test_report_validation_v4 tests.test_report_runs_v4 tests.test_report_api_v4 -v`를 수행한다. `test_report_narrative_v4`는 신설 예정이며 현재 실행하지 않았다. 변경한 공급자·백업/삭제 경로의 기존 관련 시험도 Graft 영향 범위에 따라 추가한다.

## 인계

RP04에 장면 없이도 소비할 수 있는 고정 내용 계약을 전달한다. RP04 전까지 기존 renderer와 통합 회귀를 유지하고, 장면 선택/이미지 추출의 실제 제거와 디자인은 RP04가 담당한다. RP05에는 생성 원문·검증 상태·고정 근거를 제공하되 공개 저장소에는 합성 사례만 남긴다.
