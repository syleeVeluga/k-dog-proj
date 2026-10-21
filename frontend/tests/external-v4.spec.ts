import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' }, password = 'Browser-test-only-42';
const sourceId = 'us2026-stranger-fear';
async function login(page: Page, username: string) {
  await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username); await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click(); await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function fixture(request: APIRequestContext, participant: string) {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'S17-EXTERNAL', participant_id: participant, dog_name: '외부 비교 합성견', consent_confirmed: true, consents: { analysis_feedback: 'confirmed', stranger_contact: 'unknown' } } })).json();
  const survey = await request.put(`/api/cases/${item.case_id}/survey`, { headers, data: { expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3', answers: { ...item.manifest.sessions[0].survey, s10: 0, s11: 0, s12: 0, s13: 0, s14: 0 }, not_applicable: [], blank_reasons: {} } });
  expect(survey.status(), await survey.text()).toBe(200); item = await survey.json();
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

test('AR05 common definition applies immediately and retirement preserves HTML/PDF and research files', async ({ page, request, browser, baseURL }, info) => {
  test.setTimeout(180000); page.setDefaultTimeout(15000);
  const data = await fixture(request, 'external-only-synthetic');
  const prior = await fixture(request, 'external-blocked-prior');
  const priorExportResponse = await request.post('/api/exports-s1', { headers, data: { request_id: 'external-blocked-prior-export', format: 'csv_zip', members: [{ case_id: prior.item.case_id, session_id: prior.item.selected_session_id, sheet: { sheet_id: prior.sheet.sheet_id, revision: prior.sheet.revision, ref: prior.sheet.manifest_ref, hash: prior.sheet.manifest_hash } }], reason: '새로운 정상 자료와 함께 남는 제공 차단 이력 검증' } });
  expect(priorExportResponse.status(), await priorExportResponse.text()).toBe(201);
  const priorExport = await priorExportResponse.json();

  await login(page, 'reviewer');
  const temporaryBackup = await page.request.post('/api/admin/backups', { headers });
  expect(temporaryBackup.status()).toBe(201);
  const dataRoot = path.join(path.dirname(path.dirname((await temporaryBackup.json()).path)), 'data');
  expect(path.basename(path.dirname(dataRoot))).toMatch(/^kdog-browser-/);
  await openMenu(page, '비교 조건');
  await page.locator('summary').filter({ hasText: /^외부 비교 기준 정의$/ }).click();
  const research = page.getByRole('region', { name: '외부 비교 기준 정의', exact: true });
  await research.getByLabel('연구 출처', { exact: true }).selectOption(sourceId);
  await expect(research.getByLabel('외부 평균', { exact: true })).toHaveValue('');
  const client = await browser.newContext();
  try {
    const operator = await client.newPage(); operator.setDefaultTimeout(15000); await login(operator, 'operator');
    await openMenu(operator, '비교 조건');
    await operator.locator('summary').filter({ hasText: /^외부 비교 기준 정의$/ }).click();
    expect((await operator.request.get('/api/comparisons-s1/definitions')).status()).toBe(200);
    const blockedSources = await (await operator.request.get('/api/comparisons-s1/sources')).json();
    expect(JSON.stringify(blockedSources)).not.toContain('reference_values');
    expect(JSON.stringify(blockedSources)).not.toContain('0.66');
    const evidenceResponse = page.waitForResponse(value => value.url().includes('/comparisons-s1/evidence?'));
    await research.getByLabel('기준 근거 파일', { exact: true }).setInputFiles({ name: 'synthetic-definition.txt', mimeType: 'text/plain', buffer: Buffer.from('SYNTHETIC BROWSER TEST DATA ONLY') });
    expect((await evidenceResponse).status()).toBe(201);
    await research.getByRole('button', { name: '전달 기준 수치 불러오기', exact: true }).click();
    for (const [label, value] of [['외부 평균', '0.66'], ['외부 표준편차', '0.91'], ['외부 유효 표본 n', '42926'], ['외부 전체 표본 n', '43517']]) await expect(research.getByLabel(label, { exact: true })).toHaveValue(value);
    await expect(research.getByLabel('수치 출처·표 위치', { exact: true })).toHaveValue(/EXT1\.1.*문항별 대조표 A46/);
    for (const [label, value] of [['외부 평균', '0.66'], ['외부 표준편차', '0.91'], ['외부 유효 표본 n', '42926'], ['외부 전체 표본 n', '43517']]) await research.getByLabel(label, { exact: true }).fill(value);
    await research.getByLabel('비교 대상 범위', { exact: true }).fill('SYNTHETIC POPULATION ONLY');
    await research.getByLabel('수치 출처·표 위치', { exact: true }).fill('SYNTHETIC FIXTURE TABLE');
    await research.getByLabel('기준 변경 기록', { exact: true }).fill('합성 기준 정의 저장·적용');
    await research.getByRole('button', { name: '기준 정의 저장·적용', exact: true }).click();
    await expect(research.getByRole('status')).toContainText('기준 정의를 저장하고 적용했습니다');
    await research.getByLabel('외부 평균', { exact: true }).fill('0.67');
    await research.getByLabel('기준 변경 기록', { exact: true }).fill('보존할 미저장 입력');
    const latest = await (await operator.request.get('/api/comparisons-s1/definitions')).json();
    const { artifact_kind, definition_id, revision, actor, recorded_at, ...remoteDocument } = latest.documents[sourceId];
    const remote = await operator.request.post('/api/comparisons-s1/definitions', { headers, data: { expected_revision: revision, document: { ...remoteDocument, reason: '다른 업무 계정의 기준 판본' } } });
    expect(remote.status(), await remote.text()).toBe(200);
    await research.getByRole('button', { name: '기준 정의 새로고침', exact: true }).click();
    await expect(research.getByText(/작성 이후 기준이 변경됐습니다/)).toBeVisible();
    const conflict = page.waitForResponse(value => value.url().endsWith('/comparisons-s1/definitions') && value.request().method() === 'POST');
    await research.getByRole('button', { name: '기준 정의 저장·적용', exact: true }).click();
    expect((await conflict).status()).toBe(409);
    await expect(research.getByLabel('외부 평균', { exact: true })).toHaveValue('0.67');
    page.once('dialog', dialog => dialog.accept());
    await research.getByRole('button', { name: '최신 기준으로 새 작성', exact: true }).click();
    await research.getByLabel('기준 변경 기록', { exact: true }).fill('새 판본 그대로 적용');
    await research.getByRole('button', { name: '기준 정의 저장·적용', exact: true }).click();
    await expect(research.getByRole('status')).toContainText('기준 정의를 저장하고 적용했습니다');
    await page.setViewportSize({ width: 360, height: 800 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await research.screenshot({ path: info.outputPath('ar05-shared-definition-360.png'), animations: 'disabled' });

    await openMenu(operator, '리포트 발급');
    await operator.getByRole('button', { name: 'external-only-synthetic 리포트 열기', exact: true }).click();
    const report = operator.getByRole('region', { name: '리포트 실행', exact: true });
    await report.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
    const picker = report.getByRole('group', { name: '이 출력의 외부 비교', exact: true });
    await expect(picker.getByRole('combobox', { name: '이 출력의 외부 비교', exact: true })).toHaveValue('');
    await picker.getByText('확인된 출처로 새 비교 고정', { exact: true }).click();
    await picker.getByLabel('미국 보호자 보고: 낯선 사람에 대한 두려움 외부 비교 포함', { exact: true }).check();
    await picker.getByLabel('외부 비교 고정 사유', { exact: true }).fill('합성 현재 입력·원척도 일치 확인');
    await operator.setViewportSize({ width: 360, height: 800 });
    await expect.poll(() => operator.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await picker.screenshot({ path: info.outputPath('external-picker-360.png') });
    let lost = true; const requests: any[] = [];
    await operator.route('**/api/comparisons-s1/external-snapshots', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      requests.push(route.request().postDataJSON());
      if (lost) { lost = false; const response = await route.fetch(); expect(response.status(), await response.text()).toBe(201); return route.abort('failed'); }
      await route.continue();
    });
    await picker.getByRole('button', { name: '선택 조건으로 외부 비교 고정', exact: true }).click();
    await expect(picker.getByRole('alert')).toBeVisible();
    const createdSnapshot = operator.waitForResponse(value => value.url().endsWith('/comparisons-s1/external-snapshots') && value.request().method() === 'POST');
    await picker.getByRole('button', { name: '선택 조건으로 외부 비교 고정', exact: true }).click();
    const snapshot = await (await createdSnapshot).json();
    expect(requests).toHaveLength(2); expect(requests[0].request_id).toBe(requests[1].request_id);
    expect(snapshot.document.target.input.manifest_hash).toBe(requests[0].target.input.manifest_hash);
    await expect(picker.getByRole('combobox', { name: '이 출력의 외부 비교', exact: true })).toHaveValue(snapshot.reference.snapshot_id);
    const started = operator.waitForResponse(value => value.url().endsWith('/report-runs-s1') && value.request().method() === 'POST');
    await report.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click();
    const job = await (await started).json();
    const env = { ...process.env }; for (const key of ['GEMINI_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY']) delete env[key];
    execFileSync('../backend/.venv/Scripts/python.exe', ['-X', 'utf8', '-c',
      `import pathlib,sys
from app.storage import Store
from app.worker import Worker
from tests.test_report_narrative_v4 import generated
root=pathlib.Path(sys.argv[1]).resolve()
assert root.name=='data' and root.parent.name.startswith('kdog-browser-')
store=Store(root)
with store.connect() as db:
    rows=db.execute("SELECT run_id,kind FROM runs WHERE status IN ('queued','running')").fetchall()
    assert [(r['run_id'],r['kind']) for r in rows]==[(sys.argv[2],'report_v4')]
class SyntheticNarrativeProvider:
    def request_v4(self, files, config, context, schema, guard):
        guard()
        assert files == []
        return generated(context), {}
assert Worker(store, observer=SyntheticNarrativeProvider()).once()
with store.connect() as db:
    run=db.execute("SELECT status FROM runs WHERE run_id=?", (sys.argv[2],)).fetchone()
    assert run['status']=='succeeded'
    assert db.execute("SELECT SUM(call_reserved) FROM steps WHERE run_id=?", (sys.argv[2],)).fetchone()[0]==1`,
      dataRoot, job.run_id], { cwd: path.resolve('../backend'), env, timeout: 90000, encoding: 'utf8' });
    await report.getByRole('button', { name: '리포트 상태 새로고침', exact: true }).click();
    await report.getByRole('button', { name: '발급 요약·HTML·PDF 열기', exact: true }).click();
    const publication = report.getByRole('region', { name: '발급 당시 외부 비교', exact: true });
    await expect(publication).toContainText('설문 평균 0');
    await expect(publication).toContainText('외부 참고 평균 0.66');
    const htmlPath = `${data.base}/report-runs-s1/${job.run_id}/files/html`;
    const html = await operator.request.get(htmlPath); expect(html.status()).toBe(200); expect(await html.text()).toContain('외부 유효 표본');
    const pdf = await operator.request.get(htmlPath.replace(/html$/, 'pdf')); expect(pdf.status()).toBe(200); expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
    await expect(operator.frameLocator('iframe[title="관찰 리포트 미리보기"]').getByText('본인 설문 평균 0', { exact: false })).toBeVisible();
    const rendered = await operator.context().newPage();
    try {
      const externalRequests: string[] = [];
      rendered.on('request', value => { if (/^https?:/.test(value.url()) && !value.url().startsWith(new URL(baseURL!).origin + '/')) externalRequests.push(value.url()); });
      await rendered.setViewportSize({ width: 360, height: 800 });
      await rendered.goto(htmlPath + '?inline=true'); await rendered.evaluate(() => document.fonts.ready);
      await expect(rendered.locator('main > section')).toHaveCount(6);
      await expect.poll(() => rendered.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await rendered.locator('main > section').nth(1).screenshot({ path: info.outputPath('external-html-360.png') });
      await rendered.emulateMedia({ media: 'print' });
      expect(await rendered.locator('main > section').evaluateAll(elements => elements.length === 6 && elements.every(element => getComputedStyle(element).overflow !== 'hidden' && getComputedStyle(element).breakAfter !== 'page'))).toBe(true);
      const printed = await rendered.pdf({ path: info.outputPath('external-browser-print.pdf'), printBackground: true, preferCSSPageSize: true });
      expect(printed.toString('latin1').match(/\/Type \/Page\b/g)?.length ?? 0).toBeGreaterThan(0);
      expect(externalRequests).toEqual([]);
    } finally { await rendered.close(); }
    await operator.setViewportSize({ width: 360, height: 800 });
    await expect.poll(() => operator.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await publication.screenshot({ path: info.outputPath('external-report-360.png') });

    await openMenu(operator, '독립 채점');
    const exportHistory = await operator.request.get('/api/exports-s1');
    expect(exportHistory.status(), await exportHistory.text()).toBe(200);
    expect((await exportHistory.json()).find((value: { export_id: string }) => value.export_id === priorExport.export_id)).toMatchObject({ status: 'ready' });
    await openMenu(operator, '연구 내보내기');
    const exporter = operator.getByRole('region', { name: '연구 내보내기', exact: true });
    await exporter.getByLabel('기준 시트', { exact: true }).selectOption(data.sheet.sheet_id);
    await exporter.getByLabel('내보낼 원자료 판본', { exact: true }).selectOption(data.sheet.manifest_ref);
    await exporter.getByLabel('최종 결과', { exact: true }).selectOption(data.final.reference.final_id);
    const exportPicker = exporter.getByRole('group', { name: '이 출력의 외부 비교', exact: true });
    await exportPicker.getByRole('combobox', { name: '이 출력의 외부 비교', exact: true }).selectOption(snapshot.reference.snapshot_id);
    await expect.poll(() => operator.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await exportPicker.screenshot({ path: info.outputPath('external-export-picker-360.png') });
    await exporter.getByRole('button', { name: '고정 선택 목록에 추가', exact: true }).click();
    await exporter.getByLabel('연구 내보내기 사유').fill('합성 외부 비교 원척도·유효 n 보존');
    const exported = operator.waitForResponse(value => value.url().endsWith('/api/exports-s1') && value.request().method() === 'POST');
    await exporter.getByRole('button', { name: '선택 판본으로 연구 파일 생성', exact: true }).click();
    const exportResponse = await exported; expect(exportResponse.status(), await exportResponse.text()).toBe(201); const exportedRow = await exportResponse.json();
    const downloadEvent = operator.waitForEvent('download');
    await exporter.getByRole('button', { name: `연구 파일 다운로드 ${exportedRow.export_id.slice(0, 8)}`, exact: true }).click();
    const download = await downloadEvent, filename = info.outputPath(download.suggestedFilename()); await download.saveAs(filename);
    const rows = JSON.parse(execFileSync('../backend/.venv/Scripts/python.exe', ['-X', 'utf8', '-c', "import csv,io,json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps(list(csv.DictReader(io.StringIO(z.read('comparisons.csv').decode('utf-8-sig')))),ensure_ascii=False))", filename], { encoding: 'utf8' }));
    expect(rows).toHaveLength(1); expect(rows[0]).toMatchObject({ source: 'external_reference', local_mean: '0.0', mean: '0.66', valid_n: '42926', total_n: '43517' });

    await research.getByLabel('새 계산에 사용', { exact: true }).uncheck();
    await research.getByLabel('기준 변경 기록', { exact: true }).fill('합성 기준 사용중단');
    await research.getByRole('button', { name: '기준 정의 저장·적용', exact: true }).click();
    await expect(research.getByRole('status')).toContainText('새 계산에서 사용 중단했습니다');
    const savedDownload = operator.waitForEvent('download');
    await exporter.getByRole('button', { name: `연구 파일 다운로드 ${exportedRow.export_id.slice(0, 8)}`, exact: true }).click();
    await savedDownload;
    expect((await operator.request.get(htmlPath)).ok()).toBe(true);
    await openMenu(operator, '리포트 발급');
    await expect(report.getByRole('button', { name: '발급 요약·HTML·PDF 열기', exact: true })).toBeVisible();
    const currentSnapshot = await (await operator.request.get(`/api/comparisons-s1/external-snapshots/${snapshot.reference.snapshot_id}`)).json();
    expect(currentSnapshot.status).toBe('ready'); expect(currentSnapshot.document).toEqual(snapshot.document);
    expect(currentSnapshot.new_selection_available).toBe(false);
    await report.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(data.final.reference.final_id);
    await picker.getByRole('button', { name: '외부 비교 조건 새로고침', exact: true }).click();
    await expect(picker.locator(`option[value="${snapshot.reference.snapshot_id}"]`)).toBeDisabled();
    const denied = await operator.request.post('/api/comparisons-s1/external-snapshots', { headers, data: { ...requests[0], request_id: 'ar05-retired-new' } });
    expect(denied.status()).toBe(409);
  } finally { await client.close(); }
});
