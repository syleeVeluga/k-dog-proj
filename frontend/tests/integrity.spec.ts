import { test, expect } from '@playwright/test';

test('검증 실패 자료 안내와 정상 참가자 조회를 함께 유지한다', async ({ page }, testInfo) => {
  await page.route('**/api/cases', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'X-KDOG-Unavailable-Cases': '1' } });
  });
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('입력 자료 검증에 실패한 참가자 1명');
  await expect(page.getByRole('heading', { name: '접수', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('integrity-warning.png'), fullPage: true });
});
