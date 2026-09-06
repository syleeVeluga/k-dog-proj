# K-DOG 구현 진행 기록

## 현재 단계 및 범위

2026-09-06: **M4 설명·검토·출력 구현**. 세 공급자 설명 생성, 원결과를 보존하는 점수/설명 수정, 실제 영상 대표 프레임, 개별 PDF/XLSX·전체 PDF ZIP/XLSX·CSV 묶음과 불변 export snapshot을 연결했다. Python 92개·브라우저 7개·production build·원본 대조 및 실제 PDF/Excel 시각 검증을 통과했고 cold review 3건을 회귀 시험과 함께 수정했다. [M4 구현·검증 기록](K-DOG_M4_구현기록_v1.0_20260906.md)을 현재 설명·검토·출력 범위의 기준으로 삼는다. 실 API/품질은 미검증이며 미정 매핑·규칙은 보류한다.

2026-09-06: **M3 병렬 평가·집계 구현**. 반려견 36/보호자 19항목의 독립 병렬 요청·저장·부분 조회, Gemini/GPT/Claude REST 평가 어댑터와 개발자 공급자 선택, 프로그램 행동/설문 집계, 명시적 평가 재사용을 연결했다. Python 74개·브라우저 5개·production build·원본 항목집 대조를 검증한다. 실제 API/평가 품질은 미검증이며 DOG-12·OWN-14는 구조화된 선택 시간 계약이 없어 보수적으로 채점을 보류한다. [M3 구현·검증 기록](K-DOG_M3_구현기록_v1.0_20260906.md)을 현재 범위의 기준으로 삼는다.

2026-09-06: **M2 관찰 처리 구현**. FFmpeg 검사·오디오 보존 변환, Gemini REST 관찰 어댑터, SQLite worker, 카메라별 근거·통합 저장, 상태/이력·부분 결과·시간 재생·재시도·중지 UI를 연결했다. 명시적 관찰 재사용과 F-01 점유 경합, F-02 철회, F-04 표시 run 보호를 검증한다. Python 56개·브라우저 4개와 실제 로컬 합성 미디어 검사를 수행하며 실제 참가자 영상·Gemini 실호출은 샘플 제공 이후로 생략했다. [M2 구현·검증 기록](K-DOG_M2_구현기록_v1.0_20260906.md)을 현재 범위의 기준으로 삼는다.

2026-09-06: **M1 최소 입력 완료**. React·FastAPI 인증/역할, SQLite 핵심 5개 테이블, 참가자 목록/상세, 표준 CSV/XLSX·수동 설문, 세션·영상 저장을 구현했다. 서버 프로세스 재시작 후 1명·2영상·설문 재조회와 해시 일치를 검증했다. Python 테스트 39개(M0 24+M1 15), 브라우저 3개, production build와 원본 항목집 대조를 수행한다. 상세 범위·실행·의존성·검증 기록은 [M1 구현 기록](K-DOG_M1_구현기록_v1.0_20260906.md)을 참조한다. AI·미디어 검사·worker·내보내기는 후속 단계다.

위 M1–M3와 아래 M0 내용은 이전 단계의 이력이다. 설명·검토·출력은 M4 기록, 평가·집계·재사용은 M3 기록, 미디어·관찰은 M2 기록을 우선 참조한다.

## 확정 사항과 외부 조건

- 행동 BS 16 + DOG 20 + OWN 19, 설문 30개를 유지한다. ID는 제안 ID이며 참가자 ID는 문자열이다.
- 작업 중 사용자가 원본 Excel 2개를 `docs/`에 추가했다. 행동 이름·구간·선택지 230개·점수·방향·셀 위치와 설문 문구 30개·원래 층·채점 메모를 읽기 전용으로 이관했다.
- 원본 행동 55개를 PRD 부록 A의 ID·시트·행·이름·구간·영역과 대조해 모두 일치했다. 빈 선택지 45칸은 생성하지 않았다. 설문은 A:E 메타데이터만 읽으며 참가자 응답·이름·연락처를 이관하지 않는다.
- q23 환산/C-2, 4영역 대응, ②④ 유형, 애매한 시간 경계는 미정으로 유지한다.
- API 키·실제 영상 없이 계약 fixture 검증만 수행한다. Gemini/GPT/Claude 실 API는 모두 미검증이다.

## 주요 파일과 실행 구조

- `backend/app/domain/contracts.py`: 필수 6종 타입과 분기·행동/설문 항목집 타입. 추가 필드·잘못된 타입·누락/중복·잘못된 null 거절, JSON Schema 생성 지원.
- `backend/app/domain/validation.py`: 현재 run/case/session·영상·카메라·시간·근거/항목 연결 검증과 원본 선택지 점수 조회. 실제 관찰·판정·영역 집계는 M2/M3 대상이다.
- `backend/app/import_catalogs.py`: 원본을 수정하지 않는 재현 가능한 이관 CLI. 원본 해시·버전·시트·행·선택지 셀 보존. `--check`는 파일을 쓰지 않고 대조만 수행.
- `resources/catalogs/behavior-v1.json`, `survey-v1.json`: 실제 원문 항목집. 실행 설정/프롬프트로 변경하지 않는 읽기 전용 기준 데이터.
- `resources/rules/pending-v1.json`: 미정 규칙 기록. 실행 가능한 계산 규칙이 아니다.
- `backend/tests/fixtures/contract-case.json`: 가상 참가자·관찰의 고정 정상/결측 사례. 실제 AI 결과가 아니다.
- Python 도메인은 FastAPI/향후 worker가 공유한다. M1 React와 저장 계층이 추가되었으며 [개발 실행 안내](DEVELOPMENT.md)를 따른다.

## 수행한 검증과 결과

- `uv sync --locked`: Python 3.14.2 환경과 잠금 의존성 설치 완료.
- `uv run --locked python -X utf8 -m unittest discover -s tests -v`: **24개 테스트 통과**. 원본 모든 항목/선택지 셀 대조, PRD 55개 일치, 설문 30개/역문항 6개/층 16+8+6, 선행 0 ID, 근거 참조·시간·무음 검사, 분기 36/19개, 없는 선택지 거절, 결측/미정 null, JSON 왕복·스키마 생성을 검증했다.
- `uv run --locked python -X utf8 -m app.import_catalogs --check`: 55/30개 JSON이 원본 재추출과 일치.
- 행동 영역은 EDU 7 / SOC_P 1 / SOC_D 1 / SOC_E 9 / ATT 14 / CON 12 / TRN 6 / 참고 5개로 일치.
- 원본 SHA-256: 행동 `bd79b9e9467ff3aa7b0b179108703776ad9c2b1ae3d8bc11db00e09c4215a079`, 설문 `e20c5093c8b9e038cb4753c72d274eb75a2f938dcf0bdedc5b412817812b669c`. 이관 후 재확인했으며 원본은 변경하지 않았다.
- codebase-memory를 재인덱싱하고 RunInput·read_behavior·resolve_branch_scores 탐색을 확인했다.
- 브라우저/UI·DB 복구·AI 품질·실 API 검증은 이번 단계에 포함되지 않는다.

## 검수 F-01–F-05 적용 방향

- F-01: run/step/attempt별 불변 파일 + 점유 토큰 조건부 DB 참조 채택. 실제 저장·경합 시험은 M1/M5에서 수행.
- F-02: 입력 스냅샷과 현재 동의·삭제 상태를 분리하고 업로드/호출/재시도/내보내기/제공 직전에 재확인. 실제 권한·중단 시험은 M1 이후.
- F-03: 재사용은 같은 case/session과 관련 해시·버전을 검사한 명시적 manifest 참조 방식. 현재 run의 허용 근거 목록만 허용하며, 허용 목록 작성과 재사용은 후속 구현.
- F-04: 선택 session/input revision/display run을 명시하고 전체 내보내기의 revision 목록을 접수 시 고정. 완료 시각으로 최신 결과를 교체하지 않음. 후속 DB/출력 구현 대상.
- F-05: 관찰 부족과 계산 규칙 미정을 구분. `rule_pending`에서는 선택지·점수를 null로 보존하며 시험 초안은 운영 결과에 섞지 않음.

## 의존성 확인

2026-09-06 인터넷 검색 후 [PyPI 최신 메타데이터](https://pypi.org/pypi/pydantic/json)와 [공식 릴리스 내역](https://pypi.org/project/pydantic/)에서 Pydantic 최신 안정 버전 **2.13.5** 확인. Python >=3.9 지원이며 로컬 Python 3.14.2에서 검증 완료. 직접 의존성은 정확한 버전으로, 전이 의존성은 `backend/uv.lock`으로 고정했다. 프로젝트 Python 범위는 실제 검증한 3.14 계열로 제한했다.

[공식 validator 문서](https://docs.pydantic.dev/latest/concepts/validators/)와 [V2 마이그레이션 문서](https://docs.pydantic.dev/latest/migration/)를 확인해 V2의 `model_validate_json`, `model_validator`, `ConfigDict`를 사용한다. 테스트는 Python 표준 `unittest`를 사용한다. FastAPI/React 등은 이번 단계에서 설치·사용하지 않는다.

원본 추가 후 [openpyxl PyPI](https://pypi.org/project/openpyxl/)·[최신 메타데이터](https://pypi.org/pypi/openpyxl/json)·[공식 읽기 전용 문서](https://openpyxl.pages.heptapod.net/openpyxl/optimized.html)를 확인했다. 최신 안정 **3.1.5**(Python >=3.8)를 개발 의존성으로 고정해 Python 3.14.2에서 이관/대조 시험을 통과했다. `read_only=True, data_only=False`로 읽고 원본을 저장하지 않는다. 수식을 실행하거나 재계산하지 않는다.

## 다음 구현 작업

M5: 개발자 프롬프트 초안·시험·적용·복원, 키 저장소와 운영 복구 정리. 실제 동의된 영상·공급자 키가 제공되면 관찰/평가/설명 실 API·근거/선택 품질 검증을 별도로 수행한다. 미정 계산 규칙은 계속 보류한다.

## 사용자 수정 보존

기존 4개 명세와 사용자가 추가한 AGENTS.md 지침을 보존한다. 읽기 전용 원본 자료를 수정·이동·삭제하지 않는다.
