# K-DOG 설치 계정과 발행 키 기간 실행 기록

버전: v1.0 · 2026-10-23 · 계획: [설치 계정과 발행 키 기간 계획](K-DOG_설치계정과발행키기간_v1.0_20261023.md) · 브랜치: `veluga/install-first-user-20261023` · 기준: `main / cd139c6`

## 구현 결과

| 커밋 | 내용 |
| --- | --- |
| `efe1be0` | 발행 키 유효 기간(`--expires`, 인증 헤더, 키 입력 전 검사), 개발자만 발행, 설치 중 첫 업무 계정(`manage create-first-user`), 문서·검증 갱신 |
| `aba4316` | 1차 검토 반영: 첫 계정의 예약 이름(`builtin-reference`, `kdog-ai-service`) 거절, 기간 한계 문구 정정 |
| `a454c63` | cold review 반영: 발행·`provision_accounts`에도 예약 이름 거절(`auth.reserved_username`), `--check` 읽기 전용, 건너뛰기 안내를 `Install.cmd` 재실행으로 변경, 첫 계정 단계 `OSError` 처리, 검증 기간을 내일로, 문서 정합 |

이미 발행된 패키지(기간 없음, 업무 계정 1개)는 그대로 설치되며 업무 계정이 있으므로 첫 계정을 묻지 않는다. `create-first-user`가 없는 이전 제품 ZIP은 `issue_release`가 발행 전에 거절한다. 새 의존성·라이브러리는 추가하지 않았으므로 라이브러리 최신판 확인 대상이 없다.

## 검증

| 항목 | 결과 |
| --- | --- |
| `tests.test_issued_release` (계획 검증 1~7) | 21개 통과 |
| `tests.test_issued_release tests.test_packaging tests.test_macos_distribution` | 49개 중 48개 통과, 네이티브 macOS 키체인 1개 명시 skip |
| 전체 backend `unittest discover -s tests` (`a454c63`) | 859개 통과, 5개 명시 skip, 1099.048초 |
| 실제 포터블 ZIP `build_release` → `verify_release` (`a454c63`, 1470개 파일, SHA-256 `9af8f4a4c96f973097f417f4bd68cec39507451af1cf1b43ca5c8fc727532d0f`) | 통과: 평문 실행, 발행 봉인, 틀린 키·헤더/본문 변조·기간 연장·만료 패키지 무변경, 설치 중 첫 업무 계정 생성·로그인·접수, 개발자 설정 접근, 재설치 시 자료·계정 유지와 재질문 없음, Gemini 두 슬롯 미등록 |
| 빌드 ZIP 키 검사 | 앱 코드·동봉 런타임 전체에서 `AIza…`·`sk-…`·`GEMINI_API_KEY=값` 형식, `.env`·DB·키 저장 파일 0건 |
| `git diff --check` | 통과 |
| S1 원본 대조 `import_catalogs --spec 20261002 --check` | 실패: 로컬 전용 원본 SRC02 없음. 이번 변경과 무관하며 통과로 표시하지 않는다 |

`uv`는 이 PC의 PATH에 없어 사용자 Python Scripts 폴더의 uv 0.13.0을 PATH 앞에 두고 실행했다. frontend 코드는 바꾸지 않았으며 `build_release`가 frontend 빌드를 다시 수행했다. 브라우저 E2E는 실행하지 않았다. 처음 전체 시험 두 번은 코드 수정 뒤 대상이 낡아 중지했고, 최종 커밋에서 한 번 완료했다.

## 독립 검토와 조치

1차 검토 1회와 cold review 3회(설치·암호화, backend 계정, 문서 정합)를 서브에이전트로 수행했다. 차단·중대 결함은 없었다.

| 지적 | 조치 |
| --- | --- |
| 기간 우회는 시계뿐 아니라 평문 설치 프로그램 수정으로도 가능 | 문서·docstring에 명시 (오프라인 강제 수단이 아님) |
| 첫 계정이 예약 이름을 가져가면 내장 기준·AI 기록이 깨짐 | 첫 계정·발행·`provision_accounts` 모두 거절, 시험 추가 |
| 건너뛰기 안내의 `create-user`가 예약 이름 검사를 우회, `cd /d`는 PowerShell 불가 | 안내를 `Install.cmd` 재실행으로 변경 |
| 첫 계정 단계 `OSError`가 traceback으로 끝남 | 오류 안내로 처리 |
| 검증 기간 "오늘"은 자정을 넘기면 거짓 실패 | 내일로 변경 |
| `--check`가 쓰기 잠금을 잡음 | 읽기 전용 연결 |
| 마지막 날 `main()` 경로·비활성 계정 충돌 시험 부족 | 시험 추가 |
| README·계획 세부·설치안내 상한·archive 안내 | 반영 |
| 건너뛴 경우 마지막 문구, Ctrl+C traceback | 유지: 건너뛰기 안내가 함께 나오고 Ctrl+C는 기존 키 입력과 같은 동작 |

## 남은 범위

깨끗한 OS·물리 PC, 실제 현장 담당자 설치, 개발자의 PC별 실제 Gemini 키 등록과 실공급자 호출은 수행하지 않았다. 설치 대수 제한은 계획대로 범위 밖이다.
