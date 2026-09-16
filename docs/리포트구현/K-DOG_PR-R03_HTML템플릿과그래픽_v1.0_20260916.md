# PR-R03 HTML 템플릿과 그래픽(데이터 바인딩)·원칙 검사기

버전: v1.0 · 2026-09-16 · 상태: 구현 계획 · 의존: [R02](K-DOG_PR-R02_리포트입력과장선택_v1.0_20260916.md) · 다음: [R04](K-DOG_PR-R04_생성실행과저장_v1.0_20260916.md)

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md) §1·§3. 근거: 06b HTML 6개(구조·CSS·문구), 01 §6 「그래도 수치는 보여줍니다 — 설문은 채우기 막대, 관찰은 가운데 기준 점, 동조는 백분율」, 변경검토 §5 「리포트 원칙 위반 차단 … 저장 전 정규식·금칙어 검사」.

## 목적

`ReportInput`을 받아 06b와 같은 모양의 **단일 HTML 문서**를 결정적으로 만든다. 06b의 CSS·구조를 그대로 옮기고(디자인을 새로 하지 않는다), 장마다 데이터 바인딩 함수를 둔다. 같은 입력이면 바이트까지 같은 HTML을 낸다. 함께 원칙 검사기(`guard.py`)를 만들어 렌더 결과와 AI 서술(R05)을 같은 규칙으로 검사한다.

## 현재 상태

- 06b 1번 HTML은 45 KB, `<style>` 13 KB + 본문. CSS 클래스: `mast eyebrow name sub meta`, `tl tl-row tl-bar tl-dur tl-foot`, `scene when good`, `svy srow bar foot`, `dist …`, `face s v lab`, `base ring step no off`, `chart cap`, `figs fig-lab fig-num fig-sub fig-how pbar pbar-row pbar-seg on`, `mt mt-l mt-v zero`, `scale scale-top track rail mid dot ends src`, `io`, `todo`, `fine`, `note`, `idnote`. 6개 파일이 같은 CSS를 쓰므로 한 스타일시트로 뺀다.
- 06b는 `<link href="https://fonts.googleapis.com/…Gowun+Batang…IBM+Plex+Sans+KR">`를 쓴다 — 외부 접속. 대체 필요(개요 §1 8번).
- `api.py:75` CSP 미들웨어가 모든 응답에 `style-src 'self'`를 붙인다. 리포트 HTML의 인라인 `<style>`·`style="left:35.8%"`는 이 헤더 아래에서 막힌다 → 리포트 라우트는 자체 CSP를 단다(R04). 렌더러는 **인라인 style 속성 대신 CSS 변수를 쓰는 클래스**로 바꿔 두면 `'unsafe-inline'` 없이도 동작한다: 예 `<div class="dot" style="left:35.8%">` → `<div class="dot" style="--x:35.8%">`는 여전히 인라인이므로 안 되고, 위치는 SVG 좌표로 그리거나 `<div class="dot" data-x="…">`+CSS 불가. 결론: **위치가 필요한 요소는 모두 SVG로 그린다**(눈금 점·분포 점·막대 길이). 인라인 `style` 속성 0개를 시험으로 강제한다.
- reportlab PDF(`exports.pdf`)는 쓰지 않는다. PDF는 인쇄로 만든다(R08).
- 새 라이브러리(Jinja2 등)는 넣지 않는다. 표준 라이브러리 `html.escape`와 함수 조합으로 충분하다(장 13개, 각 20~60줄). 도입하려면 AGENTS.md 「버전 검증」 절차를 따라 PR 본문에 기록한다.

## 변경 범위

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `resources/report/report-v2.css` | 신설 | 06b `<style>` 블록을 그대로 옮기고 (1) 폰트 스택을 `var(--serif)`=`'Nanum Myeongjo','Gowun Batang',serif`, `var(--sans)`=`'NanumGothic','Malgun Gothic','Apple SD Gothic Neo',sans-serif`로, (2) `@font-face`로 `/fonts/NanumGothic-Regular.ttf`(앱 안) 선언, (3) `@media print`에 A4 여백·`break-inside: avoid`(`.scene .scale .base .chart .io`)·`.wrap{max-width:none}`·다크 모드 무효화 추가. 해시를 `report-v2.json`에 기록하지는 않고, 렌더 결과에 CSS 내용을 **인라인 `<style>`로 포함**한다(단독 파일이어야 하므로) |
| `backend/app/report/render.py` | 신설 | `render(report_input: ReportInput, *, css: str, standalone: bool) -> str`. 문서 뼈대(`<!doctype html><html lang="ko">`, `<title>`, `<meta charset>`, `<style>`), `mast`, 장 순서대로 `section` 호출, `fine`. `standalone=True`면 `@font-face` 줄을 빼고 시스템 글꼴만(내려받기용), `False`면 앱 제공 폰트 사용. 스크립트 태그 없음 |
| `backend/app/report/svg.py` | 신설 | 순수 함수: `timeline_bar(share)`, `fill_bar(mean)`(설문 5점 채우기), `scale_dot(position_percent)`(레일·가운데 선·점), `secure_ring(steps)`(06b `viewBox 0 0 400 150` 고리 3개, 못 본 단계 `stroke-dasharray`), `tail_line(points)`(`viewBox 0 0 640 190`, null은 끊김), `arousal_line(points)`(`0 0 640 200`, 가운데 선), `sync_cells(count, detail)`(6칸), `distribution(...)`(R07용 자리만). 좌표는 소수 1자리로 고정 반올림해 결정성 유지 |
| `backend/app/report/guard.py` | 신설 | `check(text_blocks: list[tuple[str, str]], rules) -> list[Violation]`. 블록마다 `kind`(`narrative` / `survey_numbers_allowed` / `fixed`)를 받아 규칙을 다르게 적용. 위반 종류: `forbidden_term`(Ainsworth·유형 이름·판정어·비교어·공격성), `score_number`(관찰 서술 안의 `[1-5](\.\d+)?점` 또는 「평균 2.43」 꼴), `ranking`(등수·백분위·상위·하위·%ile), `total`(총점·합계 점수), `diagnosis`(「진단」을 「진단이 아닙니다」 밖에서). 결과는 위치·문장·규칙 키. 06b 6개 HTML 본문 텍스트를 넣으면 위반 0이어야 한다(허용 예시 고정) |
| `resources/rules/report-v2.json` | 변경 | `forbidden` 절 채움(아래) |
| `backend/tests/test_report_render.py` · `test_report_guard.py` | 신설 | 아래 |

## 장별 렌더 규칙 (06b와의 대응)

| 장 | 06b 구조 | 렌더 규칙 |
| --- | --- | --- |
| 표지 | `mast > eyebrow / name / sub / meta` + `idnote` | `name`=`ReportInput.title`, `meta` = 「{촬영일}」「관찰 {m}분 {ss}초」「영상 {n}개」「설문 28문항」(설문 없으면 「설문 미등록」). `idnote`는 반려견 이름이 없을 때만 「설문지에 반려견 이름이 적혀 있지 않아 …」 |
| 01 흐름 | `tl > tl-row(.nm, .tl-bar>.bar, .tl-dur)`, `tl-foot` | 막대 길이는 SVG `rect width=share`. `tl-foot`은 규칙 문구(계획 길이와 2배 이상 다른 구간이 있을 때만) |
| 02 장면 | `scene(.good) > h3 / .when / p…` | R05 `narrative.scenes[]`. `when` = 「{m}분 {ss}초 ~ {m}분 {ss}초 · {n}초」는 구간 시각에서 프로그램이 계산해 AI 문장을 덮어쓴다(시각은 AI가 만들지 않는다) |
| 03 설문 | `svy > h4 / srow(.nm .bar .vv) / .foot` | `vv`는 소수 1자리(06b 「4.2」). 막대는 SVG `fill_bar`. 「이런 문항은 대부분의 보호자가 높게 답하십니다 …」 고정 `foot` |
| 05 만나는 곳 | `face > .s(설문에서) / .v(영상에서)`, `note` | 설문 문장 = `survey_title`에 「에 가깝게 답하셨습니다」(≥4) / 「쪽으로 답하셨습니다」(3) / 「에 낮은 점수를 주셨습니다」(≤2) 결정적 조사; 영상 문장 = 라벨 원문에 「~였습니다」 어미 규칙, R05가 있으면 그 문장 |
| 06 안전기지 | `base > svg.ring + step(.off) > .no / b / p` | `seen=false`인 단계는 `off` + 점선. 마지막 문장 「오늘은 세 단계 중 {k}단계까지 볼 수 있었습니다」 |
| 07 꼬리 | `chart > svg + cap` | y축 라벨 없음(숫자 노출 금지). 06b처럼 「말아 넣은 적은 한 번도 없었습니다」는 `never_tucked`일 때만 |
| 08 상태 변화 | `chart > svg + cap` | 「가운데 선이 편안한 자리 …」 고정 lede |
| 09 동조 | `figs > fig-lab/fig-num/fig-sub/fig-how` + `pbar` | `fig-num`은 `{rate}%` 또는 「—」(사유를 `fig-sub`에). `proximity_percent`가 null이면 그 `fig` 자체를 뺀다. `pbar-row` 라벨(「걷기/멈춤」)은 `phase_detail`이 있을 때만; 없으면 라벨 없는 한 줄 6칸 |
| 10 숫자 | `mt > mt-l(b + span) / mt-v(.zero)` | 지표는 `+1`·`−2`(부호 항상), 횟수는 `0회`(0이면 `zero`). 「양수면 편안한 쪽으로 왔다는 뜻입니다」 lede. 「몸 털기는 …」 고정 설명은 횟수가 있을 때만 |
| 11 눈금 | `scale > scale-top / track(rail mid dot) / ends / src` | `dot`은 SVG `scale_dot`. `scale-val`(06b는 비어 있음)은 쓰지 않는다 — 숫자 없음 |
| 12 입퇴장 | `table.io` 3열 | `same=true`면 둘째 칸 「같음」(06b 꼬리 행). 마지막 문장은 전부 같음/일부 다름/전부 다름 세 문구 중 결정적 선택 |
| 13 해보실 만한 것 | `h4 + p` 반복, `todo` | R05 `narrative.suggestions[]`. lede 「해야 하는 일이 아닙니다 …」 고정 |
| 말할 수 없는 것 | `fine > h4 + p…` | `omissions` 순서: `observed_once` → `event_venue` → `audio_absent` → 구간 부재 → 무효 → 미판독 묶음 → `not_diagnosis`(항상 마지막) |

모든 자유 텍스트는 `html.escape`. 라벨 원문에 있는 `·`·`※` 뒤 설명(「※바닥을 밟는 동안」)은 리포트에 넣지 않는다(채점자용 지시). 라벨 텍스트 정리 함수 `label_sentence(text)`를 두고 시험으로 고정한다.

## 금칙어·검사 규칙(`report-v2.json.forbidden`)

```json
"forbidden": {
  "terms": ["Secure", "Avoidant", "Ambivalent", "Disorganized", "Disorganised", "안정형", "회피형", "양가형", "혼란형", "불안정 애착", "불안 애착",
            "안정 애착", "거리 둠", "일관되지 않음", "편안·우호", "우호·들뜸", "담담·거리둠", "경계·긴장", "회피 쪽", "무덤덤",
            "총점", "등수", "순위", "백분위", "상위 ", "하위 ", "평균보다", "다른 개보다", "다른 아이보다",
            "공격", "물림", "회복력이 좋", "회복력이 나쁘", "문제행동", "문제견"],
  "type_labels_note": "TYPE_LABELS·SeparationLabel의 값은 계약에서 직접 읽어 자동 포함한다(중복 관리 방지). 단 「안정」·「불안」 두 낱말은 일반어라 단독으로는 막지 않고 「안정형」「불안 애착」 꼴만 막는다.",
  "score_pattern": "(?<![0-9])[1-5](\\.[0-9]+)?\\s*점(?!에 가까울수록)",
  "score_pattern_exempt_kinds": ["survey_numbers_allowed", "fixed"],
  "judgement_pattern": "(좋은 개|나쁜 개|잘못 키우|못 키우|훈련이 안 된|버릇이 나쁜)",
  "diagnosis_pattern": "진단(?!이 아닙니다)",
  "allowed_examples": "docs/최종 고객 문서/06b_리포트_6쌍/*.html 본문은 위반 0이어야 한다 (시험이 고정)"
}
```

「거리 둠」「일관되지 않음」 같은 유형 이름이 일반 문장에 우연히 쓰일 수 있으나(「거리를 둠」과 다름), 06b 6개 본문이 통과하는지로 목록의 과도함을 검증한다. 06b에 있는 「5점에 가까울수록」·「1점」(축 라벨)·「4.2」(설문 막대)는 예외 규칙으로 허용된다.

## 시험

`test_report_render.py`
- 6쌍 fixture(R02) → HTML 생성. 1번의 `h2` 제목 순서·번호가 06b 1번과 같다(단, `scenes`·`suggestions`·`population` 제외 후 번호 재부여를 고려해 **제목 집합**과 **상대 순서**를 비교).
- 인라인 `style=` 속성 0개, `<script` 0개, `http://`·`https://` 0개(`standalone=True`), `@font-face` 존재 여부가 `standalone`에 따라 갈림.
- 결정성: 두 번 렌더 → 바이트 동일. 입력의 한 점수 변경 → 해당 SVG만 바뀜.
- 라벨 정리: 「발성  ※입장 구간」 → 「발성」, 「낯선 바닥 — 꼬리  ※바닥을 밟는 동안」 → 「낯선 바닥 — 꼬리」.
- 숫자 노출: 렌더 HTML의 관찰 장(06~12) 텍스트에 `[1-5]점`·소수 점수 없음. 03장에는 소수 1자리 있음. 09장에는 `%`만.
- 인쇄 CSS: `@page { size: A4 }`·`break-inside` 규칙 존재(문자열 검사). 실제 페이지 수는 R08에서 브라우저로 확인.

`test_report_guard.py`
- 06b 6개 HTML 본문(태그 제거) → 위반 0.
- 합성 문장: 「불안정 애착입니다」「Secure 유형」「회복력이 좋습니다」「총점 3.2」「상위 20%」「평균 2.43점」 → 각각 해당 위반 1개. 「5점에 가까울수록 그렇다」「1점 / 5점」(축 라벨, kind=fixed) → 0.
- `TYPE_LABELS` 값을 바꾼 합성 규칙으로 자동 포함 확인.

## 완료 조건

1. 6쌍 fixture가 06b와 같은 장 구조의 HTML로 렌더되고, 1번은 06b 1번과 제목 집합·순서가 같다.
2. 인라인 style·스크립트·외부 URL이 없고, 렌더가 결정적이다.
3. 검사기가 06b 본문을 통과시키고 합성 위반을 잡는다.
4. 백엔드 전체 시험·`git diff --check` 통과. 새 의존성 없음.

## 미결

- 서체: 06b의 Gowun Batang(명조 제목)을 동봉하려면 라이선스(OFL) 확인 후 `resources/fonts/`에 추가하고 README·해시를 갱신한다. 이 PR은 NanumGothic만 쓰고, 명조 동봉은 R08에서 결정.
- 다크 모드 CSS는 06b에서 그대로 옮기되 인쇄에서는 무효화한다. 화면 미리보기(R06)는 `prefers-color-scheme`에 따른다.

권장 PR 제목: `feat: 06b 기반 리포트 HTML 렌더러·SVG 그래픽·원칙 검사기`
