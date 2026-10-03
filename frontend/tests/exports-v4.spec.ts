import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const headers = { 'X-KDOG-Request': '1' }, password = 'Browser-test-only-42', backend = path.resolve(process.cwd(), '../backend');
async function login(page: Page, username = 'operator') { await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username); await page.getByLabel('비밀번호', { exact: true }).fill(password); await page.getByRole('button', { name: '로그인', exact: true }).click(); await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible(); }
async function fixture(request: APIRequestContext, participant: string) {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'S14-EXPORT', participant_id: participant, dog_name: '연구 합성견', guardian_name: '합성 보호자', consent_confirmed: true, consents: { analysis_feedback: 'confirmed', stranger_contact: 'unknown' } } })).json();
  const base = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const bytes = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=2:duration=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  const receipt = await (await request.post('/api/uploads', { headers, data: { request_id: participant + '-media', filename: 'synthetic-export.mp4', expected_size: bytes.length } })).json();
  expect((await request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: bytes })).status()).toBe(200);
  expect((await request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: { case_id: item.case_id, session_id: item.selected_session_id, camera_id: 'CAM1', expected_revision: item.input_revision } })).status()).toBe(200);
  item = await (await request.get(`/api/cases/${item.case_id}`)).json(); const video = item.manifest.sessions[0].videos[0];
  const recording = { video_id: video.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '연구 내보내기 합성 절차', segments: ['entry', 'baseline', 'alone', 'reunion', 'ignore', 'walk', 'stranger', 'exit'].map(segment => ({ segment, video_id: video.video_id, state: segment === 'entry' ? 'performed' : 'not_performed', start_sec: segment === 'entry' ? 0 : null, end_sec: segment === 'entry' ? 4 : null, reason: segment === 'entry' ? null : '합성 미실시' })) };
  const capture = await request.put(base + '/recording-s1', { headers, data: { expected_revision: item.input_revision, recording } }); expect(capture.status(), await capture.text()).toBe(200); item = await capture.json();
  const sheet = await (await request.post(base + '/sheets-s1', { headers, data: { expected_revision: item.input_revision, assigned_username: 'operator', rater_id: participant, rater_name: '합성 연구 평가자' } })).json();
  const catalog = await (await request.get('/api/catalog/behavior-s1')).json();
  const observations = catalog.items.filter((value: { usage: string; optional: boolean }) => value.usage !== 'automatic' && !value.optional).map((value: { code: string }) => ['개5', '개45'].includes(value.code) ? { code: value.code, value: value.code === '개5' ? 0 : -2, status: 'observed', validity: 'valid', opportunity: 'present', evidence: [{ video_id: video.video_id, video_sha256: video.sha256, camera_id: 'CAM1', window_id: 'entry_whole', start_seconds: 0, end_seconds: 4, observed_seconds: 4, note: '합성 근거' }] } : { code: value.code, value: null, status: 'unobserved', reason: '=SUM(1,1)' });
  const save = await request.put(`/api/score-sheets-s1/${sheet.sheet_id}`, { headers, data: { expected_revision: sheet.revision, observations, reason: '합성 원값 기록' } }); expect(save.status(), await save.text()).toBe(200); const saved = await save.json();
  const submit = await request.post(`/api/score-sheets-s1/${sheet.sheet_id}/submit`, { headers, data: { expected_revision: saved.revision, reason: '합성 독립 제출' } }); expect(submit.status(), await submit.text()).toBe(200); const submitted = await submit.json();
  const calculated = await request.post(`/api/score-sheets-s1/${sheet.sheet_id}/basic-results-s1`, { headers, data: { input: { sheet_id: sheet.sheet_id, revision: submitted.revision, ref: submitted.manifest_ref, hash: submitted.manifest_hash } } }); expect(calculated.status(), await calculated.text()).toBe(201); const basic = (await calculated.json()).summary;
  const final = await request.post(base + '/final-results-s1', { headers, data: { basic: { result_id: basic.result_id, revision: basic.revision, ref: basic.manifest_ref, hash: basic.manifest_hash }, opinion: null, reason: '합성 최종본' } }); expect(final.status(), await final.text()).toBe(201);
  return { item, base, sheet: submitted, basic, final: await final.json(), observations };
}
async function openExport(page: Page, participant: string) { await page.getByRole('button', { name: '독립 채점', exact: true }).click(); await page.getByRole('button', { name: `${participant} 독립 채점 열기`, exact: true }).click(); await page.getByText('연구 내보내기', { exact: true }).click(); return page.getByRole('region', { name: 'S1 연구 내보내기', exact: true }); }
test.beforeEach(({ page }) => { page.setDefaultTimeout(15000); });

test('S14 reference workbook preserves raw cells, formulas, unknown identity and idempotent reference-only registration', async ({ page }, info) => {
  test.setTimeout(120000); await login(page); const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'S14-REFERENCE', participant_id: 'reference-only', dog_name: '동명이견', guardian_name: '평가자로 추정하면 안 되는 이름', consents: { analysis_feedback: 'declined', stranger_contact: 'unknown' } } })).json();
  expect((await (await page.request.get('/api/comparisons-s1/candidates')).json()).some((row: any) => row.case_id === item.case_id)).toBe(false);
  await page.getByRole('button', { name: '검수 자료', exact: true }).click(); const panel = page.getByRole('region', { name: '검수 참고 자료', exact: true });
  const buffer = execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-c', 'import sys; from tests.test_validation_data_v4 import workbook_bytes; sys.stdout.buffer.write(workbook_bytes())'], { cwd: backend });
  await panel.getByLabel('검수 XLSX 파일', { exact: true }).setInputFiles({ name: 'synthetic-reference.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer });
  await expect(panel.getByLabel('원본 시트', { exact: true })).toHaveValue('Synthetic');
  await panel.getByLabel('원본 대상 표기', { exact: true }).fill('합성 별칭'); await panel.getByLabel('셀 선택·상태 판단 사유', { exact: true }).fill('원본 셀과 전달 상태 보존');
  for (const [cell, code] of [['A1', '개5'], ['A2', '개13'], ['A3', '개32'], ['B1', '개30'], ['C1', '개59'], ['D1', '개10']]) {
    await panel.getByLabel('원본 셀 주소', { exact: true }).fill(cell); await panel.getByLabel('원본 항목 코드', { exact: true }).fill(code);
    if (cell === 'B1') { await expect(panel.getByLabel('원본 셀 검사')).toContainText('=SUM(A1:A2)'); await expect(panel.getByLabel('원본 셀 검사')).toContainText('저장 캐시: -2'); await panel.getByLabel('전달된 확정 상태').selectOption('ai_provisional'); }
    if (cell === 'D1') await panel.getByLabel('원본 대상 표기').fill('대응 미확인');
    await panel.getByRole('button', { name: '참고 행 선택에 추가', exact: true }).click();
  }
  await expect(panel.getByLabel('확인한 평가자')).toBeDisabled(); await expect(panel.getByLabel('대응 미확인 대응 대상')).toHaveValue('');
  await panel.getByLabel('합성 별칭 대응 대상').selectOption(item.case_id); await panel.getByLabel('원본 참여 상태').selectOption('withdrawn'); await panel.getByLabel('대응 확인 사유').fill('안정 ID를 확인하되 원본은 참여 중단');
  await panel.getByLabel('참고 등록 사유').fill('점수 복원 없이 합성 출처 참고');
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/validation-data-s1/preview'));
  await panel.getByRole('button', { name: '선택 자료 미리보기', exact: true }).click(); const preview = await (await previewResponse).json();
  const byCell = Object.fromEntries(preview.rows.map((row: any) => [row.source.cell, row]));
  expect(byCell.A1.source.value).toBe(0); expect(byCell.A2.source.value).toBe(-2); expect(byCell.D1.source.value).toBeNull(); expect(byCell.B1.source.value).toBeNull(); expect(byCell.B1.source.cached_value).toBe(-2); expect(byCell.A3.effective_status).toBe('legacy_semantics'); expect(byCell.C1.effective_status).toBe('example');
  expect(byCell.A1.exclusion_reasons).toContain('participant_withdrawn'); expect(byCell.D1.exclusion_reasons).toContain('unmatched_subject'); expect(preview.rows.every((row: any) => !row.current_s1_score && !row.independent_ground_truth && row.selection.evaluator === null)).toBe(true);
  const requests: any[] = []; let lost = true;
  await page.route('**/api/validation-data-s1', async route => { if (route.request().method() !== 'POST') return route.continue(); requests.push(route.request().postDataJSON()); if (lost) { lost = false; await route.fetch(); await route.abort('failed'); } else await route.continue(); });
  await panel.getByRole('button', { name: '참고 자료로 등록', exact: true }).click(); await expect(panel.getByRole('alert')).toBeVisible();
  await panel.getByRole('button', { name: '참고 자료로 등록', exact: true }).click(); await expect(panel.getByRole('status')).toContainText('검수 참고 자료를 등록했습니다');
  expect(requests).toHaveLength(2); expect(requests[0].config.request_id).toBe(requests[1].config.request_id);
  const list = await (await page.request.get('/api/validation-data-s1')).json(); expect(list.filter((row: any) => row.filename === 'synthetic-reference.xlsx')).toHaveLength(1);
  const detail = await (await page.request.get(`/api/validation-data-s1/${list.find((row: any) => row.filename === 'synthetic-reference.xlsx').reference.validation_id}`)).json(); expect(detail.document.source.hash).toBe(preview.source_sha256);
  expect((await page.request.get(`/api/cases/${item.case_id}/sessions/${item.selected_session_id}/sheets-s1`)).status()).toBe(403);
  expect((await (await page.request.get(`/api/cases/${item.case_id}`)).json()).input_revision).toBe(item.input_revision);
  await page.setViewportSize({ width: 360, height: 800 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await panel.screenshot({ path: info.outputPath('validation-s1-360.png') });
  expect(errors).toEqual([]);
});

test('S14 research download pins S1 raw/basic/final and preserves zero, negative, null and CSV safety', async ({ page, request }, info) => {
  test.setTimeout(120000); const data = await fixture(request, 'export-values'); await login(page); const panel = await openExport(page, 'export-values');
  await panel.getByLabel('기준 본인 시트').selectOption(data.sheet.sheet_id); await panel.getByLabel('내보낼 원자료 판본').selectOption(data.sheet.manifest_ref);
  await panel.getByLabel('같은 원자료의 기본 결과').selectOption(`${data.basic.result_id}:${data.basic.revision}`); await panel.getByLabel('최종 결과', { exact: true }).selectOption(data.final.reference.final_id);
  await panel.getByRole('button', { name: '고정 선택 목록에 추가', exact: true }).click(); await panel.getByLabel('연구 내보내기 사유').fill('합성 원자료 값 보존 시험');
  const sent: any[] = []; let lost = true;
  await page.route('**/api/exports-s1', async route => { if (route.request().method() !== 'POST') return route.continue(); sent.push(route.request().postDataJSON()); if (lost) { lost = false; const response = await route.fetch(); expect(response.status(), await response.text()).toBe(201); await route.abort('failed'); } else await route.continue(); });
  await panel.getByRole('button', { name: '선택 판본으로 연구 파일 생성', exact: true }).click(); await expect(panel.getByRole('alert')).toBeVisible(); await panel.getByRole('button', { name: '선택 판본으로 연구 파일 생성', exact: true }).click(); await expect(panel.getByRole('status')).toContainText('연구 파일 준비 완료');
  expect(sent).toHaveLength(2); expect(sent[0].request_id).toBe(sent[1].request_id); expect(sent[0].members[0].sheet.hash).toBe(data.sheet.manifest_hash); expect(sent[0].members[0].final).toEqual(data.final.reference);
  const downloadEvent = page.waitForEvent('download'); await panel.getByRole('button', { name: /연구 파일 다운로드/ }).first().click(); const download = await downloadEvent; const csvPath = info.outputPath(download.suggestedFilename()); await download.saveAs(csvPath);
  const parsed = JSON.parse(execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-c', "import sys,json,csv,zipfile; z=zipfile.ZipFile(sys.argv[1]); rows=list(csv.DictReader(z.read('raw_observations.csv').decode('utf-8-sig').splitlines())); print(json.dumps({'rows':rows,'names':z.namelist()},ensure_ascii=False))", csvPath], { cwd: backend, encoding: 'utf8' }));
  const rows = Object.fromEntries(parsed.rows.map((row: any) => [row.code, row])); expect(rows['개5'].value).toBe('0'); expect(rows['개45'].value).toBe('-2'); expect(rows['개6'].value).toBe(''); expect(rows['개6'].reason.startsWith("'")).toBe(true); expect(rows['개32']).toBeUndefined(); expect(parsed.names).toContain('independent_pairs.csv'); expect(JSON.stringify(parsed.rows)).not.toContain('합성 연구 평가자');
  await panel.getByLabel('내보낼 원자료 판본').selectOption(data.sheet.manifest_ref); await panel.getByRole('button', { name: '고정 선택 목록에 추가', exact: true }).click(); await panel.getByLabel('연구 파일 형식').selectOption('xlsx');
  await panel.getByRole('button', { name: '선택 판본으로 연구 파일 생성', exact: true }).click(); await expect.poll(async () => (await (await page.request.get('/api/exports-s1')).json()).filter((row: any) => row.format === 'xlsx').length).toBeGreaterThan(0);
  const xlsxEvent = page.waitForEvent('download'); await panel.locator('details[open]').getByRole('button', { name: /연구 파일 다운로드/ }).click(); const xlsx = await xlsxEvent; const xlsxPath = info.outputPath(xlsx.suggestedFilename()); await xlsx.saveAs(xlsxPath);
  const typed = JSON.parse(execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-c', "import sys,json,openpyxl; w=openpyxl.load_workbook(sys.argv[1],data_only=False); values=list(w['raw_observations'].values); rows=[dict(zip(values[0],r)) for r in values[1:]]; print(json.dumps({r['code']:r['value'] for r in rows},ensure_ascii=False)); w.close()", xlsxPath], { cwd: backend, encoding: 'utf8' })); expect(typed['개5']).toBe(0); expect(typed['개45']).toBe(-2); expect(typed['개6']).toBeNull();
  await page.setViewportSize({ width: 360, height: 800 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); await panel.screenshot({ path: info.outputPath('research-export-s1-360.png') });
  const current = await (await page.request.get(`/api/cases/${data.item.case_id}`)).json();
  expect((await page.request.post(`/api/cases/${data.item.case_id}/deletion`, { headers, data: { expected_revision: current.input_revision } })).status()).toBe(200);
  let leaked = false; page.on('download', () => { leaked = true; }); await panel.locator('details[open]').getByRole('button', { name: /연구 파일 다운로드/ }).click(); await expect(panel.getByRole('alert')).toBeVisible(); expect(leaked).toBe(false);
});

test('S14 already-revealed target is selectable; grant-only and reviewer export access remain blocked', async ({ page, request }) => {
  test.setTimeout(120000); const data = await fixture(request, 'export-disclosure');
  const assigned = await (await request.post(data.base + '/sheets-s1', { headers, data: { expected_revision: data.item.input_revision, source_sheet_id: data.sheet.sheet_id, assigned_username: 'admin', rater_id: 'export-admin', rater_name: '독립 연구 검토자' } })).json();
  await login(page, 'admin'); const base = `/api/score-sheets-s1/${assigned.sheet_id}`;
  const draft = await (await page.request.put(base, { headers, data: { expected_revision: assigned.revision, observations: data.observations, reason: '합성 독립 관찰' } })).json(); const submitted = await (await page.request.post(base + '/submit', { headers, data: { expected_revision: draft.revision, reason: '독립 제출' } })).json();
  expect((await request.post(base + '/grants', { headers, data: { expected_revision: submitted.revision, target_sheet_id: data.sheet.sheet_id, target_revision: data.sheet.revision, reason: '합성 공개' } })).status()).toBe(200);
  const panel = await openExport(page, 'export-disclosure'); await panel.getByLabel('기준 본인 시트').selectOption(assigned.sheet_id); await expect(panel.getByLabel('내보낼 원자료 판본').locator('option')).not.toContainText([/실제 공개 원본/]);
  expect((await page.request.post(base + '/reveal-ai-s1', { headers, data: { expected_revision: submitted.revision, ref: data.sheet.manifest_ref } })).status()).toBe(200);
  await panel.getByRole('button', { name: '내보내기 후보 새로고침', exact: true }).click(); await panel.getByLabel('내보낼 원자료 판본').selectOption(data.sheet.manifest_ref); await panel.getByRole('button', { name: '고정 선택 목록에 추가', exact: true }).click(); await panel.getByLabel('연구 내보내기 사유').fill('노출된 exact 원본 선택');
  const output = page.waitForResponse(response => response.url().endsWith('/exports-s1') && response.request().method() === 'POST'); await panel.getByRole('button', { name: '선택 판본으로 연구 파일 생성', exact: true }).click(); const exported = await output; expect(exported.status(), await exported.text()).toBe(201);
  expect((await request.post(`/api/score-sheets-s1/${data.sheet.sheet_id}/assignment`, { headers, data: { expected_revision: data.sheet.revision, active: false, reason: '원본 배정 취소' } })).status()).toBe(200);
  await panel.getByRole('button', { name: /연구 파일 다운로드/ }).click(); await expect(panel.getByRole('alert')).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click(); await login(page, 'reviewer'); await expect(page.getByRole('button', { name: '검수 자료', exact: true })).toHaveCount(0); expect((await page.request.get('/api/exports-s1')).status()).toBe(403);
});
