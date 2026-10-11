import { test, expect } from '@playwright/test';

test('명시 상세 열기만 이력에 남고 새로고침·기록 조회는 기록을 늘리지 않는다', async ({ page }, testInfo) => {
  const headers = { 'X-KDOG-Request': '1' };
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('reviewer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const id = `ACTIVITY_${Date.now()}`;
  const response = await page.request.post('/api/cases', { headers, data: { event_id: 'ACTIVITY', participant_id: id, dog_name: '활동 합성견' } });
  expect(response.status()).toBe(201);
  const item = await response.json();
  for (let index = 0; index < 24; index++) await page.request.get(`/api/cases/${item.case_id}?purpose=open`);
  await page.reload();
  await page.getByRole('button', { name: `${id} 상세 열기`, exact: true }).click();
  await page.getByText('최근 열람·수정·실행 기록', { exact: true }).click();
  const logs = page.getByRole('list', { name: '대상 활동 기록' });
  await expect(logs).toContainText('reviewer · 참가자 자료 열기');
  const path = `/api/cases/${item.case_id}/activity`;
  const before = await (await page.request.get(path)).json();
  await page.request.get(`/api/cases/${item.case_id}?purpose=open`);
  await page.getByRole('button', { name: '이전 기록 더 보기' }).click();
  await expect(logs.locator(':scope > li')).toHaveCount(26);
  await expect(logs).toContainText('reviewer · 참가자 등록');
  await logs.getByText('대상 확인', { exact: true }).last().click();
  await expect(logs.locator(':scope > li')).toHaveCount(26);
  for (let index = 0; index < 10; index++) {
    await page.request.get('/api/cases');
    await page.request.get(`/api/cases/${item.case_id}`);
  }
  await page.getByRole('button', { name: '최근 기록 새로고침' }).click();
  expect(await (await page.request.get(path + `?before=${before.before}`)).json()).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath('activity-history.png') });
});
