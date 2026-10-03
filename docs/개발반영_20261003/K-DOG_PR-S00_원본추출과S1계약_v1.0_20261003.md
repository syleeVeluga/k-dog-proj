# PR-S00 원본추출과S1계약

버전: v1.0 · 2026-10-03 · 상태: 구현 전 · 선행: 없음 · 기준: main 3654596

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md). 공통 검증·리뷰·버전 확인·저장 보호는 상위 §7을 적용한다.

브랜치 제안: `veluga/s00-s1-contracts` · 권장 PR 제목: `feat: S1 항목과 근거 계약 추가`

## 문제와 결과

현 계약은 117행·직접109행과 원표 행번호를 고정한다. S1.1의 90항목, 새 의미, 산출 규칙과 근거를 별도 자산·엄격한 계약으로 제공한다. 기본 앱 판본은 이 PR에서 바꾸지 않는다.

근거: 통합명세 2·6~10절, 부록 A~F, 산출근거의 영상90항목·변경항목·산출규칙. 인수: T02·T15·T20·T28, 확인: G01·G04·D03·D05.

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `backend/app/import_catalogs_v4.py` | 신설 | DOCX 표·산출근거 추출, 원본 hash/위치, 변경표 대조 |
| `backend/app/import_catalogs.py` | 수정 | `--spec 20261002` 및 S1 기본 추출 경로 연결 |
| `backend/app/domain/catalog_v4.py`, `backend/app/domain/contracts_v4.py`, `backend/app/domain/validation_v4.py` | 신설 | 90코드·83/4/3, 엄격한 값/상태/근거·판본 계약 |
| `resources/catalogs/behavior-v4.json` | 신설 | S1.1 원문·허용값·우선순위·선택 여부·관찰 조건 |
| `resources/rules/scoring-v4.json`, `resources/rules/protocol-v4.json`, `resources/rules/preprocess-v4.json` | 신설 | 확정 계산·동선·창 정의, 미확정은 상태로 분리 |
| `resources/mappings/survey-behavior-v4.json`, `resources/mappings/results-v4.json`, `resources/mappings/s1-input-v4.json` | 신설 | 설문/출력 연결, 구간 D/F/G·내부 J 주소와 실물 검증 상태 |
| `backend/tests/test_catalog_v4.py`, `backend/tests/test_contracts_v4.py`, `backend/tests/test_mapping_v4.py` | 신설 | 원문·코드·역참조·범위·판본 혼용 차단 |

## 구현 순서와 계약

1. 주 문서와 산출근거의 hash·문서 버전·시트/절/셀을 기록한다. 개인정보 포함 검수 파일을 카탈로그 원본으로 복제하지 않는다. 규칙 출처가 DOCX 본문인지 Excel인지 항목별로 표시한다.
2. 90개를 83숫자·4자동·3메모로 검증한다. 환경1과 내부 J94를 분리한다. 개59는 활성90개 밖의 연결메모 계약에 두고 폐기33·미사용4는 원문 변경 대조표에만 둔다. 기존 앱 점수의 이관표·역사 저장소는 만들지 않는다.
3. 직접 숫자에 바46~53 횟수, 선택 바54·55의 0/1, 환경1 0~3과 새 개8·10·12·30·34 정의를 넣는다. 전체 관찰·범주 우선순위·원척도·표시 순서를 분리한다. 중요도를 가중치로 사용하지 않는다.
4. 부록 B 29배점은 구판과 동일 여부, 부록 C 25조합은 최종 문구와의 일치를 검증한다. V·AW·AY·개32 파생값은 S1 규칙 목록에 넣지 않는다. 걷기 예외는 91번째 항목이 아닌 국면 메타데이터다.
5. 구간 D→내부 J 주소, F 근거·G 검토메모의 역할을 매핑한다. G01 실물 부재 시 명세상 주소와 실물 확인 상태를 분리하고 입력 Excel import는 비활성으로 둔다.
6. 설문 원문은 v3 자산을 참조하고 S1 집계 정책/행동 연결만 새로 만든다. Q7~9 등 확대 미확정과 개21 시간 미확정을 확정 창/산식으로 직렬화하지 않는다.
7. 숫자 0/null, 기회 없음·미실시·무효·관찰 부족·정책 대기를 구별한다. 자동4개 입력은 거절하고 유형은 허용 이름 또는 보류 상태만 허용한다.
8. 고객 원본은 변경하지 않는다. S1 자산은 지정 경로로 생성하고 실행 시 hash 불일치는 명시 오류로 처리한다. 구판 추출기·파생 자산의 유지 자체는 요구하지 않으며, 아직 전환하지 않은 호출부에 필요한 것은 해당 PR의 교체 완료 때 정리한다. 재사용하는 설문 원문·공통 자산은 유지한다.

## 검증과 완료 조건

- 코드 집합이 주 문서·산출근거와 같고 117−4−33−1+11=90, 83+4+3=90이 성립한다.
- 부호·0·null·미사용·자동 입력·구판 ID·범위 위반, 환경1/개94 혼동을 거절한다.
- 개9와 보10·11·23의 표시 순서만 달라지고 값/보호자 배점은 바뀌지 않는다.
- 모든 참조 코드·창·설문·출력 근거가 존재하며 폐기 항목은 새 실행 참조에 없다.
- G01 미수령은 검사 결과에 미검증으로 남는다. 계약 추출 통과를 원본 Excel 수식 대조 통과로 표시하지 않는다.
- 신설 후 `uv run --locked python -X utf8 -m unittest discover -s tests -p "test_*v4.py" -v`와 `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`를 backend에서 실행한다. 카탈로그 검사는 수령된 기준 원문의 추출 대조이며, G01 입력 원본의 주소·수식 실검은 S06에서 별도로 기록한다.

## 경계와 인계

S01에 새 판본 계약, S04에 창·미확정 정책, S07에 계산 근거를 전달한다. 원문 규칙은 만들어 넣지 않는다. 이 PR는 기존 실행 데이터를 초기화하지 않으며 S01에서 결과 제거와 원입력 연결을 수행한다. G01 실제 파일 수령 후 주소·수식 확인은 S06이 담당한다.

## 구현 및 검증 기록

- [ ] 구현·변경 파일 및 commit/PR 기록
- [ ] 명세 기대값과 실제 시험 결과·미실행 사유 기록
- [ ] 라이브러리/API 최신·선택 버전·확인일·근거 기록
- [ ] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [ ] 남은 D/G 확인, 활성/보류 기능, 다음 PR 인계 기록

### 2026-10-03 구현 실행 기록

구현 범위는 S00 코드·자산·계약 검증이다. 고객 원본 파일은 읽기 전용으로 사용했으며 참가자 응답·점수·리포트 파일을 추출 원본으로 사용하지 않았다. commit/PR은 상위 작업에서 단계별로 기록한다. 이 기록 시점에는 S00 담당 에이전트가 commit·push·PR 생성이나 실제 데이터 초기화를 실행하지 않았다.

변경 파일:

- `backend/app/import_catalogs_v4.py`, `backend/app/import_catalogs.py`: `--spec 20261002`와 S1 기본 추출 경로. 구판 명시 추출은 `--spec 20260929`로만 선택한다.
- `backend/app/domain/catalog_v4.py`, `contracts_v4.py`, `validation_v4.py`: 활성90개, 엄격한 정수/메모/상태·판본·근거 계약, 규칙/매핑 읽기의 중첩 원본 식별·hash 검증.
- `resources/catalogs/behavior-v4.json`, `changes-v4.json`: 활성 사전과 원문 변경표를 분리한다. 개59는 연결 메모이며 환경1은 내부 J94와 구분된다.
- `resources/rules/scoring-v4.json`, `protocol-v4.json`, `preprocess-v4.json`: 확정 원문·관찰창·동선·정책 대기, 원본 번호와 camera_id 대응을 보존한다. R25의 원문 이관안에는 사용자 2026-10-03 전점수 폐기 지시가 우선한다는 적용 상태를 명시했다.
- `resources/mappings/survey-behavior-v4.json`, `results-v4.json`, `s1-input-v4.json`: S1 참조·입력 주소·F/G 역할·걷기 국면 H10:H15와 실물 미검증 상태.
- `backend/tests/test_catalog_v4.py`, `test_contracts_v4.py`, `test_mapping_v4.py`: S00 30개 시험. 기존 `test_catalog_v3.py`의 CLI 시험은 구판 명시 추출로 변경했다.

원문 검증:

| 원본 | 확인한 SHA-256 | 확인 범위 |
| --- | --- | --- |
| SRC02 통합명세 v1.3/S1.1 | `4a1b3696246d55b34f6ca2b919c1599da4b15b47fa7a4e5ae624a2669a17493a` | 부록 A 90항목, B 29배점, C 25조합, F 54개 변경 기록, 본문 동선·계산·미확정 경계 |
| SRC03 산출근거 XLSX | `11b9fd6c1241679d175998d04e0f29fd4420228dc2abb0d0d84e72f055b22941` | 영상90항목 순서/주소, OWT29·SEP25 원문, 변경54행, 설문28 연결, R01~25·출력 연결 |

두 원본은 추출 전후 hash가 동일했다. DOCX/XLSX 간 코드·주소·29배점·25조합·54개 변경을 대조했다. 29배점은 기존 v3 자산과 동일하며, 새 25조합의 문구는 S1.1 원문과 일치한다. `117−4−33−1+11=90`과 `83+4+3=90`을 시험했다. SRC03의 개23/58에 남은 개8 몸 상태 참조는 SRC02의 정정 정의로 대체했다. G01/G04의 실제 빈 입력 파일·수식 실행·주소 실물 대조는 미실행이며 importer 출력과 자산에 이 상태를 명시한다.

검증 명령과 결과:

- backend에서 `uv run --locked python -X utf8 -m unittest discover -s tests -p "test_*v4.py" -v`: 당시 34개 통과(S00 30개 + S01 접수 4개). 최종 중첩 hash 수정 후 S00 세 모듈을 구성한 `unittest.TestSuite`로 30개 전부 재통과했다.
- backend에서 `uv run --locked python -X utf8 -m app.import_catalogs --spec 20261002 --check`: 8개 자산 원문 추출 대조 통과. 출력 마지막에 `G01/G04 ... not received ... Excel import disabled`를 별도 표시한다.
- backend에서 `uv run --locked python -X utf8 -m unittest discover -s tests -p "test_catalog_v3.py" -v`: 7개 통과. 구판을 기본 판본으로 간주하던 CLI 회귀를 명시 판본 선택으로 수정했다.
- 저장소 루트 `git diff --check`: 통과. 전체 backend 회귀 및 공유 그래프 `graft build`는 공통 파일 담당 상위 작업에서 한 번에 실행·기록한다.
- 이 검증은 합성 계약 시험과 수령 원문의 추출 대조다. 실제 영상·AI 공급자·입력 Excel 재계산·운영 인수 통과가 아니다.

독립 cold review 수용·수정 기록:

| 발견 | 처리 | 회귀 확인 |
| --- | --- | --- |
| 보10 퇴실 전 상호작용이 퇴실 후 혼자 창에 연결됨 | 퇴실 준비부터 몸이 완전히 나갈 때까지의 `separation_departure` 창 신설 | 퇴실 전 근거 허용·혼자 구간 근거 거절 |
| 보22 회피 대응을 실제 접촉 창으로 한정함 | 재회 후반 창으로 연결하여 접촉 전 회피에 손을 거두는 대응도 수용 | 접촉 없는 회피 대응의 유효 입력 |
| 개10 후기50초의 부분 관찰이 숫자로 수용됨 | 전체 창 관찰 조건 필수화 | 부분관찰 거절·완전관찰 수용 |
| 원본 hash가 형식만 맞으면 수용됨 | 카탈로그·규칙·프로토콜·전처리·매핑 모두 SRC02/03 파일명/hash를 고정 검증 | 임시 자산의 중첩 hash를 변경하면 명시 오류 |
| R25 원문 이관안이 현재 적용 정책으로 읽힐 수 있음 | `superseded_by_user_20261003`와 전점수 폐기/재채점 적용정책 명시 | 옛 값 복사 금지 정책·활성 파생값 목록 확인 |

독립 검토자는 최종 수정본에서 위 5개 발견의 재현이 모두 해소됐고 S00 범위의 잔여 수정 요청이 없음을 확인했다. 규칙 내부의 hash 손상도 `ValidationError`로 거절되며 카탈로그10개 시험과 8개 자산 원문 검사를 재실행했다.

라이브러리 확인일은 2026-10-03이다. Pydantic 최신 안정판과 선택판은 모두 **2.13.5**이며 기존 `pyproject.toml`/`uv.lock` 고정판을 재사용했다. [PyPI 버전·Python 호환](https://pypi.org/project/pydantic/2.13.5/), [공식 2.13 릴리스](https://pydantic.dev/articles/pydantic-v2-13-release), [Strict Mode API](https://docs.pydantic.dev/latest/concepts/strict_mode/)를 확인했다. Python >=3.9 및 Python3.14 지원 범위이고 현 시험 환경은 Python3.14.2/Pydantic2.13.5다. 새 의존성 설치·기존 의존성 변경은 없다. DOCX/XLSX의 읽기 전용 추출은 표준 라이브러리 ZIP/XML로 수행하고 원본 Excel 수식을 실행하지 않는다.

다음 단계 인계: S01은 새 판본 상수와 계약을 사용한다. S04는 실제 사건 시각·동선과 정의 창을 연결한다. S06은 영상의 대상/회차 소속·실제 시각·독립 입력의 저장 보호와 기회조건을 검사하고 G01/G04 파일 수령 후 실물 import를 검증한다. S07은 R01~25 원문, 29배점·25조합 및 명시된 적용 우선순위를 사용한다. D03의 보5 사건간 종합·동률·최소량·개21 전체30초안, D04 자동 유형 결정 상세, D05 비공포 묶음 부분결측 정책, G01/G04 실물 확인은 계속 대기 상태다.
