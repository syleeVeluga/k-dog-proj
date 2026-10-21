import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' }, password = 'Browser-test-only-42';
async function login(page: Page, username = 'operator') {
  await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username); await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click(); await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function open(page: Page, participant: string) {
  await openMenu(page, '리포트 발급'); await page.getByRole('button', { name: `${participant} 리포트 열기`, exact: true }).click();
}
async function fixture(request: APIRequestContext, participant: string) {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'S1-REPORT', participant_id: participant, dog_name: '리포트 합성견', consents: { analysis_feedback: 'confirmed', stranger_contact: 'unknown' } } })).json();
  const base = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const bytes = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=2:duration=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  const receipt = await (await request.post('/api/uploads', { headers, data: { request_id: participant + '-media', filename: 'synthetic-report.mp4', expected_size: bytes.length } })).json();
  expect((await request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: bytes })).status()).toBe(200);
  expect((await request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: { case_id: item.case_id, session_id: item.selected_session_id, camera_id: 'CAM1', expected_revision: item.input_revision } })).status()).toBe(200);
  item = await (await request.get(`/api/cases/${item.case_id}`)).json(); const video = item.manifest.sessions[0].videos[0];
  const recording = { video_id: video.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '리포트 합성 절차 확인', segments: ['entry', 'baseline', 'alone', 'reunion', 'ignore', 'walk', 'stranger', 'exit'].map(segment => ({ segment, video_id: video.video_id, state: segment === 'entry' ? 'performed' : 'not_performed', start_sec: segment === 'entry' ? 0 : null, end_sec: segment === 'entry' ? 4 : null, reason: segment === 'entry' ? null : '합성 미실시' })) };
  const capture = await request.put(base + '/recording-s1', { headers, data: { expected_revision: item.input_revision, recording } }); expect(capture.status(), await capture.text()).toBe(200); item = await capture.json();
  const sheet = await (await request.post(base + '/sheets-s1', { headers, data: { expected_revision: item.input_revision, assigned_username: 'operator', rater_id: participant, rater_name: '리포트 평가자' } })).json();
  const catalog = await (await request.get('/api/catalog/behavior-s1')).json();
  const observations = catalog.items.filter((value: { usage: string; optional: boolean }) => value.usage !== 'automatic' && !value.optional).map((value: { code: string }) => ({ code: value.code, value: null, status: 'unobserved', reason: '합성 관찰 부족을 그대로 보존' }));
  const saved = await (await request.put(`/api/score-sheets-s1/${sheet.sheet_id}`, { headers, data: { expected_revision: sheet.revision, observations, reason: '합성 기록' } })).json();
  const submitted = await (await request.post(`/api/score-sheets-s1/${sheet.sheet_id}/submit`, { headers, data: { expected_revision: saved.revision, reason: '합성 독립 제출' } })).json();
  const calculated = await request.post(`/api/score-sheets-s1/${sheet.sheet_id}/basic-results-s1`, { headers, data: { input: { sheet_id: sheet.sheet_id, revision: submitted.revision, ref: submitted.manifest_ref, hash: submitted.manifest_hash } } }); expect(calculated.status(), await calculated.text()).toBe(201);
  const basic = (await calculated.json()).summary;
  const final = await request.post(base + '/final-results-s1', { headers, data: { basic: { result_id: basic.result_id, revision: basic.revision, ref: basic.manifest_ref, hash: basic.manifest_hash }, opinion: null, reason: '부족 사유를 보존한 리포트 최종본' } }); expect(final.status(), await final.text()).toBe(201);
  return { item, base, final: await final.json(), sheet: submitted, observations };
}

test.beforeEach(({ page }) => { page.setDefaultTimeout(15000); });

test('S1 report uses explicit final pins, recovers a lost create response and stops/retries without duplicate creation', async ({ page, request }) => {
  test.setTimeout(120000); const data = await fixture(request, 's1report-run'); await login(page); await open(page, 's1report-run');
  const panel = page.getByRole('region', { name: '리포트 실행', exact: true });
  await expect(panel.getByText('생성된 리포트 실행이 없습니다.', { exact: true })).toBeVisible();
  expect(await (await page.request.get(data.base + '/report-runs-s1')).json()).toEqual([]);
  await panel.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
  const requests: { request_id: string; final: unknown }[] = []; let lost = false;
  await page.route('**' + data.base + '/report-runs-s1', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    requests.push(route.request().postDataJSON());
    if (!lost) { lost = true; const response = await route.fetch(); expect(response.status()).toBe(201); return route.abort('failed'); }
    return route.continue();
  });
  await panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
  await expect(panel.getByText(/응답 확인이 필요한 요청/)).toBeVisible();
  await panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
  await expect(panel.getByRole('heading', { name: '대기', exact: true })).toBeVisible();
  expect(requests).toHaveLength(2); expect(requests[0].request_id).toBe(requests[1].request_id); expect(requests[0].final).toEqual(data.final.reference);
  const runs = await (await page.request.get(data.base + '/report-runs-s1')).json(); expect(runs).toHaveLength(1);
  await panel.getByLabel('실행 제어 기록', { exact: true }).fill('합성 중지와 고정 재시도');
  await panel.getByRole('button', { name: '이 리포트 실행 중지', exact: true }).click(); await expect(panel.getByRole('heading', { name: '중지', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '고정 입력으로 리포트 재시도', exact: true }).click(); await expect(panel.getByRole('heading', { name: '대기', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '이 리포트 실행 중지', exact: true }).click(); await expect(panel.getByRole('heading', { name: '중지', exact: true })).toBeVisible();
  await openMenu(page, '참가자 접수'); await openMenu(page, '리포트 발급');
  expect(await (await page.request.get(data.base + '/report-runs-s1')).json()).toHaveLength(1);
});

test('S1 report publication UI opens guarded cards and offline HTML, marks history, downloads and clears revoked output', async ({ page, request }, testInfo) => {
  test.setTimeout(120000); const data = await fixture(request, 's1report-issued');
  const previewDir = testInfo.outputPath('rendered');
  execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-m', 'tests.build_report_preview_v4', '--output', previewDir], { cwd: path.resolve('../backend') });
  const html = readFileSync(path.join(previewDir, 'filled.html'), 'utf8');
  const runId = 'a1'.repeat(16), oldId = 'b2'.repeat(16);
  const row = { run_id: runId, case_id: data.item.case_id, session_id: data.item.selected_session_id, kind: 'report_v4', input_revision: data.item.input_revision, status: 'succeeded', updated_at: '2026-10-04T01:00:00Z', outdated: false, result_available: true, is_latest_issued: true, publication_state: 'issued', normal_publish_available: true, pending_reasons: ['G02'], final: data.final.reference, steps: [{ stage: 'content_v4', attempt: 1, status: 'succeeded', code: null, timing: { total_seconds: 0.25 }, reused: true, provider_calls: 0 }] };
  const manifest = { artifact_kind: 'report-publication', report_id: 'synthetic-publication', run_id: runId, case_id: data.item.case_id, session_id: data.item.selected_session_id, input_revision: data.item.input_revision, input_hash: '1'.repeat(64), config_hash: '2'.repeat(64), final: data.final.reference, created_at: row.updated_at, publication_state: 'issued', normal_publish_available: true, pending_reasons: ['G02'], header: { dog_name: '합성 발급견', guardian_name: '합성 보호자', event_name: 'S1', participant_id: 'print', generated_at: row.updated_at }, profile: { status: 'partial', source_hash: '3'.repeat(64), cards: ['보호자 교육태도', '반려견과 보호자의 애착관계', '사회성', '함께걷기'].map((title, index) => ({ key: String(index), title, status: 'insufficient', label: null, claims: [{ claim_id: String(index), text: '확인된 관찰이 부족합니다.', fact_ids: [] }] })), validation_issues: [] }, output: { html: { ref: 'synthetic.html', hash: '4'.repeat(64) }, pdf: { ref: 'synthetic.pdf', hash: '5'.repeat(64) }, image_issues: {} } };
  row.pending_reasons = [];
  row.steps = [{ ...row.steps[0], reused: false, provider_calls: 1 }];
  manifest.pending_reasons = [];
  let blocked = false; const created: { reuse_run_id: string }[] = [];
  await page.route('**' + data.base + '/report-runs-s1', route => {
    if (route.request().method() === 'POST') { created.push(route.request().postDataJSON()); return route.fulfill({ status: 201, json: { ...row, run_id: 'synthetic-new', status: 'queued', normal_publish_available: false } }); }
    return route.fulfill({ json: [row, { ...row, run_id: oldId, is_latest_issued: false, outdated: true, input_revision: 1 }] });
  });
  await page.context().route('**' + data.base + '/report-runs-s1/*/files/*', route => {
    if (blocked) return route.fulfill({ status: 403, json: { detail: '합성 권한 철회: 발급본 열람 차단' } });
    const url = new URL(route.request().url()); const format = url.pathname.split('/').at(-1);
    if (format === 'manifest') return route.fulfill({ json: { ...manifest, run_id: url.pathname.includes(oldId) ? oldId : runId } });
    if (format === 'html') return route.fulfill({ contentType: 'text/html', body: html, headers: { 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; script-src 'none'" } });
    return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\nSynthetic UI download fixture', headers: { 'Content-Disposition': 'attachment; filename="synthetic-report.pdf"' } });
  });
  await login(page); await open(page, 's1report-issued');
  const panel = page.getByRole('region', { name: '리포트 실행', exact: true });
  await expect(panel.getByRole('region', { name: '리포트 발급본', exact: true })).toHaveCount(0);
  await expect(panel.getByRole('heading', { name: '발급 완료 · 이전 발급본 · 이전 입력·기준', exact: true })).toBeVisible();
  const current = panel.getByRole('article', { name: '리포트 실행 기록 ' + runId.slice(0, 8), exact: true });
  await current.getByText('기술 정보 · 단계·시도·시간·재사용', { exact: true }).click();
  await expect(current).toContainText('공급자 호출 예약 1회');
  await expect(current).toContainText('비용 미확인');
  await current.getByRole('button', { name: '발급 요약·HTML·PDF 열기', exact: true }).click();
  const output = panel.getByRole('region', { name: '리포트 발급본', exact: true }); await expect(output.getByRole('heading', { name: '합성 발급견 · 발급 결과', exact: true })).toBeVisible();
  expect(await output.innerText()).not.toContain(runId);
  await output.getByText('기술 정보', { exact: true }).click();
  await expect(output).toContainText(runId);
  await output.getByText('기술 정보', { exact: true }).click();
  await expect(output.getByRole('heading', { level: 4 })).toHaveCount(4);
  await expect(page.frameLocator('iframe[title="관찰 리포트 미리보기"]').locator('.sheet')).toHaveCount(6);
  const download = page.waitForEvent('download'); await output.getByRole('button', { name: 'PDF 저장', exact: true }).click(); const downloaded = await download; await downloaded.saveAs(testInfo.outputPath('downloaded.pdf')); expect(downloaded.suggestedFilename()).toBe(`kdog-s1-${runId}.pdf`); expect(readFileSync(testInfo.outputPath('downloaded.pdf'), 'utf8')).toContain('Synthetic UI download fixture');
  await page.frameLocator('iframe').locator('body').evaluate(() => { window.print = () => { document.body.dataset.printed = 'yes'; }; });
  await output.getByRole('button', { name: '열린 리포트 인쇄', exact: true }).click(); await expect(page.frameLocator('iframe').locator('body')).toHaveAttribute('data-printed', 'yes');
  await panel.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
  await panel.getByLabel('검증된 내용 명시 재사용', { exact: true }).selectOption(runId); await panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
  await expect.poll(() => created.length).toBe(1); expect(created[0].reuse_run_id).toBe(runId);
  await page.setViewportSize({ width: 360, height: 800 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await output.screenshot({ path: testInfo.outputPath('report-issued-s1-360.png'), animations: 'disabled' });
  await current.screenshot({ path: testInfo.outputPath('rp03-report-usage-360.png'), animations: 'disabled' });
  blocked = true; await panel.getByRole('button', { name: '리포트 상태 새로고침', exact: true }).click();
  await expect(output).toHaveCount(0); await expect(panel.getByRole('alert')).toHaveText('합성 권한 철회: 발급본 열람 차단');
});

test('AR05 reviewer creates a report from another final while an independent draft remains untouched', async ({ page, request }) => {
  test.setTimeout(120000); const data = await fixture(request, 'ar05report-shared');
  const created = await request.post(data.base + '/sheets-s1', { headers, data: { expected_revision: data.item.input_revision, source_sheet_id: data.sheet.sheet_id, assigned_username: 'reviewer', rater_id: 'ar05-professor', rater_name: '독립 리포트 교수' } });
  expect(created.status(), await created.text()).toBe(201); const draft = await created.json();
  await login(page, 'reviewer');
  const before = await (await page.request.get(`/api/score-sheets-s1/${draft.sheet_id}`)).json();
  await open(page, 'ar05report-shared'); const panel = page.getByRole('region', { name: '리포트 실행', exact: true });
  await panel.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
  await expect(panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true })).toBeEnabled();
  await expect(panel.getByText(/본인 제출 시트|명시 공개/)).toHaveCount(0);
  await panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
  const run = panel.getByRole('article').first(); await expect(run).toBeVisible();
  await run.getByText('열람·수정 기록', { exact: true }).click();
  await expect(run.getByRole('list', { name: '리포트 열람·수정 기록', exact: true })).toContainText('reviewer · 생성 요청');
  const after = await (await page.request.get(`/api/score-sheets-s1/${draft.sheet_id}`)).json();
  expect(after.document).toEqual(before.document); expect(after.summary.revision).toBe(before.summary.revision);
});

test('CM04 기본 발급은 별도 선택 없이 전 회차 누적 비교를 자동 연결하고 이전 방식은 접어 둔다', async ({ page, request }) => {
  test.setTimeout(120000); const data = await fixture(request, 'cm04report-default');
  await login(page); await open(page, 'cm04report-default');
  const panel = page.getByRole('region', { name: '리포트 실행', exact: true });
  const notice = panel.getByRole('region', { name: '누적 비교 발급 안내', exact: true });
  await expect(notice).toContainText('9개 지표의 우리 누적 평균');
  await expect(notice).toContainText(/현재 누적 대상: 포함 \d+쌍/);
  await expect(panel.getByText('이전 방식: 외부 비교 명시 선택', { exact: true })).toBeVisible();
  const posted: Record<string, unknown>[] = [];
  page.on('request', value => { if (value.method() === 'POST' && value.url().endsWith(data.base + '/report-runs-s1')) posted.push(value.postDataJSON()); });
  await panel.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
  await panel.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
  await expect(panel.getByRole('article').first()).toBeVisible();
  expect(posted).toHaveLength(1); expect(posted[0].cumulative).toBe(true); expect(posted[0]).not.toHaveProperty('external_comparison');
  const runs = await (await page.request.get(data.base + '/report-runs-s1')).json();
  expect(runs).toHaveLength(1); expect(runs[0].cumulative_comparison_as_of).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  await expect(panel.getByText(/누적 비교 집계 기준일 \d{4}-\d{2}-\d{2}/)).toBeVisible();
});
