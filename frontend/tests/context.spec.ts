import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };

test('72명 목록에서 업무 맥락 유지 및 교수의 회차 조회는 읽기 전용', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  try {
    const csv = 'event_id,participant_id,dog_name,sequence_no\n' + Array.from({ length: 72 }, (_, i) => `CTX-A,C${String(i).padStart(3, '0')},맥락견${i},${i + 1}`).join('\n') + '\nCTX-B,C071,다른행사견,1\n';
    const preview = await (await page.request.post('/api/imports/preview?kind=participants&format=csv', { headers, data: csv })).json();
    expect((await page.request.post('/api/imports/commit', { headers, data: { rows: preview.rows } })).ok()).toBe(true);
    let item = (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string; participant_id: string }) => c.event_id === 'CTX-A' && c.participant_id === 'C071');
    const firstSession = item.selected_session_id;
    const version = (await (await page.request.get('/api/catalog/survey')).json()).version;
    item = await (await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: { expected_revision: item.input_revision, session_id: firstSession, survey_version: version, answers: Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, 3])) } })).json();
    item = await (await page.request.post(`/api/cases/${item.case_id}/sessions`, { headers, data: { expected_revision: item.input_revision, note: '두 번째 회차' } })).json();
    await page.getByRole('button', { name: '로그아웃' }).click();
    await page.getByLabel('계정', { exact: true }).fill('reviewer');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await page.getByLabel('행사 필터').selectOption('CTX-A');
    await page.getByRole('button', { name: 'C000 상세 열기' }).click();
    const context = page.getByLabel('선택 참가자');
    await expect(context.getByRole('heading')).toBeInViewport();
    await expect(context.getByRole('heading')).toBeFocused();
    await page.getByRole('button', { name: '전체 목록으로 돌아가기' }).click();
    await page.getByLabel('검색', { exact: true }).fill('C071');
    await page.getByRole('button', { name: 'C071 상세 열기' }).click();
    await expect(context).toContainText('CTX-A / C071 / 맥락견71 / 2차 촬영');
    await expect(context.getByRole('heading')).toBeInViewport();
    await page.getByLabel('선택 세션', { exact: true }).selectOption(firstSession);
    await page.getByRole('button', { name: '설문 보기', exact: true }).click();
    await expect(page.getByLabel('설문 현황')).toContainText('전 문항 응답');
    await expect(context).toContainText('1차 촬영');
    await page.getByRole('button', { name: '촬영 자료 보기', exact: true }).click();
    await expect(page.getByLabel('촬영 자료')).toContainText('1차 촬영');
    await expect(page.getByRole('button', { name: '8구간 초안 저장' })).toHaveCount(0);
    await page.setViewportSize({ width: 768, height: 1024 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(context.getByRole('heading')).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath('reviewer-context-768.png'), fullPage: true });
    const unchanged = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
    expect(unchanged.input_revision).toBe(item.input_revision);
    expect(unchanged.selected_session_id).toBe(item.selected_session_id);
    await page.getByRole('button', { name: '전체 목록으로 돌아가기' }).click();
    await expect(page.getByLabel('검색', { exact: true })).toHaveValue('C071');
    await expect(page.getByLabel('행사 필터')).toHaveValue('CTX-A');
  } finally {
    await page.request.post('/api/auth/login', { headers, data: { username: 'operator', password: 'Browser-test-only-42' } });
    const cases = await (await page.request.get('/api/cases')).json();
    for (const item of cases.filter((c: { event_id: string }) => c.event_id.startsWith('CTX-'))) {
      await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
    }
  }
});
