import { test, expect, type Page } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page) {
  await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill('operator'); await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click(); await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function makeCase(page: Page, id: string, missing: boolean) {
  const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'S1-COHORT', participant_id: id, dog_name: '같은 이름 합성견', consents: { analysis_feedback: 'confirmed', stranger_contact: 'unknown' } } })).json();
  const answers: Record<string, number | null> = Object.fromEntries(Array.from({ length: 28 }, (_, index) => [`s${String(index + 1).padStart(2, '0')}`, index >= 9 && index <= 13 ? 0 : 3]));
  if (missing) { answers.s01 = null; answers.s10 = null; }
  const response = await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: { expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3', answers, not_applicable: [], blank_reasons: missing ? { s01: '합성 미응답', s10: '합성 미응답' } : {} } });
  expect(response.status(), await response.text()).toBe(200); return { item: await response.json(), answers };
}
test.beforeEach(({ page }) => { test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20261002', 'S1 browser fixture required'); page.setDefaultTimeout(15000); });

test('S1 cohorts pin explicit same-edition responses, preserve valid n and retries, and hide revoked source details', async ({ page }, testInfo) => {
  test.setTimeout(120000); const errors: string[] = []; page.on('pageerror', value => errors.push(value.message)); await login(page);
  const first = await makeCase(page, 'cohort-one', false), second = await makeCase(page, 'cohort-two', true);
  await page.request.post('/api/cases', { headers, data: { event_id: 'S1-COHORT', participant_id: 'cohort-unconfirmed', dog_name: '동의 미확인 합성견' } });
  await page.getByRole('button', { name: '리포트', exact: true }).click(); await page.getByText('자체 집단과 외부 비교 조건', { exact: true }).click();
  const panel = page.getByRole('region', { name: 'S1 자체 집단 비교', exact: true });
  await expect(panel.getByLabel('cohort-unconfirmed 집단 포함', { exact: true })).toHaveCount(0);
  await panel.getByLabel('집단 이름', { exact: true }).fill('합성 원척도 집단'); await panel.getByLabel('집단 선택 사유', { exact: true }).fill('동명이인 두 case를 각각 명시 선택');
  await panel.getByLabel('cohort-one 집단 포함', { exact: true }).check(); await panel.getByLabel('cohort-two 집단 포함', { exact: true }).check();
  const bodies: { request_id: string; members: { case_id: string }[] }[] = []; let lost = false;
  await page.route('**/api/comparisons-s1/cohorts', async route => {
    if (route.request().method() !== 'POST') return route.continue(); bodies.push(route.request().postDataJSON());
    if (!lost) { lost = true; const response = await route.fetch(); expect(response.status(), await response.text()).toBe(201); return route.abort('failed'); }
    return route.continue();
  });
  await panel.getByRole('button', { name: '선택 응답으로 새 집단 고정', exact: true }).click(); await expect(panel.getByText(/응답 확인이 필요한 요청/)).toBeVisible();
  await panel.getByRole('button', { name: '선택 응답으로 새 집단 고정', exact: true }).click();
  const detail = panel.getByRole('region', { name: '고정 집단 상세', exact: true }); await expect(detail.getByRole('heading', { name: '합성 원척도 집단', exact: true })).toBeVisible();
  expect(bodies).toHaveLength(2); expect(bodies[0].request_id).toBe(bodies[1].request_id); expect(new Set(bodies[0].members.map(value => value.case_id)).size).toBe(2);
  const history = await (await page.request.get('/api/comparisons-s1/cohorts')).json(); expect(history).toHaveLength(1);
  const saved = await (await page.request.get('/api/comparisons-s1/cohorts/' + history[0].reference.snapshot_id)).json();
  const fear = saved.document.domains.find((value: { question_ids: string[] }) => value.question_ids.includes('s10'));
  const education = saved.document.domains.find((value: { question_ids: string[] }) => value.question_ids.includes('s01'));
  expect(fear).toMatchObject({ mean: 0, n: 1, scale_minimum: 0, scale_maximum: 4 }); expect(education).toMatchObject({ mean: 3, n: 1 });
  await expect(detail.getByRole('row').filter({ hasText: fear.domain })).toContainText('0 · n=1'); await expect(detail.getByRole('row').filter({ hasText: fear.domain })).toContainText('포함 1 / 제외 1');
  const sources = await (await page.request.get('/api/comparisons-s1/sources')).text(); expect(sources).not.toContain('42926'); expect(sources).not.toContain('reference_values');
  await expect(panel.getByRole('heading', { name: '외부 비교 D06 · 확인 대기', exact: true })).toBeVisible();
  const changed = await page.request.put(`/api/cases/${first.item.case_id}/survey`, { headers, data: { expected_revision: first.item.input_revision, session_id: first.item.selected_session_id, survey_version: 'survey-20260929-v3', answers: { ...first.answers, s10: 4, s11: 4 }, not_applicable: [], blank_reasons: {} } }); expect(changed.status()).toBe(200);
  await panel.getByRole('button', { name: '비교 후보·이력 새로고침', exact: true }).click(); await expect(detail.getByText(/고정 이후 입력이 변경된 대상 1개/)).toBeVisible(); await expect(detail.getByRole('row').filter({ hasText: fear.domain })).toContainText('0 · n=1');
  await page.setViewportSize({ width: 360, height: 800 }); await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await detail.screenshot({ path: testInfo.outputPath('cohort-s1-360.png'), animations: 'disabled' });
  expect((await page.request.post(`/api/cases/${second.item.case_id}/deletion`, { headers, data: { expected_revision: second.item.input_revision } })).status()).toBe(200);
  await panel.getByRole('button', { name: '비교 후보·이력 새로고침', exact: true }).click(); await expect(detail).toHaveCount(0); await expect(panel.getByRole('alert')).toBeVisible(); expect(errors).toEqual([]);
});

test('S1 cohort drafts retain stale pins until explicit replacement and reports require explicit comparison selection', async ({ page }) => {
  test.setTimeout(120000); await login(page); const data = await makeCase(page, 'cohort-revision', false);
  await page.reload(); await page.getByRole('button', { name: '리포트', exact: true }).click(); await page.getByText('자체 집단과 외부 비교 조건', { exact: true }).click();
  const panel = page.getByRole('region', { name: 'S1 자체 집단 비교', exact: true });
  await panel.getByLabel('집단 이름', { exact: true }).fill('판본 충돌 합성 집단'); await panel.getByLabel('집단 선택 사유', { exact: true }).fill('선택 시점 판본 보호'); await panel.getByLabel('cohort-revision 집단 포함', { exact: true }).check();
  const changed = await page.request.put(`/api/cases/${data.item.case_id}/survey`, { headers, data: { expected_revision: data.item.input_revision, session_id: data.item.selected_session_id, survey_version: 'survey-20260929-v3', answers: { ...data.answers, s10: 2, s11: 2 }, not_applicable: [], blank_reasons: {} } }); expect(changed.status()).toBe(200); const current = await changed.json();
  await panel.getByRole('button', { name: '비교 후보·이력 새로고침', exact: true }).click(); await expect(panel.getByText(/선택 후 입력이 변경/)).toBeVisible();
  await panel.getByRole('button', { name: '선택 응답으로 새 집단 고정', exact: true }).click(); await expect(panel.getByRole('alert')).toBeVisible(); await expect(panel.getByLabel('집단 이름', { exact: true })).toHaveValue('판본 충돌 합성 집단');
  await panel.getByRole('button', { name: '이 대상 선택을 최신 판본으로 교체', exact: true }).click(); await panel.getByRole('button', { name: '선택 응답으로 새 집단 고정', exact: true }).click();
  await expect(panel.getByRole('region', { name: '고정 집단 상세', exact: true })).toBeVisible();
  const saved = (await (await page.request.get('/api/comparisons-s1/cohorts')).json()).find((value: { title: string }) => value.title === '판본 충돌 합성 집단');
  const final = { final_id: 'synthetic-cohort-final', ref: 'final-results/synthetic.json', hash: 'a'.repeat(64) }, base = `/api/cases/${data.item.case_id}/sessions/${data.item.selected_session_id}`;
  await page.route('**' + base + '/final-results-s1', route => route.fulfill({ json: [{ reference: final, recorded_at: '2026-10-04T01:00:00Z', actor: 'operator', basic: { result_id: 'synthetic-basic', revision: 1, ref: 'basic/synthetic.json', hash: 'b'.repeat(64) }, opinion: null, requires_reveal: false }] }));
  const starts: { comparison: unknown }[] = [];
  await page.route('**' + base + '/report-runs-s1', route => { if (route.request().method() === 'POST') { starts.push(route.request().postDataJSON()); return route.fulfill({ status: 201, json: {} }); } return route.fulfill({ json: [] }); });
  await page.reload(); await page.getByRole('button', { name: '리포트', exact: true }).click(); await page.getByRole('button', { name: 'cohort-revision 리포트 열기', exact: true }).click();
  const report = page.getByRole('region', { name: 'S1 리포트 실행', exact: true });
  await report.getByLabel('리포트에 고정할 최종본', { exact: true }).selectOption(final.final_id); await expect(report.getByLabel('리포트 자체 비교집단', { exact: true })).toHaveValue('');
  await report.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click(); await expect.poll(() => starts.length).toBe(1); expect(starts[0].comparison).toBeNull();
  await report.getByLabel('리포트 자체 비교집단', { exact: true }).selectOption(saved.reference.snapshot_id); await report.getByRole('button', { name: '선택한 최종본으로 리포트 생성', exact: true }).click(); await expect.poll(() => starts.length).toBe(2); expect(starts[1].comparison).toEqual(saved.reference);
  expect(current.input_revision).toBe(data.item.input_revision + 1);
  const added = await page.request.post(`/api/cases/${data.item.case_id}/sessions`, { headers, data: { expected_revision: current.input_revision, note: '비교 후 추가 회차' } }); expect(added.status()).toBe(200); const next = await added.json();
  await page.getByRole('button', { name: '현재 접수 입력 새로고침', exact: true }).click(); await expect(page.getByLabel('리포트 회차', { exact: true })).toHaveValue(next.selected_session_id);
  await page.getByLabel('선택 세션', { exact: true }).selectOption(data.item.selected_session_id); await expect(page.getByLabel('리포트 회차', { exact: true })).toHaveValue(data.item.selected_session_id);
});
