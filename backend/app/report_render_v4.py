"""Offline S1 HTML and shared, non-scoring presentation values."""

import base64
import hashlib
import json
from html import escape

from .domain.report_profile_v4 import ReportProfileV4
from .domain.report_render_v4 import ReportHeaderV4, SceneImageV4
from .storage import REPO_ROOT


ASSETS = ("resources/report/presentation-v4.json", "resources/report/templates/s1.html",
          "resources/report/templates/s1.css", "resources/fonts/NanumGothic-Regular.ttf",
          "resources/fonts/NotoSansSymbols.ttf")
STATUS = {"available": "관찰됨", "partial": "일부 관찰", "insufficient": "관찰 부족", "held": "판단 보류"}
SEGMENTS = {"entry": "입장", "baseline": "기준", "alone": "혼자", "reunion": "재회", "ignore": "무시", "walk": "걷기", "stranger": "낯선", "exit": "퇴장"}
PHASES = {"move_1": "첫 이동", "stop_1": "첫 정지", "move_2": "둘째 이동", "stop_2": "둘째 정지", "move_3": "셋째 이동", "stop_3": "셋째 정지"}


def assets():
    return {name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest() for name in ASSETS}


def presentation():
    return json.loads((REPO_ROOT / ASSETS[0]).read_text(encoding="utf-8"))


def number(value):
    return "미산출" if value is None else f"{value:.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def fact_text(fact):
    unit = f" ({fact.unit})" if fact.unit and '~' in fact.unit else f" {fact.unit}"
    return number(fact.value) + (unit if fact.value is not None and fact.unit else "")


def validate(profile, header, images):
    profile = ReportProfileV4.model_validate_json(profile.model_dump_json())
    header = ReportHeaderV4.model_validate_json(header.model_dump_json())
    if any(issue.blocking for issue in profile.validation_issues):
        raise ValueError("해결되지 않은 내용 검증 오류가 있어 출력할 수 없습니다.")
    photos = {}
    for image in images:
        image = SceneImageV4.model_validate(image)
        scene = next((entry for entry in profile.scenes if entry.scene_id == image.scene_id), None)
        if scene is None or image.scene_id in photos or not any(
                (entry.video_id, entry.video_sha256, entry.camera_id) == (image.video_id, image.video_sha256, image.camera_id)
                and entry.start_seconds <= image.source_seconds <= entry.end_seconds for entry in scene.evidence):
            raise ValueError("사진은 선택한 실제 장면의 원본·시각에 연결되어야 합니다.")
        signature = b"\x89PNG\r\n\x1a\n" if image.mime == "image/png" else b"\xff\xd8\xff"
        if not image.data.startswith(signature) or hashlib.sha256(image.data).hexdigest() != image.image_sha256:
            raise ValueError("사진 형식 또는 고정 hash가 다릅니다.")
        photos[image.scene_id] = image
    assets()
    return profile, header, photos


def survey_rows(profile):
    values = {item.item_id: item for item in profile.source.survey.items}
    rows = []
    for domain in profile.source.survey.domains:
        allowed = sorted({value for key in domain.question_ids for value in values[key].allowed_values})
        rows.append({"title": domain.domain, "value": domain.mean, "minimum": min(allowed), "maximum": max(allowed),
                     "detail": f"응답 {domain.answered_count}/{domain.target_count} · " +
                     (f"{number(domain.numerator)} ÷ {domain.denominator}" if domain.mean is not None else domain.reason or "미산출")})
    one = profile.source.survey.standalone
    rows.append({"title": "일상 따라옴 (단일 원응답)", "value": one.raw,
                 "minimum": min(one.allowed_values), "maximum": max(one.allowed_values),
                 "detail": f"응답 {int(one.raw is not None)}/1 · " + (one.blank_reason or ("원응답" if one.raw is not None else "원응답 없음"))})
    return rows


def comparison_rows(profile):
    facts = {fact.fact_id: fact for fact in profile.facts}
    reversed_items = {item.item_id for item in profile.source.survey.items if item.reverse_scored}
    rows = []
    for item in profile.comparisons:
        reversed_answer = item.key in reversed_items
        survey_ids = [key for key in item.survey_fact_ids if reversed_answer or not key.startswith('survey-raw:')]
        survey = " / ".join(("원응답 " if key.startswith('survey-raw:') else "역채점 " if reversed_answer else "") + fact_text(facts[key]) for key in survey_ids) or "원응답 없음"
        if survey_ids and all(facts[key].value is None for key in survey_ids):
            survey = "원응답 없음"
        video = " / ".join(("·".join(facts[key].item_codes) + ": " if facts[key].item_codes else "") + fact_text(facts[key]) for key in item.video_fact_ids) or "관찰 부족"
        if not item.direct_video_task:
            video = "직접 확인 과제 없음 · " + video
        # Keep concrete comparison explanations; the identical scale notice is printed once.
        details = [claim.text for claim in item.claims if claim.claim_id.startswith("observation:")]
        rows.append((item.title, survey, video, details))
    return rows


def comparison_legend(profile):
    used = {key for item in profile.comparisons for key in item.video_fact_ids}
    return [f'{"·".join(fact.item_codes)} · {fact.label} ({fact.unit or "원척도"})' for fact in profile.facts
            if fact.fact_id in used and fact.label]


def time_text(seconds):
    return f"{int(seconds // 60):02}:{seconds % 60:05.2f}"


def timeline_rows(profile, kind):
    labels = SEGMENTS if kind == 'segment' else PHASES
    rows = []
    for item in profile.timeline:
        if item.kind != kind:
            continue
        start, end = item.reference_start_seconds, item.reference_end_seconds
        interval = f'{time_text(start)}–{time_text(end)}' if start is not None and end is not None else '시각 미기록'
        state = {'performed':'수행', 'shortened':'단축', 'not_performed':'미수행', 'welfare_stopped':'복지 중단'}[item.state]
        rows.append((labels.get(item.key, item.key), interval, state + (f' · {item.reason}' if item.reason else '')))
    return rows


def render_html(profile, header, images=()):
    profile, header, photos = validate(profile, header, images)
    design = presentation()
    e = lambda value: escape(str(value), quote=True)
    def paragraphs(claims):
        return "".join(f'<p>{e(claim.text)}</p>' for claim in claims)
    def notice(text):
        return f'<p class="basis">{e(text)}</p>' if text else ""
    sections = []
    def section(index, body):
        banner = '<span>검토용 미리보기</span>' if header.preview else '<span>관찰 리포트</span>'
        sections.append(f'<section class="sheet" data-section="{index+1}"><div class="brand"><span>K-DOG · OBSERVATION REPORT</span>{banner}</div>'
                        f'<div class="eyebrow">{index+1:02} / 06</div><h2>{e(design["sections"][index])}</h2>{body}'
                        f'<footer class="footer"><span>{e(header.dog_name)} · {e(header.participant_id)}</span><span>{e(header.observed_date)}</span></footer></section>')
    cards = ''.join(f'<article class="card"><div class="small">{e(card.title)}</div><div class="value">{e(card.label or STATUS[card.status])}</div>{paragraphs(card.claims)}</article>' for card in profile.cards)
    section(0, f'<div class="hero"><div>K-DOG 관찰 리포트</div><h1>{e(header.dog_name)}의 오늘</h1><p>{e(header.guardian_name)} · {e(header.event_name)} · {e(header.observed_date)}</p></div>' +
            f'<div class="cards">{cards}</div><div class="callout">{paragraphs(profile.summary)}</div><p class="legend">{e(design["legend"])}</p>')
    scenes = []
    for scene in profile.scenes:
        photo = photos.get(scene.scene_id)
        picture = f'<img alt="선택한 관찰 장면" src="data:{photo.mime};base64,{base64.b64encode(photo.data).decode()}">' if photo else '<div class="photo-missing">사진을 확인하지 못했습니다.<br>연결된 실제 관찰 근거를 표시합니다.</div>'
        caption = f'{photo.camera_id} · 원본 {time_text(photo.source_seconds)}' if photo else " / ".join(f'{entry.camera_id} {time_text(entry.start_seconds)}–{time_text(entry.end_seconds)}' for entry in scene.evidence)
        scenes.append(f'<article class="scene"><div>{picture}{notice(caption)}</div><div><h3>{e(scene.title)}</h3><div class="time">공통시각 {time_text(scene.reference_start_seconds)}–{time_text(scene.reference_end_seconds)}</div>{paragraphs(scene.claims)}</div></article>')
    timeline = '<h3>기록된 실제 구간</h3><table><thead><tr><th>구간</th><th>공통시각</th><th>실제 상태</th></tr></thead><tbody>' + ''.join(f'<tr><td>{e(label)}</td><td>{e(interval)}</td><td>{e(state)}</td></tr>' for label,interval,state in timeline_rows(profile,'segment')) + '</tbody></table>'
    section(1, ''.join(scenes) + notice(profile.scene_notice) + ''.join(notice(entry.reason) for entry in profile.scene_review) + timeline)
    charts = []
    for row in survey_rows(profile):
        width = 0 if row['value'] is None else (row['value']-row['minimum'])/(row['maximum']-row['minimum'])*100
        bar = f'<div class="track"><div class="fill" style="width:{width:.3f}%"></div></div>' if row['value'] is not None else ''
        charts.append(f'<div class="survey-row"><div class="bar-label"><span>{e(row["title"])}</span><span class="survey">{e(number(row["value"]))}</span></div>{bar}{notice(f"눈금 {row['minimum']}–{row['maximum']} · {row['detail']}")}</div>')
    section(2, '<p>평소 보호자 응답을 원래 눈금으로 표시합니다. 값이 작거나 크다는 사실만으로 좋고 나쁨을 정하지 않습니다.</p>' + ''.join(charts) + notice(design['external_notice']))
    rows = ''.join(f'<tr><td>{e(title)}</td><td class="survey">{e(survey)}</td><td class="video">{e(video)}' + ''.join(f'<p>{e(detail)}</p>' for detail in details) + '</td></tr>' for title,survey,video,details in comparison_rows(profile))
    section(3, f'<p>{e(design["scale_notice"])}</p>' + notice(' / '.join(comparison_legend(profile))) + f'<table><thead><tr><th>평소의 질문</th><th>설문 값</th><th>이번 영상 관찰</th></tr></thead><tbody>{rows}</tbody></table>')
    walk = '<div class="walk">' + ''.join(f'<div>{e(label)}<p>{e(interval)}</p>{notice(state)}</div>' for label,interval,state in timeline_rows(profile,'walk_phase')) + '</div>'
    section(4, ''.join(f'<article class="box"><h3>{e(item.title)}</h3>{paragraphs(item.claims) or notice(STATUS[item.status])}{walk if item.key == "walking" else ""}</article>' for item in profile.details))
    actions = ''.join(f'<article class="tip"><div class="number">{index+1}</div><div>{e(claim.text)}</div></article>' for index,claim in enumerate(profile.actions))
    section(5, actions + notice(profile.actions_notice) + '<h3>오늘의 관찰을 함께 읽으며</h3>' + paragraphs(profile.summary) +
            '<h3>관찰 범위와 출처</h3><p>확정된 영상 원자료, 보호자 설문과 완료된 해석을 바탕으로 작성했습니다. 관찰되지 않은 행동을 하지 않는 행동으로 단정하지 않습니다.</p>' +
            notice(design['scale_notice']) + notice(design['external_notice']) + notice(f'생성 {header.generated_at} · 기본 결과 판본 {profile.source.basic.revision} · 원자료 판본 {profile.source.sheet.revision}') +
            notice('기본 여섯 장의 내용을 유지하며 긴 설명은 인쇄 시 다음 쪽으로 이어집니다.'))
    css = (REPO_ROOT / ASSETS[2]).read_text(encoding='utf8')
    for font, name in ((ASSETS[3], 'KDog'), (ASSETS[4], 'KDogSymbols')):
        css += f"\n@font-face{{font-family:{name};src:url(data:font/ttf;base64,{base64.b64encode((REPO_ROOT/font).read_bytes()).decode()}) format('truetype');}}"
    template = (REPO_ROOT / ASSETS[1]).read_text(encoding='utf8')
    return template.replace('__TITLE__', e(f'{header.dog_name} · K-DOG 관찰 리포트')).replace('__STYLE__', css).replace('__SECTIONS__', ''.join(sections)).encode('utf8')
