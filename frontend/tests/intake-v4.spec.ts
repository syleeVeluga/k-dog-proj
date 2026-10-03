import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
test.afterEach(async ({ page }) => {
  for (const item of (await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'S1-SYNTHETIC')) {
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  }
});

test('S1 접수는 빈 채점 상태로 시작하고 구판 채점으로 연결하지 않는다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  const result = await page.request.post('/api/cases', {
    headers: { 'X-KDOG-Request': '1' },
    data: { event_id: 'S1-SYNTHETIC', participant_id: 'S1-001', dog_name: '합성 반려견' },
  });
  expect(result.status()).toBe(201);
  const item = await result.json();
  expect(item.manifest.schema_version).toBe('intake-4.0');
  const other = await page.request.post('/api/cases', { headers,
    data: { event_id: 'S1-SYNTHETIC', participant_id: 'S1-002', dog_name: '다른 합성 반려견' } });
  expect(other.status()).toBe(201);
  await page.reload();
  await expect(page.getByRole('row').filter({ hasText: 'S1-SYNTHETIC' }).getByText('S1 재분석 필요', { exact: true })).toHaveCount(2);
  await page.getByRole('button', { name: 'S1-001 상세 열기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '합성 반려견', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('S1-001');
  const emptyStatus = page.getByRole('status').filter({ hasText: 'S1 재분석 필요' });
  await expect(emptyStatus.getByText('S1 재분석 필요', { exact: true })).toBeVisible();
  await expect(emptyStatus).toContainText('아직 채점값이 없습니다');
  await page.getByRole('button', { name: '독립 채점', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '배정된 시트가 없습니다.' })).toBeVisible();
  expect(await (await page.request.get(`/api/cases/${item.case_id}/sessions/${item.selected_session_id}/sheets-s1`)).json()).toEqual([]);
  const oldRun = await page.request.post(`/api/cases/${item.case_id}/sessions/${item.selected_session_id}/runs-v3`, {
    headers: { 'X-KDOG-Request': '1' }, data: { expected_revision: item.input_revision, request_id: 'old-denied' },
  });
  expect(oldRun.status()).toBe(409);
  await page.screenshot({ path: 'test-results/intake-s1-empty.png', fullPage: true });
});
