"""Server PDF using the same pinned content and scales as offline HTML."""

from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .report_render_v4 import STATUS, comparison_legend, comparison_rows, number, presentation, survey_rows, time_text, timeline_rows, validate
from .domain.comparisons_v4 import CohortPublicV4
from .storage import REPO_ROOT


class SurveyBar(Flowable):
    def __init__(self, value, minimum, maximum, width):
        super().__init__()
        self.width, self.height = width, 12
        self.fraction = (value - minimum) / (maximum - minimum)

    def draw(self):
        self.canv.setFillColor(colors.HexColor("#DFE9E2"))
        self.canv.roundRect(0, 3, self.width, 6, 3, fill=1, stroke=0)
        if self.fraction:
            self.canv.setFillColor(colors.HexColor("#C9523C"))
            self.canv.roundRect(0, 3, self.width*self.fraction, 6, 3, fill=1, stroke=0)


def render_pdf(profile, header, images=(), *, cohort=None):
    profile, header, photos = validate(profile, header, images)
    cohort = CohortPublicV4.model_validate(cohort) if cohort is not None else None
    surveys = survey_rows(profile, cohort)
    design = presentation()
    for name, filename in (("KDogS1", "NanumGothic-Regular.ttf"), ("KDogS1Symbols", "NotoSansSymbols.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(REPO_ROOT / "resources/fonts" / filename)))
    ink = colors.HexColor(design["colors"]["ink"])
    muted = colors.HexColor(design["colors"]["muted"])
    style = ParagraphStyle("bodyS1", fontName="KDogS1", fontSize=10, leading=16, wordWrap="CJK", textColor=ink, spaceAfter=8)
    small = ParagraphStyle("smallS1", parent=style, fontSize=8, leading=12, textColor=muted, spaceAfter=5)
    cell = ParagraphStyle("cellS1", parent=style, fontSize=7.8, leading=10.5, spaceAfter=1)
    survey_cell = ParagraphStyle("surveyCellS1", parent=cell, textColor=colors.HexColor("#C9523C"))
    video_cell = ParagraphStyle("videoCellS1", parent=cell, textColor=colors.HexColor("#087F77"))
    heading = ParagraphStyle("headingS1", parent=style, fontSize=16, leading=23, spaceBefore=10, spaceAfter=10, keepWithNext=True)
    title = ParagraphStyle("titleS1", parent=heading, fontSize=25, leading=34, spaceBefore=4, spaceAfter=22)
    hero = ParagraphStyle("heroS1", parent=title, textColor=colors.white, spaceAfter=10)
    white = ParagraphStyle("whiteS1", parent=style, textColor=colors.HexColor("#D4EDBF"))
    def p(text, selected=style):
        value = escape(str(text)).replace("\n", "<br/>")
        for symbol in "②④⑥⑧⑩":
            value = value.replace(symbol, f'<font name="KDogS1Symbols">{symbol}</font>')
        return Paragraph(value, selected)
    def claims(items, selected=style):
        return [p(item.text, selected) for item in items]
    def box(content, background="#FFFFFF"):
        table = Table([[content]], colWidths=[511], splitInRow=1)
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor(background)),
                                  ("TOPPADDING", (0,0), (-1,-1), 15), ("BOTTOMPADDING", (0,0), (-1,-1), 10),
                                  ("LEFTPADDING", (0,0), (-1,-1), 17), ("RIGHTPADDING", (0,0), (-1,-1), 17)]))
        return table
    def build(overflow=False):
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=(595.28,841.89), leftMargin=42, rightMargin=42.28,
                               topMargin=34, bottomMargin=42, title="K-DOG 관찰 리포트", author="K-DOG", invariant=1)
        story = []
        def section(index):
            if index:
                story.append(PageBreak())
            story.extend([p("K-DOG · OBSERVATION REPORT" + (" · 검토용 미리보기" if header.preview else ""), small),
                          p(f'{index+1:02} / 06', small), p(design['sections'][index], title)])
        section(0)
        story.append(box([p(f"{header.dog_name}의 오늘", hero), p(f"{header.guardian_name} · {header.event_name} · {header.observed_date}", white)], "#153D39"))
        story.append(Spacer(1,15))
        cards = [[p(card.title, small), p(card.label or STATUS[card.status], heading), *claims(card.claims)] for card in profile.cards]
        grid = Table([[cards[0], cards[1]], [cards[2], cards[3]]], colWidths=[255.5,255.5], splitInRow=1)
        grid.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.white), ("VALIGN", (0,0),(-1,-1),"TOP"),
                                 ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#DFE9E2")),
                                 ("INNERGRID",(0,0),(-1,-1),0.5,colors.HexColor("#DFE9E2")),
                                 ("LEFTPADDING",(0,0),(-1,-1),14), ("RIGHTPADDING",(0,0),(-1,-1),14),
                                 ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10)]))
        story.extend([grid, Spacer(1,12), box(claims(profile.summary) or [p("관찰 자료를 확인하고 있습니다.")], "#E1EFDA"), p(design['legend'], small)])
        if overflow:
            story.append(p(design['overflow_notice'], small))
        section(1)
        for scene in profile.scenes:
            photo = photos.get(scene.scene_id)
            left = []
            if photo:
                image = Image(BytesIO(photo.data))
                ratio = min(155/image.imageWidth,82/image.imageHeight)
                image.drawWidth, image.drawHeight = image.imageWidth*ratio, image.imageHeight*ratio
                image.hAlign = "LEFT"
                left.extend([image, p(f'{photo.camera_id} · 원본 {time_text(photo.source_seconds)}', small)])
            else:
                left.append(p("사진을 확인하지 못했습니다. 연결된 실제 관찰 근거를 표시합니다.", small))
            right = [p(scene.title, heading), p(f'공통시각 {time_text(scene.reference_start_seconds)}–{time_text(scene.reference_end_seconds)}', small),
                     *claims(scene.claims), p(" / ".join(f'{entry.camera_id} {time_text(entry.start_seconds)}–{time_text(entry.end_seconds)}' for entry in scene.evidence), small)]
            table = Table([[left,right]],colWidths=[173,338],splitInRow=1)
            table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("BACKGROUND",(0,0),(-1,-1),colors.white),
                                      ("BOTTOMPADDING",(0,0),(-1,-1),10)]))
            story.extend([table,Spacer(1,8)])
        if profile.scene_notice:
            story.append(p(profile.scene_notice))
        story.extend(p(entry.reason,small) for entry in profile.scene_review)
        story.append(p("기록된 실제 구간",heading))
        timeline = [[p(label,small),p(interval,small),p(state,small)] for label,interval,state in timeline_rows(profile,'segment')]
        if timeline:
            story.append(Table(timeline,colWidths=[80,155,276],splitInRow=1))
        section(2)
        story.append(p("평소 보호자 응답을 원래 눈금으로 표시합니다. 값이 작거나 크다는 사실만으로 좋고 나쁨을 정하지 않습니다."))
        if cohort:
            story.append(p(f'자체 비교 집단: {cohort.title} · 선택 {cohort.selection_count}개체', small))
        for row in surveys:
            story.append(p(f'{row["title"]} · {number(row["value"])}'))
            if row['value'] is not None:
                story.append(SurveyBar(row['value'], row['minimum'], row['maximum'], 490))
            story.append(p(f"눈금 {row['minimum']}–{row['maximum']} · {row['detail']}", small))
        story.append(p(design['external_notice'],small))
        section(3)
        story.append(p(design['scale_notice'], small))
        for label in comparison_legend(profile):
            story.append(p(label,small))
        data = [[p("평소의 질문",cell), p("설문 값",cell), p("이번 영상 관찰",cell)]]
        for text,survey,video,details in comparison_rows(profile):
            data.append([p(text,cell), p(survey,survey_cell), p("\n".join([video,*details]),video_cell)])
        table = Table(data, colWidths=[265,73,173], repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E9F0E8")),
                                  ("LINEBELOW",(0,0),(-1,-1),0.25,colors.HexColor("#DFE9E2")),
                                  ("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),3),
                                  ("BOTTOMPADDING",(0,0),(-1,-1),3)]))
        story.append(table)
        section(4)
        for item in profile.details:
            story.append(p(item.title,heading))
            story.extend(claims(item.claims) or [p(STATUS[item.status])])
            if item.key == 'walking':
                walks = [[p(label,small),p(interval,small),p(state,small)] for label,interval,state in timeline_rows(profile,'walk_phase')]
                if walks:
                    story.append(Table(walks,colWidths=[80,155,276],splitInRow=1))
        section(5)
        for index,claim in enumerate(profile.actions):
            story.extend([p(f'{index+1:02} · 오늘부터 해보기',heading), p(claim.text)])
        if profile.actions_notice:
            story.append(p(profile.actions_notice))
        story.extend([p("오늘의 관찰을 함께 읽으며",heading), *claims(profile.summary), p("관찰 범위와 출처",heading),
                      p("확정된 영상 원자료, 보호자 설문과 완료된 해석을 바탕으로 작성했습니다. 관찰되지 않은 행동을 하지 않는 행동으로 단정하지 않습니다."),
                      p(design['scale_notice'],small), p(design['external_notice'],small),
                      p(f'생성 {header.generated_at} · 기본 결과 판본 {profile.source.basic.revision} · 원자료 판본 {profile.source.sheet.revision}',small)])
        if cohort:
            story.extend([p(cohort.interpretation_note, small), p(cohort.selection_note, small),
                          p(f'자체 비교 snapshot {cohort.reference.snapshot_id} · 판본 {cohort.reference.revision}', small)])
        if header.preview:
            story.append(p("검토용 미리보기",small))
        def page(canvas, document):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor(design['colors']['background']))
            canvas.rect(0,0,595.28,841.89,fill=1,stroke=0)
            canvas.setStrokeColor(colors.HexColor("#DFE9E2"))
            canvas.line(42,32,553,32)
            canvas.setFillColor(muted)
            canvas.setFont("KDogS1",8)
            canvas.drawString(42,20,"K-DOG · 관찰 리포트" + (" · 검토용 미리보기" if header.preview else ""))
            canvas.drawRightString(553,20,str(document.page))
            canvas.restoreState()
        doc.build(story,onFirstPage=page,onLaterPages=page)
        return output.getvalue(), doc.page
    data, count = build()
    return build(True)[0] if count > 6 else data
