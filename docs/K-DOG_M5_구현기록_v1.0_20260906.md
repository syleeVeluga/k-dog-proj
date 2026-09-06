# K-DOG M5 개발자 편집·복구 구현·검증 기록

버전: v1.0 · 작성일: 2026-09-06

기준: [구현 지시서 §8·M5·T08–T11](K-DOG_바이브코딩_구현지시서_v1.0_20260905.md), [PRD REQ-09/10/11·AT-26–32](K-DOG_PRD_v0.4_20260905.md), [검수 F-01–F-05](K-DOG_문서검수_v1.0_20260905.md).

## 구현 범위

- 개발자 화면에서 관찰·반려견 평가·보호자 평가·설명 프롬프트를 각각 편집한다. 공급자·모델·최대 출력 토큰·관찰 FPS·최대 시도·평가 동시 요청·분석당 AI 호출 상한을 검증한다. 관찰은 Gemini, 참가자와 카메라 관찰 동시 처리는 각각 1건으로 유지한다. 확정 항목집과 미정 계산 규칙은 설정으로 교체하지 않는다.
- 현재 설정 복제 → 불변 초안 저장 → 버전 차이 → 스키마/합성 샘플 시험 → 운영 적용/이전 버전 복원을 제공한다. 초안마다 새 ID·파일·SHA-256을 저장하고 적용 시 현재 버전을 비교하여 다른 개발자의 변경을 덮어쓰지 않는다. 기존 M3/M4 설정은 최초 M5 적용 전까지 사용하며 이후 구형 수정 API는 거절한다.
- 접수된 run 설정은 변경하지 않는다. 새 설정은 새 run부터 사용한다. 단계별 설정 해시로 재사용을 판단해 보호자 프롬프트만 바꾸면 관찰과 반려견 평가를 재사용할 수 있다.
- 개발자 전용 키 등록·교체·폐기·연결 시험을 제공한다. Windows 현재 실행 계정의 DPAPI를 사용하며 machine 범위는 사용하지 않는다. 암호문은 데이터 폴더 `secrets/`, 참조 ID와 상태는 감사 이력에 저장한다. 키 조회 API는 없고 공급자 호출 메타데이터에는 자격증명 참조만 기록한다. 교체·암호문 읽기·정리는 DB 쓰기 트랜잭션으로 직렬화한다.
- 등록 이력이 없는 공급자에 한해 기존 worker 환경 변수 초기값을 지원한다. 등록하면 vault가 우선하며 폐기 후 환경 변수 키로 복귀하지 않는다. API와 worker는 **같은 전용 Windows 서비스 계정**으로 실행해야 한다. 개발자 앱 로그인 역할과 Windows 실행 계정은 별개다.
- 운영 관리자 화면에 자료 백업·공간·삭제 요청·복구 상태를 제공한다. SQLite backup API 스냅샷과 연결 파일을 해시로 검증하며 키 암호문·임시 업로드·미참조 파일은 일반 백업에서 제외한다. 백업의 로그인 세션은 제거한다.
- 새 폴더 복원 시 현재 삭제 목록을 재적용한다. DB 무결성·외래키·연결 파일 검증 및 삭제 정리까지 끝낸 임시 폴더만 최종 경로로 공개한다. 백업에 없는 참가자의 삭제 이력도 후속 복원을 위해 보존한다.
- API·worker OS 잠금으로 실행 중 복원·정리를 거절한다. 미참조 파일 정리와 삭제 요청된 참가자의 원본·파생 파일·run·수정·관련 내보내기 제거를 제공한다. DB 삭제에는 secure_delete, VACUUM, WAL 절단을 적용한다. 삭제 참가자를 포함한 전체 내보내기는 파일 전체를 제거한다.

주요 구현: `backend/app/settings.py`, `secrets.py`, `developer_sample.py`, `maintenance.py`, `frontend/src/DeveloperSettings.tsx`. 기존 API·worker·어댑터에 연결했다. 새 의존성은 없으며 DB user_version 2에서 `steps.call_reserved`만 추가한다.

## 시험·비용 한도와 미검증 범위

**스키마 시험**은 저장한 설정 계약 검증이며 공급자를 호출하지 않는다. **합성 샘플 API 시험**은 사용자가 누른 한 단계만 실제 어댑터로 실행한다. 관찰은 FFmpeg로 만든 2초 회색 무음 영상, 평가·설명은 참가자가 없는 빈 근거/결측 설문을 사용한다. 결과·사용량은 개발자 시험 이력에 저장하며 참가자·run·운영 결과를 생성하지 않는다. 시작 기록만 남은 시험은 중단된 요청으로 이미 과금되었을 수 있다.

연결 시험은 고정된 공급자 models endpoint로 키 인증을 확인한다. 모델의 구조화 출력 지원·품질 검증과는 구분한다. 자동 시험은 모의 공급자/REST만 사용했다. **실제 공급자 연결·모델 지원·관찰/평가/설명 품질은 미검증**이며 키가 없을 때 가상 결과로 자동 전환하지 않는다.

분석당 AI 호출 상한은 호출 전에 DB에서 원자적으로 예약한다. 병렬 평가·재시도·중단/응답 유실 및 설명 재생성이 같은 run의 상한을 공유한다. 전송 전 실패한 예약도 보수적으로 포함한다. 상한에 도달하면 새 호출을 거절하고 성공 결과는 보존한다. 한도 변경은 새 분석부터 적용한다.

상한은 **요청 횟수와 출력 토큰의 상한**이며 원화/달러 결제 금액 상한이 아니다. 입력 영상/토큰·모델 단가·환율을 반영한 통화 비용 추정과 행사 부하 측정은 M6 파일럿 작업으로 남긴다. 미정 단가·q23·4영역 매핑·②④ 유형·모호한 시간 선택 규칙을 임의 확정하지 않았다.

## 운영 명령

`backend/`에서 실행한다. 설치/빌드/계정 발급은 [개발 안내](DEVELOPMENT.md)를 따른다. 아래 경로는 예시이며 `--data-dir`는 하위 명령 앞에 둔다.

```powershell
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" recovery-status
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" backup "E:/K-DOG/backup-20260906" --actor manager
```

백업은 새 폴더만 허용한다. 관리자 화면에서는 데이터 폴더와 나란한 `backups/<id>`에 저장한다. 백업 중 DB 쓰기를 잠시 막으므로 영상량이 크면 업무를 멈춘 시간에 수행한다. `backup.json`이 완성되지 않은 실패 폴더는 복원할 수 없다. 개인정보가 포함된 자료 백업의 접근 권한은 운영자가 관리한다.

API와 worker를 종료한 뒤 다음을 사용한다.

```powershell
# --data-dir에는 최신 삭제 목록을 가진 현재 DB를 반드시 지정한다.
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" restore "E:/K-DOG/backup-20260906" "D:/K-DOG/restored-20260906"
# 미참조 임시/고아 파일만 정리한다.
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" clean
# 이미 삭제 요청된 참가자 DB·원본·파생 파일도 영구 삭제한다.
uv run --locked python -X utf8 -m app.manage --data-dir "D:/K-DOG/data" clean --purge-deleted
```

복원은 기존 폴더를 덮어쓰지 않는다. 현재 DB가 없으면 빈 삭제 목록을 가정하지 않고 거절한다. 다른 PC로 이동할 때 최신 삭제 이력을 가진 DB도 안전하게 보존해야 한다. 새 PC에서는 개발자가 키를 다시 등록하고 검증된 복원 경로를 API/worker 양쪽의 `--data-dir`로 지정한다. 실행 중이던 run은 이전 점유를 만료시켜 새 worker가 최종 시도 파일을 검증·채택하거나 제한 안에서 재시도한다.

보관 기간·백업 순환 삭제 정책은 책임자가 확정해야 한다. 과거 백업이나 외부 전달 파일을 자동 회수하지 않는다. Gemini 원격 삭제 실패는 기존 `remote_cleanup_pending`으로 남으며 완료를 보장하지 않는다. PC 관리자를 신뢰할 수 없다면 로컬 DPAPI만으로 보호를 보장하지 않으며 PRD의 개발자 관리 중계/클라우드 배포를 선택해야 한다. 원클릭 설치·새 환경 패키징은 M6에 남는다.

## 검증 결과

```powershell
# backend/
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
uv run --locked python -X utf8 -m app.manage --help
# frontend/
npm run build
npm run test:e2e
# 저장소 루트
git diff --check
```

- Python **107개 통과**: 기존 92개 + M5 회귀 15개. production build와 브라우저 **8개 통과**. 원본 행동 55개·설문 30개 및 기존 SHA-256 일치.
- 실제 별도 Python worker 프로세스를 관찰 파일 저장 후 DB 채택 직전에 종료 코드 91로 강제 종료했다. 백업 → 새 폴더 복원 → worker 재개 후 두 관찰이 첫 시도로 완료되고 저장된 카메라를 재호출하지 않음을 확인했다.
- 실제 Windows DPAPI 왕복, 동시 키 교체 12회, 폐기 후 환경 변수 우회 금지, DB/파일/백업의 시험 키 원문 부재, 공급자 JSON escape·헤더 반사 값 제거를 검증했다.
- 복원된 보고서/XLSX 다운로드, 최신 삭제 목록과 원본/전체 내보내기 제거, DB 내 삭제된 반려견 이름 원문 제거, 손상 해시·경로 탈출 거절을 확인했다.
- 브라우저의 초안·시험·적용·복원·키 입력란 초기화·직원 권한 분리를 검증했다. 360px 수평 넘침과 브라우저 오류 없음. `frontend/test-results/settings-*/m5-settings-{desktop,mobile}.png`를 생성해 시각 확인했다. 스크린샷은 무시되는 로컬 합성 시험 산출물이다.
- 기존 Starlette TestClient의 httpx deprecation 경고는 실패가 아니며 이번 기능과 무관한 도구 교체는 수행하지 않았다. 원본 Excel·요구사항 문서는 보존했다.

## Cold review

구현 후 요구사항과 변경 파일을 별도로 다시 검토했다. 별도 에이전트 리뷰는 사용하지 않았다.

| 발견 | 수정·검증 |
|---|---|
| 동시 키 교체 시 새 암호문을 미참조 파일로 오인할 수 있음 | DB 트랜잭션 직렬화, 12개 동시 교체 후 현재 키 복호화와 활성 암호문 1개 검증 |
| 복원 후반 실패 시 최종 폴더 노출 또는 백업에 없는 삭제 이력 유실 | 임시 폴더 검증/삭제 후 공개, 정리 오류 주입에서 최종 경로 없음, 백업 이후 추가된 삭제 이력 보존 |
| 현재 설정 손상이 과거 리포트 조회를 막음 | 현재 연결 상태 실패를 설정 필요로 제한, 손상 활성 파일에서도 기존 점수·리포트 조회 성공 |
| 키 작업 후 새로고침이 편집 중인 프롬프트를 초기화함 | 키 작업에서는 메타데이터만 갱신하고 편집 내용을 유지 |

구현 검증 중 발견한 백업 DB 연결 종료 누락과 합성 입력 계산 버전 불일치도 수정했다. 최종 전체 검증에서 미해결 회귀 오류는 없다.

## 의존성·공식 문서 확인

2026-09-06 공식 PyPI/npm 최신 메타데이터와 API 문서를 다시 확인했다. 기존 잠금 버전이 최신 안정과 모두 일치하여 변경 없이 사용했다. Python 3.14.2·Node 24 환경에서 검증했으며 신규 라이브러리/SDK 설치는 없다.

| 패키지 | 최신 안정 = 선택 버전 | 공식 확인 |
|---|---|---|
| Pydantic / FastAPI / Uvicorn | 2.13.5 / 0.141.1 / 0.52.4 | [Pydantic](https://pypi.org/pypi/pydantic/json), [FastAPI](https://pypi.org/pypi/fastapi/json), [Uvicorn](https://pypi.org/pypi/uvicorn/json) |
| openpyxl / ReportLab / Pillow | 3.1.5 / 5.0.1 / 12.3.0 | [openpyxl](https://pypi.org/pypi/openpyxl/json), [ReportLab](https://pypi.org/pypi/reportlab/json), [Pillow](https://pypi.org/pypi/pillow/json) |
| httpx / pypdf | 0.28.1 / 6.17.0 | [httpx](https://pypi.org/pypi/httpx/json), [pypdf](https://pypi.org/pypi/pypdf/json) |
| React / React DOM | 19.2.8 / 19.2.8 | [React](https://registry.npmjs.org/react/latest), [React DOM](https://registry.npmjs.org/react-dom/latest) |
| React types / DOM types | 19.2.18 / 19.2.7 | [React types](https://registry.npmjs.org/@types/react/latest), [DOM types](https://registry.npmjs.org/@types/react-dom/latest) |
| Playwright / TypeScript / Vite | 1.63.0 / 7.0.2 / 8.2.2 | [Playwright](https://registry.npmjs.org/@playwright/test/latest), [TypeScript](https://registry.npmjs.org/typescript/latest), [Vite](https://registry.npmjs.org/vite/latest) |

[Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/), [FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/), [React useState](https://react.dev/reference/react/useState), [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata), [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata)를 확인했다. DPAPI는 표준 ctypes로 current-user·UI 금지 플래그를 지정하고 결과 메모리를 LocalFree로 해제한다. Python 패키지의 requires-python은 모두 3.14를 허용하며 동일 React/DOM 버전과 기존 도구 조합을 유지했다.

codebase-memory `list_projects` 후 fast/full 재인덱싱을 했으나 M0의 196개 노드만 반환하고 M1–M4 코드 검색도 비어 있었다. 인덱스 불일치를 알린 뒤 파일 탐색으로 보완했다. 최신 코드가 그래프에 반영되었다고 주장하지 않는다.
