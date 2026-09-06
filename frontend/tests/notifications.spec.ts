import { test, expect } from '@playwright/test';

for (const width of [1440, 360]) {
  test(`action notifications stay in view after scrolling at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    await page.getByLabel('계정', { exact: true }).fill('developer');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    const keyTest = page.getByRole('button', { name: '키 연결 시험', exact: true });
    await page.route('**/api/developer/keys/gemini/test', route => route.fulfill({ json: { status: '연결 성공' } }));
    await keyTest.click();
    const success = page.getByRole('status').filter({ hasText: '연결 시험: 연결 성공' });
    await expect(success).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => scrollY)).toBeGreaterThan(500);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(success).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: testInfo.outputPath(`notification-success-${width}.png`) });
    await success.getByRole('button', { name: '알림 닫기' }).click();
    await expect(success).toHaveCount(0);
    await keyTest.click();
    await expect(success).toBeInViewport({ ratio: 1 });

    await page.route('**/api/developer/status', route => route.fulfill({ json: { message: '인증 상태 확인 완료' } }));
    await page.getByRole('button', { name: '인증 상태 확인' }).click();
    const globalNotice = page.getByRole('status').filter({ hasText: '인증 상태 확인 완료' });
    await expect(globalNotice).toBeInViewport({ ratio: 1 });
    await page.route('**/api/developer/keys/gemini/test', route => route.fulfill({ status: 400, json: { detail: '키 연결에 실패했습니다. 공급자 설정과 API 키를 확인하세요.' } }));
    await keyTest.click();
    const error = page.getByRole('alert');
    await expect(error).toContainText('키 연결에 실패했습니다.');
    await expect(error).toBeInViewport({ ratio: 1 });
    await expect(success).toHaveCount(0);
    const first = await globalNotice.boundingBox();
    const second = await error.boundingBox();
    expect(first!.y + first!.height <= second!.y || second!.y + second!.height <= first!.y).toBe(true);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(error).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`notification-error-${width}.png`) });
    await error.getByRole('button', { name: '알림 닫기' }).focus();
    await page.keyboard.press('Enter');
    await expect(error).toHaveCount(0);
    await globalNotice.getByRole('button', { name: '알림 닫기' }).click();
    await page.route('**/api/developer/keys/gemini/test', route => route.fulfill({ status: 400, json: { detail: `연결 실패: ${'긴오류상세'.repeat(150)}` } }));
    await keyTest.click();
    await expect(error).toBeInViewport({ ratio: 1 });
    await expect(error.getByRole('button', { name: '알림 닫기' })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('button', { name: '로그아웃' }).click();
    await expect(error).toHaveCount(0);
  });
}

test('report settings and backup failures use error notifications', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('developer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByLabel('설명 모델 ID')).toBeVisible();
  await page.route('**/api/developer/report', route => route.fulfill({ status: 400, json: { detail: '설명 설정 저장 실패' } }));
  await page.getByRole('button', { name: '새 실행에 설명 설정 적용' }).click();
  await expect(page.getByRole('alert')).toContainText('설명 설정 저장 실패');
  await expect(page.getByRole('alert')).toBeInViewport({ ratio: 1 });
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByLabel('계정', { exact: true }).fill('admin');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByText('자료 백업·복구', { exact: true }).click();
  await page.route('**/api/admin/backups', route => route.fulfill({ status: 400, json: { detail: '백업 생성 실패' } }));
  await page.getByRole('button', { name: '자료 백업 생성 · 키 제외' }).click();
  await expect(page.getByRole('alert')).toContainText('백업 생성 실패');
  await expect(page.getByRole('alert')).toBeInViewport({ ratio: 1 });
});
