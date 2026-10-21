"""Photo-free report presentation; content and scales remain pinned upstream."""
import base64
import json
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .domain.comparisons_v4 import CohortPublicV4
from .report_render_v4 import (CM_ASSETS, CM_PRESENTATION, NEW_ASSETS, STATUS, comparison_legend, comparison_panels, comparison_rows,
    comparison_sources, external_rows, number, survey_rows, timeline_rows, validate)
from .storage import REPO_ROOT


def files(profile=None):
    return CM_ASSETS if profile is not None and profile.presentation_version == CM_PRESENTATION else NEW_ASSETS


def design(profile=None):
    return json.loads((REPO_ROOT / files(profile)[0]).read_text(encoding="utf-8"))


def panel_html(panel, e):
    marks = "".join(f'<div class="lane {lane["kind"]}"><span class="lane-label">{e(lane["label"])}</span>'
                    f'<div class="axis"><i class="mark {lane["kind"]}" style="left:{lane["position"]*100:.3f}%"></i></div></div>' for lane in panel["lanes"])
    ticks = (f'<div class="ticks"><span></span><div>{"".join(f'<span style="left:{index*100/(len(panel["ticks"])-1):.3f}%">{e(value)}</span>' for index, value in enumerate(panel["ticks"]))}</div></div>' if panel["lanes"] else "")
    body = (marks + ticks) if panel["lanes"] else f'<p class="metric-notice">{e(panel["notice"])}</p>'
    return (f'<article class="metric" data-metric="{e(panel["metric_id"])}"><h3>{e(panel["title"])}</h3><p class="scale">{e(panel["scale"])}</p>{body}'
            + "".join(f"<p>{e(text)}</p>" for text in panel["sentences"])
            + "".join(f'<p class="basis">{e(text)}</p>' for text in (*panel["notes"], *([panel["detail"]] if panel["detail"] else ()))) + "</article>")


def html(profile, header, images=(), *, cohort=None):
    profile, header, _ = validate(profile, header, images)
    cohort = CohortPublicV4.model_validate(cohort) if cohort is not None else None
    document = design(profile)
    e = lambda value: escape(str(value), quote=True)
    def paragraphs(items):
        return "".join(f"<p>{e(item.text)}</p>" for item in items)
    def note(value):
        return f'<p class="basis">{e(value)}</p>' if value else ""
    bodies = []
    def section(index, body):
        bodies.append(f'<section><div class="eyebrow">{index+1:02}</div><h2>{e(document["sections"][index])}</h2>{body}</section>')
    section(0, '<div class="cards">'+"".join(f'<article class="card"><div class="small">{e(card.title)}</div><div class="value">{e(card.label or STATUS[card.status])}</div>{paragraphs(card.claims)}</article>' for card in profile.cards)+'</div>'+note(document["legend"]))
    charts = []
    for row in survey_rows(profile, cohort):
        width = (row["value"]-row["minimum"])/(row["maximum"]-row["minimum"])*100 if row["value"] is not None else None
        bar = f'<div class="track"><div class="fill" style="width:{width:.3f}%"></div></div>' if width is not None else ""
        charts.append(f'<div class="survey-row"><div class="bar-label"><span>{e(row["title"])}</span><span class="survey">설문 {e(number(row["value"]))}</span></div>{bar}{note(f"원척도 {row['minimum']}–{row['maximum']} · {row['detail']}")}</div>')
    external = "".join('<article class="box"><h3>'+e(row[0])+'</h3>'+"".join(note(value) for value in row[1:])+'</article>' for row in external_rows(profile))
    if profile.survey_comparison:
        ready = any(row.external_status == "ready" for row in profile.survey_comparison.rows)
        legend = "".join(f'<span><i class="{kind}"></i>{e(text)}</span>' for kind, text in ((("us", document["labels"]["us"]),) if ready else ()) +
            (("cumulative", profile.survey_comparison.label), ("individual", document["labels"]["individual"])))
        panels = comparison_panels(profile, document, cohort)
        section(1, f'<p>{e(document["comparison_intro"])}</p><div class="legend-marks">{legend}</div>' + note(document["fear_note"]) +
            (note(f'자체 비교 집단: {cohort.title} · 선택 {cohort.selection_count}개체') if cohort else "") + "".join(panel_html(panel, e) for panel in panels) +
            note(f'{profile.survey_comparison.label} 집계 기준일 {profile.survey_comparison.as_of}'))
    else:
        section(1, '<p>평소의 경험을 원래 눈금으로 읽습니다. 값의 크기만으로 좋고 나쁨을 정하지 않습니다.</p>'+ (note(f'자체 비교 집단: {cohort.title} · 선택 {cohort.selection_count}개체') if cohort else "")+"".join(charts)+external)
    rows = "".join(f'<tr><td>{e(title)}</td><td class="survey">{e(survey)}</td><td class="video">{e(video)}'+"".join(f'<p>{e(item)}</p>' for item in details)+'</td></tr>' for title, survey, video, details in comparison_rows(profile))
    section(2, note(document["scale_notice"])+note(" / ".join(comparison_legend(profile)))+'<table class="comparison"><thead><tr><th>평소의 질문</th><th>설문 값</th><th>이번 영상 관찰</th></tr></thead><tbody>'+rows+'</tbody></table>')
    def intervals(kind):
        rows = timeline_rows(profile, kind)
        return '<table><thead><tr><th>구간</th><th>공통시각</th><th>관찰 상태</th></tr></thead><tbody>'+"".join('<tr>'+"".join(f'<td>{e(item)}</td>' for item in row)+'</tr>' for row in rows)+'</tbody></table>' if rows else ""
    section(3, "".join(f'<article class="box"><h3>{e(item.title)}</h3>{paragraphs(item.claims) or note(STATUS[item.status])}{intervals("walk_phase") if item.key == "walking" else ""}</article>' for item in profile.details)+ '<h3>기록된 관찰 구간</h3>'+intervals("segment"))
    section(4, '<div class="callout">'+paragraphs(profile.summary)+'</div>'+"".join(f'<article class="tip"><span>{index+1:02}</span><div>{e(item.text)}</div></article>' for index, item in enumerate(profile.actions))+note(profile.actions_notice))
    section(5, '<p>확정된 영상 원자료, 보호자 설문과 완료된 해석을 바탕으로 작성했습니다. 관찰되지 않은 행동을 하지 않는 행동으로 단정하지 않습니다.</p>'+note(document["scale_notice"])+
        ("".join(note(text) for text in comparison_sources(profile)) if profile.survey_comparison else note(document["external_notice"]))+note(f'생성 {header.generated_at} · 기본 결과 판본 {profile.source.basic.revision} · 원자료 판본 {profile.source.sheet.revision}')+ (note(cohort.interpretation_note)+note(cohort.selection_note)+note(f'자체 비교 snapshot {cohort.reference.snapshot_id} · 판본 {cohort.reference.revision}') if cohort else ""))
    title = f'{header.dog_name}와 함께 읽는 관찰'
    brand = '<div class="brand"><span>K-DOG / OBSERVATION</span><span>'+('검토용 미리보기' if header.preview else '관찰 리포트')+'</span></div>'
    hero = f'<header class="hero">{brand}<h1>{e(title)}</h1><p>{e(header.guardian_name)} · {e(header.event_name)} · {e(header.observed_date)}</p><p class="intro">함께 지낸 경험과 이번 관찰을 나란히 살펴보고, 일상에서 도울 방향을 찾아봅니다.</p></header>'
    names = files(profile)
    css = (REPO_ROOT / names[2]).read_text(encoding="utf-8")
    for path, family in zip(names[3:], ("KDog", "KDogSymbols")):
        css += f"\n@font-face{{font-family:{family};src:url(data:font/ttf;base64,{base64.b64encode((REPO_ROOT/path).read_bytes()).decode()}) format('truetype');}}"
    template = (REPO_ROOT / names[1]).read_text(encoding="utf-8")
    return template.replace('__TITLE__', e(title)).replace('__STYLE__', css).replace('__SECTIONS__', hero+"".join(bodies)+f'<footer>K-DOG · {e(header.participant_id)} · {e(header.observed_date)}</footer>').encode("utf-8")


class MetricPanel(Flowable):
    """Point markers on the original scale, one lane per marker; equal displayed values share the same x."""
    LABEL = 150

    def __init__(self, panel, width, color):
        super().__init__()
        self.panel, self.width, self.color = panel, width, color
        self.height = 18 * len(panel["lanes"]) + 14

    def draw(self):
        canvas, left, right = self.canv, self.LABEL, self.width - 8
        span = right - left
        for index, lane in enumerate(reversed(self.panel["lanes"])):
            y = 14 + 18 * index
            canvas.setFillColor(self.color(lane["kind"])); canvas.setFont("KDogRP04", 7.5)
            canvas.drawString(0, y + 2, lane["label"])
            canvas.setStrokeColor(self.color("line")); canvas.setLineWidth(1.2); canvas.line(left, y + 4, right, y + 4)
            x = left + span * lane["position"]
            canvas.setFillColor(self.color(lane["kind"]))
            if lane["kind"] == "us":
                path = canvas.beginPath(); path.moveTo(x, y + 10); path.lineTo(x + 5, y + 5); path.lineTo(x, y); path.lineTo(x - 5, y + 5); path.close()
                canvas.drawPath(path, fill=1, stroke=0)
            elif lane["kind"] == "cumulative":
                canvas.rect(x - 4.5, y + 0.5, 9, 9, fill=1, stroke=0)
            else:
                canvas.circle(x, y + 5, 4.8, fill=1, stroke=0)
        canvas.setFillColor(self.color("muted")); canvas.setFont("KDogRP04", 7)
        ticks = self.panel["ticks"]
        for index, value in enumerate(ticks):
            canvas.drawCentredString(left + span * index / (len(ticks) - 1), 2, value)


class SurveyBar(Flowable):
    def __init__(self, value, minimum, maximum, width):
        super().__init__()
        self.width, self.height = width, 14
        self.fraction = (value-minimum)/(maximum-minimum)

    def draw(self):
        self.canv.setFillColor(colors.HexColor("#ECE7F2"))
        self.canv.roundRect(0, 4, self.width, 6, 3, fill=1, stroke=0)
        if self.fraction:
            self.canv.setFillColor(colors.HexColor("#846FAD"))
            self.canv.roundRect(0, 4, self.width*self.fraction, 6, 3, fill=1, stroke=0)


def pdf(profile, header, images=(), *, cohort=None):
    profile, header, _ = validate(profile, header, images)
    cohort = CohortPublicV4.model_validate(cohort) if cohort is not None else None
    document = design(profile)
    for name, path in zip(("KDogRP04", "KDogRP04Symbols"), files(profile)[3:]):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(REPO_ROOT/path)))
    color = lambda key: colors.HexColor(document["colors"][key])
    body = ParagraphStyle("rp04Body", fontName="KDogRP04", fontSize=9.5, leading=15, textColor=color("ink"), wordWrap="CJK", spaceAfter=8)
    small = ParagraphStyle("rp04Small", parent=body, fontSize=8, leading=12, textColor=color("muted"), spaceAfter=5)
    cell = ParagraphStyle("rp04Cell", parent=body, fontSize=8, leading=12, spaceAfter=1)
    survey_style = ParagraphStyle("rp04Survey", parent=cell, textColor=color("survey"))
    video_style = ParagraphStyle("rp04Video", parent=cell, textColor=color("video"))
    heading = ParagraphStyle("rp04Heading", parent=body, fontSize=17, leading=24, spaceBefore=20, spaceAfter=12, keepWithNext=True)
    subheading = ParagraphStyle("rp04Subheading", parent=heading, fontSize=12, leading=18, spaceBefore=12, spaceAfter=8)
    title = ParagraphStyle("rp04Title", parent=heading, fontSize=27, leading=37, spaceBefore=12, spaceAfter=18)
    def p(value, style=body):
        text = escape(str(value)).replace("\n", "<br/>")
        for symbol in "②④⑥⑧⑩":
            text = text.replace(symbol, f'<font name="KDogRP04Symbols">{symbol}</font>')
        return Paragraph(text, style)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(595.28, 841.89), leftMargin=44, rightMargin=44.28, topMargin=38, bottomMargin=44, title="K-DOG 관찰 리포트", author="K-DOG", invariant=1)
    story = [p("K-DOG / OBSERVATION" + (" · 검토용 미리보기" if header.preview else ""), small), p(f"{header.dog_name}와 함께 읽는 관찰", title), p(f"{header.guardian_name} · {header.event_name} · {header.observed_date}", small), p("함께 지낸 경험과 이번 관찰을 나란히 살펴보고, 일상에서 도울 방향을 찾아봅니다.")]
    def section(index):
        story.append(p(f"{index+1:02}  {document['sections'][index]}", heading))
    def claims(items):
        story.extend(p(item.text) for item in items)
    def table(data, widths):
        result = LongTable(data, colWidths=widths, repeatRows=1, splitInRow=1)
        result.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), color("background")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LINEBELOW", (0,0), (-1,-1), .3, color("line")), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
        story.append(result)
    section(0)
    cards = [[p(item.title, small), p(item.label or STATUS[item.status], subheading), *[p(claim.text) for claim in item.claims]] for item in profile.cards]
    grid = Table([[cards[0], cards[1]], [cards[2], cards[3]]], colWidths=[253.5,253.5], splitInRow=1)
    grid.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), color("background")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("INNERGRID", (0,0), (-1,-1), 2, colors.white), ("LEFTPADDING", (0,0), (-1,-1), 14), ("RIGHTPADDING", (0,0), (-1,-1), 14), ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 10)]))
    story.extend([grid, Spacer(1,10), p(document["legend"], small)])
    section(1)
    if profile.survey_comparison:
        story.append(p(document["comparison_intro"]))
        ready = any(row.external_status == "ready" for row in profile.survey_comparison.rows)
        story.append(p((f"◆ {document['labels']['us']} (회색) · " if ready else "") + f"■ {profile.survey_comparison.label} (파란색) · ● {document['labels']['individual']} (주황색)", small))
        story.append(p(document["fear_note"], small))
        if cohort:
            story.append(p(f"자체 비교 집단: {cohort.title} · 선택 {cohort.selection_count}개체", small))
        for panel in comparison_panels(profile, document, cohort):
            block = [p(panel["title"], subheading), p(panel["scale"], small)]
            block.append(MetricPanel(panel, 507, color) if panel["lanes"] else p(panel["notice"]))
            block.extend(p(text) for text in panel["sentences"])
            block.extend(p(text, small) for text in (*panel["notes"], *([panel["detail"]] if panel["detail"] else ())))
            story.append(KeepTogether(block))
        story.append(p(f"{profile.survey_comparison.label} 집계 기준일 {profile.survey_comparison.as_of}", small))
    else:
        story.append(p("평소의 경험을 원래 눈금으로 읽습니다. 값의 크기만으로 좋고 나쁨을 정하지 않습니다."))
        if cohort:
            story.append(p(f"자체 비교 집단: {cohort.title} · 선택 {cohort.selection_count}개체", small))
        for row in survey_rows(profile, cohort):
            story.append(p(f"{row['title']} · 설문 {number(row['value'])}", subheading))
            if row["value"] is not None:
                story.append(SurveyBar(row["value"], row["minimum"], row["maximum"], 490))
            story.append(p(f"원척도 {row['minimum']}–{row['maximum']} · {row['detail']}", small))
        for row in external_rows(profile):
            story.append(p(row[0], subheading))
            story.extend(p(value, small) for value in row[1:])
    section(2)
    story.append(p(document["scale_notice"], small))
    story.extend(p(value, small) for value in comparison_legend(profile))
    data = [[p("평소의 질문", cell),p("설문 값", cell),p("이번 영상 관찰", cell)]]
    data.extend([p(text,cell),p(survey,survey_style),p("\n".join([video,*details]),video_style)] for text,survey,video,details in comparison_rows(profile))
    table(data, [225,78,204])
    section(3)
    def intervals(kind):
        rows = timeline_rows(profile, kind)
        if rows:
            table([[p(value,cell) for value in ("구간","공통시각","관찰 상태")], *[[p(value,cell) for value in row] for row in rows]], [90,160,257])
    for item in profile.details:
        story.append(p(item.title, subheading))
        claims(item.claims)
        if not item.claims:
            story.append(p(STATUS[item.status],small))
        if item.key == "walking":
            intervals("walk_phase")
    story.append(p("기록된 관찰 구간", subheading)); intervals("segment")
    section(4); claims(profile.summary)
    for index, item in enumerate(profile.actions):
        story.extend([p(f"{index+1:02} · 오늘부터 해보기",subheading),p(item.text)])
    if profile.actions_notice:
        story.append(p(profile.actions_notice))
    story.append(KeepTogether([p(f"06  {document['sections'][5]}",heading),
        p("확정된 영상 원자료, 보호자 설문과 완료된 해석을 바탕으로 작성했습니다. 관찰되지 않은 행동을 하지 않는 행동으로 단정하지 않습니다."),
        p(document["scale_notice"],small),*([p(text,small) for text in comparison_sources(profile)] if profile.survey_comparison else [p(document["external_notice"],small)]),p(f"생성 {header.generated_at} · 기본 결과 판본 {profile.source.basic.revision} · 원자료 판본 {profile.source.sheet.revision}",small)]))
    if cohort:
        story.extend([p(cohort.interpretation_note,small),p(cohort.selection_note,small),p(f"자체 비교 snapshot {cohort.reference.snapshot_id} · 판본 {cohort.reference.revision}",small)])
    def page(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(color("line")); canvas.line(44,32,551,32)
        canvas.setFillColor(color("muted")); canvas.setFont("KDogRP04",8)
        canvas.drawString(44,20,"K-DOG · 관찰 리포트" + (" · 검토용 미리보기" if header.preview else ""))
        canvas.drawRightString(551,20,str(document.page)); canvas.restoreState()
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
