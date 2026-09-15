# K-DOG 42항목 판 P0 구현 계획 — PR-0 ~ PR-4 파일별 상세

버전: v1.0 · 2026-09-16 · 상위 문서: [변경 검토 v1.0](K-DOG_변경검토_v1.0_20260915.md) 4장(N1~N4)·6장(P0) · 근거: `docs/최종 고객 문서/` 01·03·04·05·05b

## 0. 범위와 원칙

P0는 촬영 당일 화면(P1)보다 앞서, **42항목 판의 규칙을 코드로 확정**하는 단계다. 화면은 만들지 않는다. 다음 네 가지가 P0의 산출물이다.

1. 03 엑셀에서 뽑은 `behavior-v2.json`과 04 설문지에서 뽑은 `survey-v2.json` (원본 해시·시트·행·셀 보존)
2. 새 계약(`contracts.py` v2): 3상태 항목 점수, 채점자, 8구간 시각, 영역·축·자료형
3. 새 계산(`scoring.py` v2): 영역 mean/lean/width/degree, 지표 4, 유형 2, 무효 규칙, 설문 5영역·분리 유형
4. 03 `여러쌍비교!D6:Z6` 수식과 같은 입력으로 같은 출력을 내는 골든 테스트 (05 예비촬영 6쌍 값)

**옛 코드는 대체물이 들어오는 PR 안에서만 옮기거나 지운다.** 옛 55항목 판 계약·계산은 현재 worker·API·리포트가 아직 쓰고 있으므로, P0에서는 `backend/app/legacy/`로 옮겨 읽기 전용으로 격리하고, 각 인프라 모듈이 42항목 판으로 교체되는 P1·P2 PR에서 그 모듈이 쓰던 legacy 조각을 함께 지운다. legacy 패키지에는 기능을 추가하지 않는다.

PR 절차는 다섯 PR 모두 같다: 브랜치 → 구현 → 검증(아래 명령) → 코드 리뷰 → 리뷰 이슈 수용 여부 검토(수용/보류/거절 사유 기록) → 수용안만 반영 → 재검증 → 푸시·PR 생성·병합. 검증 명령은 `backend/`에서 실행한다.

```powershell
uv run --locked python -X utf8 -m unittest discover -s tests
uv run --locked python -X utf8 -m app.import_catalogs --check
git diff --check
```

## 1. 항목 ID 표 — 03 엑셀 행과 새 ID의 대응

ID 규칙: 시트 순서대로 `BS-01~09`(1_바디시그널 5~13행), `DOG-01~24`(2_개행동 5~28행), `OWN-01~09`(3_보호자행동 5~13행). 번호 = 행 − 4. 옛 55항목 ID와 접두어가 같지만 번호 의미가 다르므로 catalog_version으로 구분한다(옛 `catalog-20260904-v1`, 새 `catalog-20260913-v2`).

| ID | 행 | 구간 | 항목(B열 앞부분) | 영역코드(AD) | 척도(AY) | 축(I) | 자료형 | 허용값 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BS-01 | 5 | 입장 | 꼬리 | SOC_E | BI | 각성 | scale | 1~5 |
| BS-02 | 6 | 입장 | 발성 | SOC_E | BI | 각성 | scale | 1~5 |
| BS-03 | 7 | 입장 | 낯선 바닥 — 꼬리 | SOC_E | BI | 각성 | scale | 1~5 |
| BS-04 | 8 | 입장 | 낯선 바닥 — 몸 털기 | 참고 | — | — | count | 정수 ≥ 0 |
| BS-05 | 9 | 혼자 | 꼬리 | ATT | BI | 각성 | scale | 1~5 |
| BS-06 | 10 | 혼자 | 분리 — 몸 털기 | 참고 | — | — | count | 정수 ≥ 0 |
| BS-07 | 11 | 낯선 | 꼬리 | SOC_H | BI | 각성 | scale | 1~5 |
| BS-08 | 12 | 걷기 | 꼬리 | SYN | BI | 각성 | scale | 1~5 |
| BS-09 | 13 | 퇴장 | 꼬리 | EXIT | BI | 각성 | scale | 1~5 |
| DOG-01 | 5 | 입장 | 방 문 통과 | SOC_E | BI | 각성 | scale | 1~5 |
| DOG-02 | 6 | 입장 | 비닐 바닥 통과 | SOC_E | BI | 사회화 | scale | 1~5 |
| DOG-03 | 7 | 입장 | 냄새 | 참고 | — | — | scale | 3, 5 |
| DOG-04 | 8 | 기준 | 각성 (기준선) | 참고 | — | — | scale | 1~5 |
| DOG-05 | 9 | 혼자 | 블라인드(나간 쪽) 지향 | ATT | BI | 애착 | scale | 1~5 |
| DOG-06 | 10 | 혼자 | 각성 | ATT | BI | 각성 | scale | 1~5 |
| DOG-07 | 11 | 혼자 | 발성 | 참고 | — | — | scale | 1~5 |
| DOG-08 | 12 | 혼자 | 탐색량 변화 | 참고 | — | — | scale | 1~5 |
| DOG-09 | 13 | 낯선 | 우호성 — 다가가는가 | SOC_H | BI | 우호 | scale | 1~5 |
| DOG-10 | 14 | 낯선 | 각성 | SOC_H | BI | 각성 | scale | 1~5 |
| DOG-11 | 15 | 낯선 | 이름을 불렀을 때 | SOC_H | BI | 우호 | scale | 1~5 |
| DOG-12 | 16 | 재회 | 다가오는가 | ATT | BI | 애착 | scale | 1~5 |
| DOG-13 | 17 | 재회 | 진정 | ATT | BI | 각성 | scale | 1~5 |
| DOG-14 | 18 | 재회 | 접촉 — 몸의 중심 | ATT | BI | 애착 | scale | 1~5 |
| DOG-15 | 19 | 재회 | 접촉 — 꼬리 | ATT | BI | 각성 | scale | 1~5 |
| DOG-16 | 20 | 재회 | 접근의 일관성 | 참고 | — | — | count | 정수 ≥ 0 |
| DOG-17 | 21 | 무시 | 접촉 개시 | ATT | BI | 애착 | scale | 1~5 |
| DOG-18 | 22 | 무시 | 각성 | ATT | BI | 각성 | scale | 1~5 |
| DOG-19 | 23 | 걷기 | 거리 유지 | SYN | BI | 거리 | scale | 1~5 |
| DOG-20 | 24 | 걷기 | 보호자 확인 | SYN | BI | 거리 | scale | 1~5 |
| DOG-21 | 25 | 걷기 | 동조 국면 수 | 참고 | — | — | phase_count | 0~6 |
| DOG-22 | 26 | 걷기 | 동조율 | 참고 | — | — | auto_ratio | 입력 없음(계산) |
| DOG-23 | 27 | 퇴장 | 방 문 통과 | EXIT | BI | 각성 | scale | 1~5 |
| DOG-24 | 28 | 퇴장 | 냄새 | 참고 | — | — | scale | 3, 5 |
| OWN-01 | 5 | 전 구간 | 목소리 톤 | EDU | BI | (없음) | scale | 1~5 |
| OWN-02 | 6 | 전 구간 | 리드줄 | EDU | BI | (없음) | scale | 1~5 |
| OWN-03 | 7 | 전 구간 | 지시·말 반복 | EDU | BI | (없음) | scale | 1~5 |
| OWN-04 | 8 | 전 구간 | 시선 | EDU | ONE | (없음) | scale | 3~5 |
| OWN-05 | 9 | 전 구간 | 유도 방식 | EDU | BI | (없음) | scale | 1~5 |
| OWN-06 | 10 | 혼자 | [분리] 나갈 때 | 참고 | — | — | scale | 1~5 |
| OWN-07 | 11 | 재회 | [재회] 들어올 때 | 참고 | — | — | scale | 1~5 |
| OWN-08 | 12 | 무시 | [무시] 지시 준수 | 참고 | — | — | scale | 1~3 |
| OWN-09 | 13 | 걷기 | [걷기] 시행 유효성 | 참고 | — | — | scale | 1~3 |

검산: 채점 28 = SOC_E 5 · SOC_H 4 · ATT 9 · SYN 3 · EDU 5 · EXIT 2. 참고 14 = BS 2 · DOG 8 · OWN 4. 채점자가 입력하는 항목은 42 − DOG-22 = **41개**.

허용값은 C~G열에 라벨이 있는 점수만이다. 엑셀 도우미 열 `AE = IF(J="",0,IF(INDEX(C:G,J)="",0,J))`가 라벨 없는 점수를 0(무효)으로 만들므로, 프로그램은 같은 값을 **입력 단계에서 거절**한다.

## 2. 규칙 해석 — 코드에 넣되 고객 확인이 필요한 것

변경검토 7장 1·2번을 코드 수준으로 구체화한 목록이다. 각 항목은 `resources/rules/scoring-v2.json`에 데이터로 두어 회신 뒤 한 줄로 바꿀 수 있게 한다.

| # | 해석 | 근거 | 확인 필요 |
| --- | --- | --- | --- |
| R1 | 참고 항목 자료형은 B열 문구로 판정: `※횟수`→count, `※0~6`→phase_count, `※자동 계산`→auto_ratio, 그 외→scale | 03 B열 | 7장 1번 |
| R2 | 냄새 2항목은 3·5만, 시선은 3~5만, 지시 준수·시행 유효성은 1~3만 허용 | 03 C~G 라벨 유무, AE 수식 | 7장 1번 |
| R3 | 영역 평균(lean의 재료)은 `AY="BI"` 항목만, **폭은 BI·ONE을 함께** 본다 | `여러쌍비교!D6`은 AY 조건 있음, `E6`은 없음 | 수식 그대로 — 확인만 |
| R4 | 애착 유형의 재료 6개(DOG-05·12·13·14·17, DOG-16 횟수) 중 하나라도 scored가 아니면 유형 없음 | 01 §4 「재료 중 하나라도 미판독이면 유형을 내지 않는다」. 단 엑셀 `M6`은 J18(몸의 중심)을 빈칸 검사에서 빼고 J20 빈칸을 0으로 본다 | **문서와 수식이 다름** — 문서를 따르고 확인 |
| R5 | 걷기 시행 유효성 = 3이면 동조율 「무효」(엑셀 `Z6`과 동일) **그리고** 걷기 항목(BS-08·DOG-19·20·21) 을 SYN 집계에서 제외 | 03 3_보호자행동 C13 라벨 「이 시행의 걷기 항목과 동조율 무효」. 엑셀 `P6·Q6`은 제외하지 않음 | **라벨과 수식이 다름** — 라벨을 따르고 확인 |
| R6 | 무시 지시 준수 = 3이면 무시 항목(DOG-17·18)을 ATT 집계·애착 유형·적응 지표에서 제외 | 03 3_보호자행동 C12 라벨. 엑셀 `V6·M6`은 검사하지 않음 | 위와 같음 |
| R7 | 설문 「해당 없음」(7~9)과 빈칸은 모두 결측. 영역 평균은 응답한 문항만으로 내고 응답 수/문항 수를 함께 기록 | 04 문항근거 「결측이지 0점이 아니다」 | 평균 방식 확인 |
| R8 | 설문 D(22~25)는 합산하지 않고 저항=(22+23)/2, 회복=24로 4유형. 25는 유형·평균 어디에도 넣지 않고 값만 저장 | 04 문항근거 §2 | — |
| R9 | 총점·전체 참고값은 만들지 않는다 (옛 `overall_reference` 폐지) | 01 §6 | — |

R5·R6은 05 예비촬영 6쌍에서 발동하지 않으므로(해당 칸이 비어 있음) 골든 테스트 결과에 영향이 없다. 합성 사례로 별도 시험한다.

## 3. PR-0 정리 (코드 삭제 없음)

목적: 이후 PR의 diff에서 줄바꿈 노이즈를 없애고, 폐기 상태를 문서·데이터에 표시한다.

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `.gitattributes` | 신설 | `* text=auto eol=lf`, `*.cmd text eol=crlf`, xlsx/docx/pdf/png/ttf/zip/ico를 `binary`. 로컬 `core.autocrlf` 설정과 무관하게 인덱스 LF를 고정한다. `git add --renormalize .` 결과가 빈 diff여야 한다 |
| `resources/rules/pending-v1.json` | 변경 | `status: "superseded"`, `superseded_by`(변경검토 7장), `superseded_on: 2026-09-15` 필드 추가. 규칙 4개 본문은 그대로(옛 run 읽기용). `test_catalog_import.test_pending_rules…`는 그대로 통과 |
| `AGENTS.md` | 변경 | Project Structure에 `docs/K-DOG_P0_구현계획…` 링크, Commit 절의 「single existing commit」 문구를 PR 절차로 교체. `import_catalogs.py` 원본 위치와 `backend/app/legacy/`는 실제로 바뀌는 PR-1·PR-3에서 반영 |
| `docs/README.md` | 변경 | 이 계획 문서 행 추가 |
| `docs/DEVELOPMENT.md` | 변경 | 검증 명령 절에 시험 실행이 `backend/`에서만 유효함을 명시(상위 폴더에서는 `tests`가 import되지 않음) |
| `_to_delete/` | 조치 없음 | `.gitignore`로 제외된 비추적 폴더. 수동 삭제 대기 상태를 그대로 둔다 |

시험: 기존 166개 통과 유지. 완료 기준: `git status` 클린, `git ls-files --eol`에서 `attr/text=auto eol=lf`가 텍스트 파일 전부에 표시.

## 4. PR-1 N1 카탈로그 42 이관

목적: 03 엑셀 시트 1~3을 읽어 `resources/catalogs/behavior-v2.json`을 만들고, `--check`로 대조한다. 옛 `read_behavior`(55항목 리더)는 이 PR에서 삭제한다(대체물이 들어오므로). `behavior-v1.json` 파일은 legacy 런타임과 `test_catalog_import`가 쓰므로 남긴다.

### 4.1 신설 `backend/app/domain/base.py`

옛 `contracts.py`의 공통 원시형을 v2 계열이 공유하도록 뗀다. legacy(v1)는 자기 사본을 그대로 쓰고 이 모듈을 import하지 않는다.

```python
Text, Identifier, Hash, Nonnegative, Positive, Revision   # 옛 정의와 동일
class Contract(BaseModel): extra="forbid", strict=True, frozen=True, allow_inf_nan=False, revalidate_instances="always"
    schema_version: Literal["2.0"] = "2.0"
def require_unique(values, label) -> None
```

### 4.2 신설 `backend/app/domain/catalog.py`

```python
Sheet = Literal["1_바디시그널", "2_개행동", "3_보호자행동"]
SegmentId = Literal["entry","baseline","alone","stranger","reunion","ignore","walk","exit"]
SEGMENTS: tuple[tuple[SegmentId, str], ...]        # (id, A열 라벨) 8개, 절차 순서
DomainCode = Literal["SOC_E","SOC_H","ATT","SYN","EDU","EXIT"]
Axis = Literal["애착","우호","사회화","각성","거리"]
Scale = Literal["BI","ONE"]
ValueType = Literal["scale","count","phase_count","auto_ratio"]
BehaviorId = pattern ^(BS-0[1-9]|DOG-(0[1-9]|1[0-9]|2[0-4])|OWN-0[1-9])$
BEHAVIOR_IDS: 42개 튜플

class ScaleLabel(Contract): score: Literal[1,2,3,4,5]; text: Text; source_cell: Text
class CatalogItem(Contract):
    item_id: BehaviorId; sheet: Sheet; source_row: Revision
    segment_label: Text            # A열 원문 (입장 … 전 구간)
    segment: SegmentId | None      # 「전 구간」은 None
    text: Text                     # B열 원문
    domain_label: Text             # H열 원문
    domain: DomainCode | None      # AD열. None = 참고
    axis_label: Text               # I열 원문
    axis: Axis | None
    scale: Scale | None            # AY열. 참고는 None
    value_type: ValueType
    labels: tuple[ScaleLabel, ...] # C~G 중 값이 있는 칸
    allowed_scores: tuple[int, ...]  # scale: 라벨 있는 점수 / count: () / phase_count: 0..6 / auto_ratio: ()
    note: Text | None              # count·phase_count·auto_ratio 항목의 C열 설명문
    @model_validator: 참고 ⇔ domain None ⇔ scale None; scale 항목은 labels ≥ 1; auto_ratio는 labels 없음
class BehaviorCatalog(Contract):
    version: Text; source_filename: Text; source_sha256: Hash
    provenance: Literal["excel_verified","test_fixture"]
    items: tuple[CatalogItem, ...]
    @model_validator: 42개 정확히, 영역 수 {SOC_E:5,SOC_H:4,ATT:9,SYN:3,EDU:5,EXIT:2,None:14}
    def rated_items(self) -> tuple[CatalogItem, ...]   # value_type != auto_ratio (41)
    def by_id(self) -> dict[str, CatalogItem]
```

### 4.3 변경 `backend/app/import_catalogs.py`

- 상수: `CUSTOMER_DIR = ROOT / "docs/최종 고객 문서"`, `BEHAVIOR_V2_FILE = "03_행동_채점표_42항목_20260913.xlsx"`, `V2_VERSION = "catalog-20260913-v2"`.
- `read_behavior_v2(path: Path) -> BehaviorCatalog`: 시트마다 4행 헤더 검사(`A4 구간·B4 관찰 항목·C4~G4 '1'~'5'·H4 영역·I4 척도·축·AD4 영역코드·AY4 척도`), 5행부터 B열이 빈 행 직전까지 읽는다. 셀이 수식이면 오류. `segment`는 A열→`SEGMENTS`, `axis`는 I열의 `양쌍·<축>` 접미로, `value_type`은 규칙 R1로 판정. 읽기 전후 파일 해시 동일 확인(옛 방식 유지).
- `read_behavior`(v1) 삭제, `GROUPS`·`DOMAIN_MAP`·`BEHAVIOR_FILE` 삭제. `read_survey`(v1)는 PR-2까지 유지.
- `main`: `behavior-v2.json`(03 엑셀)과 `survey-v1.json`(옛 원본, PR-2에서 교체)을 다룬다. `--source-dir`는 옛 원본 폴더, 새 인자 `--customer-dir`(기본 `docs/최종 고객 문서`)는 42항목 판 원본 폴더.

### 4.4 신설 `resources/catalogs/behavior-v2.json`

위 리더의 출력. `source_sha256`은 03 엑셀 실제 해시.

### 4.5 시험 `backend/tests/test_catalog_v2.py` (신설)

- 42개·시트별 9/24/9·영역 수·참고 14·rated 41.
- 항목마다 `text/segment_label/domain_label/axis_label`이 원본 셀과 같고, `labels`가 C~G의 비어 있지 않은 칸과 정확히 일치하며 `source_cell` 열이 점수와 대응.
- 1장 표의 `value_type`·`allowed_scores`가 전 항목에서 일치(표를 시험 상수로 박아 둠 — 이 표가 규칙 R1·R2의 명문화다).
- `--check` 경로: JSON 재생성 결과가 파일과 바이트 동일.
- 원본 해시 일치.
- `test_catalog_import.py`: v1 리더 삭제에 영향 없음(엑셀을 직접 읽어 대조하므로) — 변경 없음.

### 4.6 문서

`DEVELOPMENT.md` 「원본 항목집 이관」에 v2 명령·`--customer-dir`·산출물 설명. 완료 기준: `--check` 통과, 신규 시험 통과, 기존 166개 통과.

## 5. PR-2 N2 설문 28 이관

목적: 04 설문지 PDF를 원본으로 `survey-v2.json`을 만들고, 옛 30문항 → 새 28문항 매핑표를 둔다. 옛 `read_survey`(30문항 리더)는 이 PR에서 삭제한다. `survey-v1.json` 파일은 남긴다(legacy 런타임·시험). 설문 **계산**은 PR-4에서 한다.

### 5.1 변경 `backend/app/domain/catalog.py`

```python
SurveyId = pattern ^s(0[1-9]|1[0-9]|2[0-8])$ ; SURVEY_IDS 28개
SurveyDomain = Literal["A","B","C","D","E"]
SURVEY_DOMAINS: {"A": (1..9, "나의 교육 방식"), "B": (10..14, "우리 아이의 사회성"), "C": (15..21, "정서적 친밀감"), "D": (22..25, "떨어져 있을 때 우리 아이는"), "E": (26..28, "나의 감정 기복")}
class SurveyItem(Contract): item_id: SurveyId; number: 1..28; text: Text; domain: SurveyDomain; allows_not_applicable: bool; source_page: 1|2
class SurveyCatalog(Contract): version; source_filename; source_sha256; provenance; response_scale: ("전혀 아니다","아니다","보통","그렇다","매우 그렇다"); items 28개 정확히; 번호 연속; 7~9만 allows_not_applicable
```

역채점(26~28)·분리 유형 규칙은 카탈로그가 아니라 `scoring-v2.json`(PR-4)에 둔다. 카탈로그는 설문지에 적힌 것만 담는다.

### 5.2 변경 `backend/app/import_catalogs.py`

- `SURVEY_V2_FILE = "04_보호자_설문지_28문항.pdf"`. `read_survey_v2(path) -> SurveyCatalog`: `pypdf`로 두 페이지 텍스트를 뽑아 `^([A-E])\. (.+?)\s{2,}①` 로 영역 머리, `^(\d{1,2}) (.+?)\s*(□)?\s*$` 로 문항을 읽는다. `□`가 있는 문항만 `allows_not_applicable`. 28개·번호 연속·영역 경계(1~9·10~14·15~21·22~25·26~28) 검사.
- `pypdf`는 dev 그룹 의존성이다. 이관기는 개발 도구이므로 그대로 두고, 모듈 상단이 아니라 함수 안에서 import한다(런타임 패키지에서 import 실패 방지).
- `read_survey`(v1)·`SURVEY_FILE`·`--source-dir` 삭제. `main`은 `behavior-v2.json`·`survey-v2.json` 두 개만 다룬다.

### 5.3 신설 `resources/catalogs/survey-v2.json`, `resources/catalogs/survey-v1-to-v2.json`

매핑표는 문항 **문장이 동일한** 쌍만 연결한다.

```json
{"schema_version": "2.0", "from": "catalog-20260904-v1", "to": "catalog-20260913-v2",
 "mapping": {"q01":"s01", … "q06":"s06", "q07":null, "q08":null, "q09":"s10", … "q13":"s14", "q14":null,
             "q15":"s15", … "q21":"s21", "q22":"s22", "q23":"s23", "q24":"s24", "q25":null,
             "q26":"s26", "q27":"s27", "q28":"s28", "q29":null, "q30":null},
 "new_without_source": ["s07","s08","s09","s25"],
 "note": "옛 q25(놀 때 주고받는 흐름)와 새 25(다른 방으로 가면 따라온다)는 문장이 달라 연결하지 않는다. 옛 q22 역채점·q23 미정 규칙은 새 판에 없다."}
```

### 5.4 시험 `backend/tests/test_survey_v2.py` (신설)

- 28개·영역 경계·`allows_not_applicable == {s07,s08,s09}`·원본 해시.
- 문항 문장이 04 문항근거 docx §2 표의 문장과 전부 일치(docx 본문 문단에서 검색).
- 매핑표: 연결된 쌍은 `survey-v1.json`·`survey-v2.json`의 text가 같고, `null`인 옛 문항은 새 판에 같은 문장이 없고, `new_without_source`는 옛 판에 같은 문장이 없다.
- `--check` 재생성 동일.
- `test_catalog_import.py`의 survey 시험은 그대로(엑셀 직접 대조).

문서: `DEVELOPMENT.md` 이관 절 갱신. 완료 기준: 위 시험 + `--check` + 기존 시험 통과.

## 6. PR-3 N3 계약 v2

목적: `app/domain/contracts.py`를 42항목 판 계약으로 바꾼다. 옛 계약·문맥 검증은 `app/legacy/`로 옮겨 읽기 전용으로 두고, 이를 쓰는 인프라 모듈의 import만 바꾼다(동작 변화 없음). 이 PR에서 **활성 계약**에서 사라지는 것: `Direction`(A/B), 55항목 `BEHAVIOR_IDS`, 선택지 ID(`BS-01:S3`) 검증, `rule_pending` 등 8상태, 30문항 `SURVEY_IDS`, `ReportDomain` 슬롯 1~4·`CrossType`.

### 6.1 이동 (git mv, 내용 변경 없음)

| 원위치 | 새 위치 |
| --- | --- |
| `backend/app/domain/contracts.py` | `backend/app/legacy/contracts_v1.py` |
| `backend/app/domain/validation.py` | `backend/app/legacy/validation_v1.py` (상대 import `.contracts` → `.contracts_v1`) |
| `backend/tests/test_contracts.py` | `backend/tests/test_legacy_contracts.py` (import 경로만) |

`backend/app/legacy/__init__.py` 신설: 「55항목 판(2026-09-04) 계약. 저장된 옛 run을 읽는 용도. 기능 추가 금지. 각 인프라 모듈이 42항목 판으로 교체되는 PR에서 함께 삭제」.

### 6.2 import 경로 변경 (동작 변화 없음)

`app.domain.contracts` → `app.legacy.contracts_v1`, `app.domain.validation` → `app.legacy.validation_v1`:
`analysis.py`(2곳+지연 import 1곳), `api.py`, `developer_sample.py`, `evaluation.py`, `evaluation_models.py`, `gemini.py`(지연 import), `ledger.py`, `observation_models.py`(2곳), `reporting.py`(+지연 import), `report_models.py`, `video_evaluation.py`, `video_models.py`, `worker.py`, `scoring.py`, `tests/test_evaluation.py`, `tests/test_video_evaluation.py`, `tests/test_catalog_import.py`(v1 `BehaviorCatalog`·`SurveyCatalog`).

### 6.3 신설(교체) `backend/app/domain/contracts.py`

```python
from .base import Contract, Text, Identifier, Hash, Nonnegative, Positive, Revision, require_unique
from .catalog import BehaviorId, BEHAVIOR_IDS, SegmentId, SEGMENTS, DomainCode, SurveyId, SURVEY_IDS, ...

ScoreStatus = Literal["scored", "unreadable", "not_applicable"]
class ItemScore(Contract):
    item_id: BehaviorId; score: int | None; status: ScoreStatus; reason: Text | None = None
    # scored ⇒ score is int ; 그 외 ⇒ score None & reason 필수. bool 거절. 값 범위는 validation에서 카탈로그로 검사
RaterKind = Literal["ai", "human"]
class Rater(Contract): rater_id: Identifier; kind: RaterKind; label: Text | None = None
class ScoreSheet(Contract):
    sheet_id: Identifier; case_id: Identifier; session_id: Identifier
    catalog_version: Text; rater: Rater; recorded_at: Text(ISO 8601)
    items: tuple[ItemScore, ...]          # 41개 정확히(auto_ratio 제외), 중복 금지
class SegmentWindow(Contract):
    segment: SegmentId; start_sec: Nonnegative; end_sec: Nonnegative
    source: Literal["ai_proposed", "operator_confirmed"]
class SessionSegments(Contract):
    session_id: Identifier; video_id: Identifier; windows: 8개, SEGMENTS 순서, end ≥ start, 겹침 없음, 앞 구간 end ≤ 뒤 구간 start
    def confirmed(self) -> bool           # 전부 operator_confirmed
class SurveyAnswers(Contract):
    answers: dict[SurveyId, Literal[1,2,3,4,5] | None]   # 28개 키 정확히
    not_applicable: tuple[SurveyId, ...] = ()           # allows_not_applicable 문항만, 해당 답은 None
# 계산 결과 (PR-4가 채움)
class DomainSummary(Contract):
    domain: DomainCode; target_count; scored_count; unreadable_count; not_applicable_count; excluded_count(무효 규칙)
    mean: float | None; lean: float | None; width: int | None (0~2); degree: float | None
    # scored_count==0 ⇒ mean/lean/width None ; BI scored 없음 ⇒ mean/lean None ; ONE scored 없음 ⇒ degree None
IndicatorKey = Literal["adaptation", "recovery", "stranger_calming", "sync_rate"]
class Indicator(Contract): key; value: float | None; status: Literal["calculated","missing","invalid"]; reason: Text | None
AttachmentType = Literal["안정","불안","거리 둠","일관되지 않음"]
SociabilityType = Literal["편안·우호","우호·들뜸","담담·거리둠","경계·긴장"]
class TypeResult(Contract): key: Literal["attachment","sociability_person"]; label: str | None; status; reason
class ScoreResult(Contract):
    sheet_id; catalog_version; scoring_rule_version; rater
    items: tuple[ItemScore, ...]          # 42개 (DOG-22 계산값 포함)
    baseline_arousal: int | None
    domains: 6개(DomainCode마다 하나); indicators: 4개; types: 2개
class SurveyDomainScore(Contract): domain: Literal["A","B","C","E"]; mean: float | None; answered_count; target_count; status: Literal["calculated","partial","missing"]
SeparationType = Literal["안정","불안","회피 쪽","무덤덤"]
class SurveyResult(Contract):
    catalog_version; scoring_rule_version
    items: 28개 (item_id, raw, converted, not_applicable: bool)
    domains: 4개; separation: {resistance, recovery, label: SeparationType|None, status}
    status: Literal["calculated","partial","unregistered"]
```

금지 사항을 계약에 박는다: 총점 필드 없음, Ainsworth 용어(`secure/avoidant/ambivalent/disorganized`) 라벨 거절(`TypeResult.label` 검사).

### 6.4 신설(교체) `backend/app/domain/validation.py`

```python
def validate_score_sheet(sheet: ScoreSheet, catalog: BehaviorCatalog) -> None
    # 항목 집합 == catalog.rated_items ; scored 값이 allowed_scores(scale/phase_count) 또는 정수 ≥ 0(count)
    # catalog.version == sheet.catalog_version ; provenance excel_verified(운영) / test 모드 명시
def validate_segments(segments: SessionSegments, duration_sec: float) -> None   # 마지막 end ≤ 영상 길이
def validate_survey_answers(answers: SurveyAnswers, catalog: SurveyCatalog) -> None
```

### 6.5 시험 `backend/tests/test_contracts.py` (신설, v2)

- `ItemScore`: scored+None 점수 거절, unreadable+점수 거절, unreadable에 사유 없음 거절, bool 거절, 0은 count 항목에서 유효(빈칸과 0 구분).
- `ScoreSheet`: 40개·43개·중복·DOG-22 포함 거절. `validate_score_sheet`: 냄새 4점, 시선 2점, 지시 준수 4점, 국면 수 7, 횟수 −1 거절; 몸 털기 0 허용.
- `SessionSegments`: 순서 바뀜·겹침·7개 거절; `confirmed()`.
- `SurveyAnswers`: 27개·s29 거절, `not_applicable`에 s10 거절, NA 문항에 값 있음 거절.
- 결과 계약 불변식(빈 영역 None, width 범위, 6/4/2 개수, Ainsworth 라벨 거절).
- JSON 스키마 생성·왕복.
- `test_legacy_contracts.py` 19개 그대로 통과(경로만 바뀜).

문서: `DEVELOPMENT.md` 「데이터 계약 사용」 절을 v2 기준으로, legacy 패키지의 의미를 한 문단 추가. 완료 기준: 신규 시험 + 166개(경로 변경 후) 통과, `python -m app.launcher --help`류 import 오류 없음(`test_packaging` 통과로 확인).

## 7. PR-4 N4 계산 v2 + 골든 테스트

목적: `app/scoring.py`를 42항목 판 계산으로 바꾼다. 옛 `scoring.py`(A/B 합·30문항)는 `app/legacy/scoring_v1.py`로 옮기고 import를 바꾼다. 옛 규칙 파일 `scoring-v1.json`은 legacy 런타임(`RULES["version"]` 비교, `launcher.required`)이 읽으므로 남긴다.

### 7.1 이동

`backend/app/scoring.py` → `backend/app/legacy/scoring_v1.py` (import를 `.contracts_v1`·`.validation_v1`로). import 변경: `analysis.py`, `developer_sample.py`, `evaluation.py`, `reporting.py`, `video_evaluation.py`, `worker.py`, `tests/test_evaluation.py`.

### 7.2 신설 `resources/rules/scoring-v2.json`

```json
{"schema_version": "2.0", "version": "scoring-v2", "catalog_version": "catalog-20260913-v2",
 "source": {"workbook": "03_행동_채점표_42항목_20260913.xlsx", "sheet": "여러쌍비교", "cells": "D6:Z6", "document": "01_개발_요구사항 §4"},
 "center": 3, "rounding": {"decimal_places": 2, "mode": "ROUND_HALF_UP"},
 "domain_output": {"EDU": "lean", "SOC_E": "lean", "SOC_H": "type", "ATT": "type", "SYN": "lean", "EXIT": "lean"},
 "mean_scales": ["BI"], "width_scales": ["BI", "ONE"], "degree_scales": ["ONE"],
 "roles": {"baseline_arousal": "DOG-04", "alone_arousal": "DOG-06", "stranger_affiliation": "DOG-09", "stranger_arousal": "DOG-10",
           "reunion_approach": "DOG-12", "reunion_calm": "DOG-13", "reunion_body": "DOG-14", "approach_consistency": "DOG-16",
           "ignore_contact": "DOG-17", "ignore_arousal": "DOG-18", "alone_orientation": "DOG-05",
           "sync_phase_count": "DOG-21", "sync_rate": "DOG-22", "ignore_compliance": "OWN-08", "walk_validity": "OWN-09"},
 "indicators": {"adaptation": {"formula": "|baseline_arousal-3| - |ignore_arousal-3|", "cell": "V6"},
                "recovery": {"formula": "|alone_arousal-3| - |reunion_calm-3|", "cell": "W6"},
                "stranger_calming": {"formula": "|alone_arousal-3| - |stranger_arousal-3|", "cell": "X6"},
                "sync_rate": {"formula": "sync_phase_count / 6", "cell": "Z6"}},
 "types": {"attachment": {"cell": "M6", "consistency_threshold": 1, "degree_items": ["ignore_contact","alone_orientation","reunion_approach","reunion_body"],
                          "degree_threshold": 3.5, "calm_item": "reunion_calm", "calm_tolerance": 1,
                          "required": ["ignore_contact","alone_orientation","reunion_approach","reunion_body","reunion_calm","approach_consistency"]},
           "sociability_person": {"cell": "J6", "affiliation_item": "stranger_affiliation", "affiliation_threshold": 3, "arousal_item": "stranger_arousal", "calm_tolerance": 1}},
 "invalidation": {"ignore": {"item": "OWN-08", "invalid_score": 3, "excludes": ["DOG-17", "DOG-18"], "voids_indicators": ["adaptation"], "voids_types": ["attachment"]},
                  "walk":   {"item": "OWN-09", "invalid_score": 3, "excludes": ["BS-08", "DOG-19", "DOG-20", "DOG-21"], "voids_indicators": ["sync_rate"], "voids_types": []}},
 "survey": {"reverse_items": ["s26","s27","s28"], "not_applicable_items": ["s07","s08","s09"],
            "domain_means": {"A": ["s01".."s09"], "B": ["s10".."s14"], "C": ["s15".."s21"], "E": ["s26".."s28"]},
            "separation": {"resistance_items": ["s22","s23"], "recovery_item": "s24", "resistance_threshold": 3.5, "recovery_high": [4,5],
                           "labels": {"high_high": "안정", "high_low": "불안", "low_high": "회피 쪽", "low_low": "무덤덤"}},
            "stored_only": ["s25"], "total": "forbidden"},
 "interpretations": ["R3", "R4", "R5", "R6", "R7"]}
```

### 7.3 신설(교체) `backend/app/scoring.py`

```python
RULES = json.loads(resources/rules/scoring-v2.json)
def rounded(value: Decimal | None) -> float | None            # ROUND_HALF_UP 2자리 (엑셀 ROUND와 동일)
def behavior_scores(sheet: ScoreSheet, catalog: BehaviorCatalog, *, mode="production") -> ScoreResult
    # 1 validate_score_sheet ; 2 무효 규칙으로 제외 집합 산출 ; 3 DOG-22 계산값 생성(status scored/unreadable/… + reason "무효")
    # 4 영역 6개: mean(BI scored, 제외 밖) → lean=round(mean-3) ; width=max|x-3| (BI+ONE) ; degree=round(mean ONE)
    # 5 지표 4개 ; 6 유형 2개 ; 7 baseline_arousal
def survey_scores(answers: SurveyAnswers, catalog: SurveyCatalog) -> SurveyResult
    # converted = 6-raw (s26~s28) ; 영역 평균(A·B·C·E) 응답 문항만 ; 분리 유형 ; 총점 없음
```

내부 도우미: `_scored_value(items, item_id) -> int | None`, `_abs_distance(v) = |v-3|`, `_indicator(key, inputs, voided)`. 모두 `Decimal`로 계산하고 마지막에만 반올림.

### 7.4 시험

`backend/tests/test_scoring_golden.py` (신설) — 05 `예비촬영_6쌍_채점_20260913.xlsx`의 J~O열(6쌍)을 읽어 `ScoreSheet`를 만든다(빈칸 → `unreadable`, 사유 「05 빈칸」). 기대값은 03 `여러쌍비교!D6:Z6` 수식을 손으로 계산해 시험 상수로 둔다.

| 쌍 | EDU lean/width/degree | SOC_E lean/width | SOC_H 유형/width | ATT 유형/width | SYN lean/width | EXIT lean/width | 적응 | 회복 | 낯선 진정 | 기준 | 동조율 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 천우미 | 0.00 / 0 / 3.00 | −0.20 / 1 | 담담·거리둠 / 1 | 없음(무시 빈칸) / 1 | −0.33 / 1 | 0.00 / 0 | 없음 | 1 | 1 | 없음 | 5/6 |
| 2 김지유 | 없음 | 0.00 / 0 | 없음 | 없음 / 0 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 — 시행 유효성 3이라 `invalid`(엑셀 `Z6`은 국면 수 빈칸을 먼저 보고 빈칸을 낸다. 값은 둘 다 없음, 상태는 무효 우선) |
| 3 배보경 | 없음 | 0.00 / 0 | 없음 | 없음 / 1 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 |
| 4 최선미 | 전부 없음 | | | | | | | | | | |
| 5 이하연 · 6 송소연 | 없음 | 0.00 / 0 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 | 없음 |

`backend/tests/test_scoring.py` (신설) — 합성 사례: BI 1과 5가 한 영역이면 lean 0·width 2; ONE만 있는 영역은 mean None·width 계산; 무효 규칙 R5·R6 발동(동조율 invalid, SYN에서 걷기 항목 제외, 적응 invalid·애착 유형 invalid); 애착 유형 4갈래 + 일관성 ≥ 1 우선; 사회성 4갈래 경계값(우호 3, 각성 2·4); 반올림 half-up(2.665→2.67, −0.335→−0.34); 설문 역채점·NA 결측·분리 유형 4갈래·s25 미포함·총점 필드 없음; 결과 JSON 왕복.

`backend/tests/test_evaluation.py`: import 경로만 변경(legacy). 완료 기준: 골든 6쌍 전부 일치, 신규 시험 통과, 기존 시험 통과.

### 7.5 문서

`DEVELOPMENT.md`에 계산 규칙 파일·골든 테스트 설명 추가. `변경검토` 7장 1·2번을 이 문서 2장의 R1~R9로 구체화했음을 변경검토에 한 줄 링크.

## 8. P1 PR 목차 (PR 단위까지만 — 파일 계획은 PR-4 완료 뒤)

화면은 **대메뉴 단위로 PR을 나눈다**. 한 PR이 한 메뉴(라우트·컴포넌트 묶음·API)만 바꾼다.

| PR | 메뉴/영역 | 내용 | 의존 |
| --- | --- | --- | --- |
| PR-5 | 저장 | `storage.py`: 채점 시트 테이블(채점자×쌍×항목), 세션 8구간 시각, 카메라 역할(360/고정) 열. 마이그레이션·백업 시험 | PR-3 |
| PR-6 | 접수 메뉴 | 참가자·반려견 등록, 동의, 순번. `Importer/SessionEditor` 정리 | PR-5 |
| PR-7 | 설문 메뉴 | 28문항 입력·「해당 없음」·즉시 계산 표시(숫자 아님, 영역 채우기). `SurveyEditor.tsx` 교체, `intake.py` 28문항 API | PR-2·PR-4·PR-5 |
| PR-8 | 촬영 메뉴 | 카메라 2대 파일 연결, 8구간 시각 입력·확정, 확정 전 채점 잠금. `VideoUpload.tsx` 확장 + 새 `Segments.tsx` | PR-5 |
| PR-9 | 전처리 | `media.py`: 구간 절단·equirectangular 크롭·창별 fps. 산출물 불변 파일·해시. 9월 13일 영상으로 시험 | PR-8, 07 장비 문서 |
| PR-10 | 옛 화면 제거 | `Scores/Reports/Observations/VideoAssessments` 및 그에 묶인 API·legacy 조각 삭제. 옛 run 읽기 전용 뷰만 유지 | PR-6~8 |
| PR-11 | 패키징 | `launcher.required`·`build_release`·설치 패키지 갱신, 72쌍 접수→절단→저장 리허설 | PR-9·PR-10 |

## 9. 완료 기준 요약

- PR-0: 줄바꿈 정규화 후 빈 diff, 폐기 표시, 166개 통과.
- PR-1: `behavior-v2.json` 42개, `--check` 통과, 1장 표와 카탈로그 일치.
- PR-2: `survey-v2.json` 28개, 매핑표 문장 검증, `--check` 통과.
- PR-3: v2 계약 시험 통과, legacy 격리 후 기존 시험 전부 통과, 활성 계약에서 A/B·선택지·55·30이 사라짐.
- PR-4: 05 예비촬영 6쌍 골든 테스트가 03 `여러쌍비교` 수식 기대값과 일치. **이것이 변경검토 6장 P0의 완료 기준이다.**
