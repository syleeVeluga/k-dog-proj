# PR-R02 리포트 입력 묶음(ReportInput)과 장 선택 규칙

버전: v1.0 · 2026-09-16 · 상태: 구현 계획 · 의존: [R01](K-DOG_PR-R01_채점시트저장_v1.0_20260916.md) · 다음: [R03](K-DOG_PR-R03_HTML템플릿과그래픽_v1.0_20260916.md)

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md) §3 대응표. 근거: 06b `00_읽어주세요` 「리포트마다 장 수가 다릅니다」 표, 01 §6, 04 §2(하위요인)·§3(설문↔영상 대응), 02 §5.

## 목적

리포트 생성의 **결정적 절반**을 화면·AI 없이 완성한다. 한 쌍의 채점 시트·설문·확정 구간·클립 정보를 하나의 검증된 입력(`ReportInput`)으로 묶고, 규칙 파일 `report-v2.json`으로 「어떤 장을 넣는가 · 각 장에 어떤 값이 들어가는가 · 못 넣은 이유는 무엇인가」를 결정한다. R03 렌더러는 이 결과만 받아 그린다. 같은 입력이면 같은 결과(해시 동일)다.

## 현재 상태

- `app.scoring.behavior_scores` → `ScoreResult`(영역 6·지표 4·유형 2·기준 각성), `survey_scores` → `SurveyResult`(항목 28 converted, 영역 A·B·C·E 평균, 분리 유형). 리포트에 필요한 값은 대부분 여기 있으나 **유형 이름과 A 영역 통합 평균은 리포트에 쓰지 않는다**(A는 06b가 「가르치는 방식 1~6」「사회화 노력 7~9」로 나눠 보임 — 04 §1 하위요인 표와 일치).
- `input_models.Session.segments: SegmentTimes`(8구간·확정 여부), `preprocess.latest()`가 `clips.json`(오디오 유무·원본 길이)을 준다.
- 옛 `reporting.py`는 55항목 판 「잠정 주제 4개」 구조라 재사용할 것이 없다(R04에서 삭제).

## 계약 (`backend/app/report/input.py`)

모두 `app.domain.base.Contract`(frozen·extra forbid) 기반.

```python
class SurveySubscale(Contract):      # 03장 채우기 막대 한 줄
    key: Literal["teaching","socialising","closeness","consistency","dog_sociability","separation_distress","reunion_settle"]
    title: Text                      # 규칙 파일의 보호자용 이름
    items: tuple[SurveyId, ...]
    mean: float | None               # converted 평균, ROUND_HALF_UP 2자리(설문 규칙과 동일)
    answered_count: int; target_count: int

class ChapterKey = Literal["timeline","scenes","survey","population","face","secure_base","tail","arousal","sync","numbers","scales","entry_exit","suggestions"]

class Omission(Contract):            # 「말할 수 없는 것」과 R06 화면의 제외 이유
    chapter: ChapterKey | None       # None이면 장과 무관한 일반 한계(마이크 없음 등)
    reason_key: Text                 # 규칙 파일의 문구 키
    detail: Text | None              # 보호자용 보충(예: 「낯선 사람 구간」)
    operator_detail: Text | None     # 운영자·교수용: 항목 ID·문턱·사유 원문(예: "BS-05, DOG-06 unreadable: 개가 화각 밖 · 꼬리 5/7 필요, 3 판독"). 리포트 본문에는 넣지 않는다

class Chapter(Contract):
    key: ChapterKey
    number: int                      # 포함된 장만 1부터 순서대로
    data: dict                       # 장별 바인딩 값(아래 표). JSON 직렬화 가능한 값만

class ReportInput(Contract):
    schema_version: "2.0"; rules_version: Text; catalog_version: Text; scoring_rule_version: Text
    case: {case_id, event_id, participant_id, sequence_no, dog_name, guardian_name, dog_profile}
    session_id: Identifier; input_revision: Revision
    recorded_on: Text | None         # 촬영일(구간 기준 영상 등록일 또는 reservation_at 날짜)
    segments: SessionSegments        # 확정된 8구간
    video_count: int; audio_status: Literal["present","absent","unknown"]
    sheet_id: Identifier; sheet_hash: Hash; rater_label: Text | None
    scores: ScoreResult; survey: SurveyResult | None
    subscales: tuple[SurveySubscale, ...]
    narrative: Narrative | None      # R05. 없으면 서술 장 제외
    chapters: tuple[Chapter, ...]
    omissions: tuple[Omission, ...]
    title: Text; subtitle: Text; observed_seconds: int
```

`build(store, db, case_id, session_id, *, sheet_id=None, narrative=None, rules=RULES) -> ReportInput`: `store.case`(삭제 요청 확인) → 매니페스트·세션 → 구간 미확정이면 409 「8구간을 확정한 뒤 리포트를 만들 수 있습니다」 → `sheets.final_sheet`(없으면 409 「사람 채점 시트가 없습니다」) → `behavior_scores` → 설문(`status=unregistered`면 `survey=None`) → `preprocess.latest`(없으면 `audio_status="unknown"`) → `subscales()` → `chapters()`·`omissions()`.

`digest(report_input)`은 `analysis.digest`처럼 정렬 JSON의 SHA-256이다. R04가 실행 분기 키·「이전 입력 기준」 판정에 쓴다.

## 규칙 파일 `resources/rules/report-v2.json`

코드에 박지 않을 것을 전부 여기 둔다. `launcher.REQUIRED`에는 R04에서 추가.

```json
{
  "schema_version": "1.0", "version": "report-v2",
  "source": "06b_리포트_6쌍 6개 HTML·00_읽어주세요, 01 §6, 04 §1·§3",
  "segment_titles": {"entry": "입장", "baseline": "자리 잡기", "alone": "보호자가 나감", "stranger": "낯선 사람",
                     "reunion": "다시 만남", "ignore": "잠시 무시", "walk": "함께 걷기", "exit": "퇴장"},
  "subscales": [
    {"key": "teaching", "title": "가르치는 방식", "items": ["s01","s02","s03","s04","s05","s06"], "group": "owner"},
    {"key": "socialising", "title": "사회화에 들이는 노력", "items": ["s07","s08","s09"], "group": "owner"},
    {"key": "closeness", "title": "정서적 친밀감", "items": ["s15","s16","s17","s18","s19","s20","s21"], "group": "owner"},
    {"key": "consistency", "title": "감정의 일관성", "items": ["s26","s27","s28"], "group": "owner"},
    {"key": "dog_sociability", "title": "사회성 — 낯선 것을 대하는 태도", "items": ["s10","s11","s12","s13","s14"], "group": "dog"},
    {"key": "separation_distress", "title": "떨어졌을 때 불안해하는 정도", "items": ["s22","s23"], "group": "dog"},
    {"key": "reunion_settle", "title": "다시 만났을 때 금방 안정되는가", "items": ["s24"], "group": "dog"}
  ],
  "chapters": {
    "timeline":   {"requires": "segments_confirmed"},
    "scenes":     {"requires": "narrative.scenes"},
    "survey":     {"requires": "survey_registered"},
    "population": {"requires": "population_available", "enabled": false},
    "face":       {"pairs": [
        {"survey": ["s10","s13","s14"], "items": ["DOG-02","BS-03","DOG-01"], "survey_title": "처음 가는 장소에서도 곧 편안해한다"},
        {"survey": ["s11"], "items": ["DOG-09","DOG-11"], "survey_title": "낯선 사람이 다가와도 편안하게 대한다"},
        {"survey": ["s22","s23"], "items": ["DOG-05"], "survey_title": "제가 자리를 비워도 아이는 크게 불안해하지 않는다"},
        {"survey": ["s24"], "items": ["DOG-12","DOG-13"], "survey_title": "내가 돌아오면 반갑게 맞이하고 금방 안정된다"}],
                   "min_pairs": 1},
    "secure_base": {"steps": [["DOG-12"], ["DOG-14","DOG-13"], ["DOG-17"]], "requires_step": 1},
    "tail":       {"items": ["BS-01","BS-03","BS-05","BS-07","DOG-15","BS-08","BS-09"], "min_scored": 5},
    "arousal":    {"points": ["DOG-04","DOG-06","DOG-10","DOG-13","DOG-18"], "required": ["DOG-06","DOG-13"]},
    "sync":       {"count_item": "DOG-21", "indicator": "sync_rate", "validity_item": "OWN-09"},
    "numbers":    {"indicators": ["recovery","stranger_calming","adaptation"], "counts": ["BS-04","BS-06"], "min_entries": 1},
    "scales":     {"domains": [
        {"domain": "ATT", "title": "보호자와의 관계", "ends": ["많이 찾음","편안함","찾지 않음"], "source": "Ainsworth의 「낯선 상황 절차」를 개에게 옮긴 Topál 등(1998)의 관찰 항목을 씁니다."},
        {"domain": "SOC_H", "title": "낯선 사람", "ends": ["경계","담담","과하게 반김"], "source": "같은 절차의 낯선 사람 국면입니다. Horn 등(2013)은 보호자를 낯선 사람으로 바꾸면 개가 기대던 안정감이 사라진다고 보고했습니다."},
        {"domain": "SOC_E", "title": "낯선 환경", "ends": ["조심스러움","편안함","살피지 않음"], "source": "같은 절차의 첫 국면입니다. 처음 오는 방과 낯선 바닥을 어떻게 대하는지를 봅니다."}],
                   "min_scored": 1},
    "entry_exit": {"pairs": [["DOG-01","DOG-23","문을 지날 때"], ["BS-01","BS-09","꼬리"], ["DOG-03","DOG-24","바닥 냄새"]], "min_pairs": 1},
    "suggestions": {"requires": "narrative.suggestions"}
  },
  "omission_texts": {
    "observed_once": "오늘 하루, {observed}입니다. 처음 오는 장소에서 한 번 본 모습이라 평소와 다를 수 있습니다.",
    "event_venue": "사람이 많고 다른 개가 있는 행사장에서 찍었습니다. 조용한 곳이었다면 달랐을 수 있습니다.",
    "audio_absent": "무선 마이크 소리가 담기지 않아 보호자님의 목소리와 관련된 항목은 보지 못했습니다.",
    "segment_missing": "「{segment}」 구간이 이날 촬영에 없어 그 구간의 항목은 보지 못했습니다.",
    "unreadable": "{items}은(는) 영상에서 판독하지 못했습니다 — {reasons}",
    "walk_invalid": "걷기 조건이 지켜지지 않아 함께 걷기 항목은 넣지 않았습니다.",
    "ignore_invalid": "무시 구간 조건이 지켜지지 않아 그 구간의 항목은 넣지 않았습니다.",
    "not_diagnosis": "진단이 아닙니다. 걱정되는 점이 있으시면 수의사나 행동 전문가와 상의하세요."
  },
  "title_priority": ["dog_name", "guardian_name", "sequence_no"],
  "forbidden": { "...": "R03 guard.py가 읽는다. 목록은 R03 문서" }
}
```

`enabled: false`인 장은 규칙만 존재하고 만들지 않는다(R07이 켠다). 문턱값(`min_scored`·`min_pairs`)은 06b 6쌍을 재현하도록 이 PR에서 맞추고, 바뀌면 이 파일만 고친다.

## 장별 바인딩 값(`Chapter.data`)

| key | data |
| --- | --- |
| `timeline` | `rows: [{segment, title, seconds, share}]` (길이 0 제외, `share`=구간/총합), `note`: 계획 길이와 다른 구간이 있으면 규칙 문구 |
| `survey` | `owner: [subscale…]`, `dog: [subscale…]` (answered 0 제외) |
| `face` | `pairs: [{survey_title, survey_mean, item_labels: [{item_id, label_text}], contradiction: bool}]` — `contradiction`은 설문 ≥4 & 항목 점수가 3에서 2 이상 떨어짐(또는 반대) 같은 결정적 판별. AI 문장은 `narrative.face`에서 덧씀 |
| `secure_base` | `steps: [{number, seen: bool, text}]` — `text`는 채점 라벨 원문(`CatalogItem.labels[score].text`), 못 본 단계는 `unreadable`/`not_applicable` 사유 |
| `tail` | `points: [{segment_title, score \| null}]`, `never_tucked: bool`(scored 중 1점 없음) |
| `arousal` | `points: [{title, distance \| null}]` (`distance = 3 − \|score − 3\|` 형태로 「편안한 자리」가 위) |
| `sync` | `phase_count \| null`, `rate_percent \| null`, `invalid: bool`, `phase_detail: null`(원장 v2가 있으면 국면별 채움 — 없으면 6칸을 순서 없이 N개 채움) |
| `numbers` | `indicators: [{key, title, value, sign_text}]`, `counts: [{item_id, title, value}]` |
| `scales` | `rows: [{title, position_percent, ends, source}]` — `position = (mean − 1) / 4 × 100` |
| `entry_exit` | `rows: [{title, entry_text, exit_text, same: bool}]` |
| `scenes`·`suggestions` | R05 `Narrative`에서 그대로 |

## 시험 (`backend/tests/test_report_input.py`, `tests/fixtures/report/`)

- **fixture 변환기** `tests/report_fixtures.py`(R01에서 시작, 여기서 확장): `test_scoring_golden.read_pairs()`의 6쌍 시트(R01 `POST /sheets`로 저장) + 05b `구간_시각`(1번)·05 `관찰노트` 구간 표(2~6번; 새 절차에 없는 구간은 길이 0) + 06b 03장 하위영역 평균을 만족하는 합성 설문 응답. 실제 보호자 이름은 쓰지 않고 「1번 보호자」처럼 익명 라벨.
- **장 목록 골든:** 6쌍 각각의 `chapters` 키 집합이 06b `00_읽어주세요` 표의 **○/— 표시**와 장별로 일치한다(표 마지막 행 「장 수」 숫자가 아니라 ○ 표시를 기준으로 한다 — 그 표에는 나중에 추가된 「다른 분들과 나란히 놓으면」이 없고 장 수 셈이 ○ 개수와 어긋나는 열이 있다). 예외를 명시한다 — `scenes`·`suggestions`(narrative 없음), `population`(비활성), 09장은 「가까이 있던 비율」 없이 `sync`로만 판정(02·03·04·06번은 동조 국면 수가 없어 06b에서도 「—」였으나 장은 있었음 → `sync`는 `count_item` 미판독이어도 걷기 구간이 있으면 장을 두고 사유를 적는다는 규칙을 반영).
- 결정성: 같은 입력 두 번 → `digest` 동일. 시트 한 항목 변경 → 다름.
- 유형 이름·분리 유형 라벨이 `ReportInput` JSON 어디에도 없다(`TYPE_LABELS`·`SeparationLabel` 값 grep).
- 구간 미확정 409, 시트 없음 409, 설문 없음이면 `survey=None`·`survey` 장 없음, 삭제 요청 참가자 403.
- 무효: OWN-09=3 합성 → `sync.invalid`·`walk_invalid` omission, SYN 눈금 없음. OWN-08=3 → `ignore_invalid`.

## 완료 조건

1. 6쌍 fixture의 장 목록이 06b 표와 (명시한 예외를 빼고) 일치한다.
2. `ReportInput`에 총점·유형 이름·Ainsworth 용어가 없다.
3. 문턱·문구·이름은 모두 `report-v2.json`에서 읽으며, 코드에는 상수가 없다.
4. 백엔드 전체 시험·`--check`·`git diff --check` 통과.

## 미결

- Q-R2 「가까이 있던 비율」: 규칙 파일에 `proximity_percent` 자리만 두고 항상 null. P2 원장 v2가 값을 주면 R03이 그린다.
- Q-R5 눈금 영역 범위: 기본 셋. 규칙 파일 `scales.domains`에 추가하면 된다.
- 재회 「③ 다시 자기 일로 돌아간다」의 판정 항목을 DOG-17(무시 접촉 개시)로 둔 것은 02 §2 「무시: 위안을 얻고 자기 활동으로 돌아가는가」에 근거한다. 고객 확인 후보로 R06 화면의 장 설명에 근거를 표시한다.

권장 PR 제목: `feat: 리포트 입력 묶음과 report-v2 장 선택 규칙`
