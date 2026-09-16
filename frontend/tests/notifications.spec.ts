import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };

for (const width of [1440, 360]) {
  test(`action notifications stay in view after scrolling at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    await page.getByLabel('계정', { exact: true }).fill('admin');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
    // A long participant list makes the page scroll; notifications must stay visible regardless of scroll position.
    for (let i = 0; i < 20; i++) {
      await page.request.post('/api/cases', { headers, data: { event_id: `NOTE-${width}`, participant_id: `N${String(i).padStart(3, '0')}`, dog_name: `알림 검증견 ${i}` } });
    }
    await expect(page.getByRole('button', { name: `N019 상세 열기` })).toBeVisible();
    await page.getByRole('button', { name: '자료 관리', exact: true }).click();
    await page.getByText('자료 백업·복구', { exact: true }).click();
    const backup = page.getByRole('button', { name: '자료 백업 생성 · 키 제외' });
    await page.route('**/api/admin/backups', route => route.fulfill({ status: 201, json: { path: 'synthetic-backup' } }));
    await backup.click();
    const success = page.getByRole('status').filter({ hasText: '검증된 백업 저장 완료: synthetic-backup' });
    await expect(success).toBeInViewport({ ratio: 1 });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(success).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: testInfo.outputPath(`notification-success-${width}.png`) });
    await success.getByRole('button', { name: '알림 닫기' }).click();
    await expect(success).toHaveCount(0);
    await page.route('**/api/admin/backups', route => route.fulfill({ status: 400, json: { detail: '백업 생성 실패' } }));
    await backup.click();
    const error = page.getByRole('alert');
    await expect(error).toContainText('백업 생성 실패');
    await expect(error).toBeInViewport({ ratio: 1 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(error).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`notification-error-${width}.png`) });
    await error.getByRole('button', { name: '알림 닫기' }).focus();
    await page.keyboard.press('Enter');
    await expect(error).toHaveCount(0);
    await page.route('**/api/admin/backups', route => route.fulfill({ status: 400, json: { detail: `연결 실패: ${'긴오류상세'.repeat(150)}` } }));
    await backup.click();
    await expect(error).toBeInViewport({ ratio: 1 });
    await expect(error.getByRole('button', { name: '알림 닫기' })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('button', { name: '로그아웃' }).click();
    await expect(error).toHaveCount(0);
  });
}
