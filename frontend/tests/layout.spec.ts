import { test, expect } from '@playwright/test';

for (const width of [360, 390, 768, 1440]) {
  test(`layout: notification leaves navigation usable and context preserves actions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/');
    await page.getByLabel('계정', { exact: true }).fill('operator');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '3초마다 자동 갱신' })).toContainText(/마지막 조회 [^·\s]/);
    await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeEnabled();
    const registration = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
    if (await registration.getAttribute('open') === null) await registration.getByText('참가자 등록', { exact: true }).click();
    await page.getByLabel('행사 ID', { exact: true }).fill('UIUX-LAYOUT');
    await page.getByLabel('참가자 ID', { exact: true }).fill(`L${width}`);
    await page.getByLabel('반려견 이름', { exact: true }).fill('레이아웃 합성견');
    await page.getByRole('button', { name: '참가자 저장', exact: true }).click();
    const notice = page.getByRole('status').filter({ hasText: '참가자를 등록했습니다.' });
    await expect(notice).toBeInViewport({ ratio: 1 });
    const navigation = page.getByRole('navigation', { name: '주 메뉴' });
    const navBox = await navigation.boundingBox(), noticeBox = await notice.boundingBox();
    expect(navBox).not.toBeNull(); expect(noticeBox).not.toBeNull();
    if (width <= 680) expect(noticeBox!.y).toBeGreaterThanOrEqual(navBox!.y + navBox!.height);
    await navigation.getByRole('button', { name: '설문', exact: true }).click();
    await expect(page.getByRole('heading', { name: '설문', exact: true })).toBeVisible();
    const context = page.getByRole('region', { name: '선택 참가자', exact: true });
    if (width <= 680) {
      expect((await context.boundingBox())!.height).toBeLessThan(300);
      await expect(context.getByRole('button', { name: '촬영 자료 보기', exact: true })).toBeHidden();
      const toggle = context.getByRole('button', { name: '회차 안내·바로가기', exact: true });
      await toggle.focus(); await page.keyboard.press('Enter');
      await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    }
    await context.getByRole('button', { name: '촬영 자료 보기', exact: true }).click();
    const panel = page.getByRole('region', { name: 'S1 촬영 기록', exact: true });
    await expect(panel).toBeVisible();
    await notice.getByRole('button', { name: '알림 닫기' }).click();
    await expect(panel.locator('details.recording-section')).toHaveCount(8);
    await expect(panel.getByLabel('입장 사유', { exact: true })).toBeHidden();
    const summary = panel.getByText('실제 8구간', { exact: true });
    await summary.focus(); await page.keyboard.press('Enter');
    await panel.getByLabel('입장 사유', { exact: true }).fill('접었다 펼쳐도 보존하는 합성 입력');
    await summary.click();
    await expect(panel.getByLabel('입장 사유', { exact: true })).toBeHidden();
    await summary.click();
    await expect(panel.getByLabel('입장 사유', { exact: true })).toHaveValue('접었다 펼쳐도 보존하는 합성 입력');
    await panel.getByText('안전기지 실제 순서', { exact: true }).click();
    await panel.getByText('안전기지 실제 순서', { exact: true }).scrollIntoViewIfNeeded();
    await expect(panel.getByRole('button', { name: '촬영 기록 초안 저장', exact: true })).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`recording-layout-${width}.png`), fullPage: true });
    // Secondary navigation remains accessible when resizing the current context.
    await page.setViewportSize({ width: width <= 680 ? 1440 : 360, height: 800 });
    if (width > 680) await context.getByRole('button', { name: '회차 안내·바로가기', exact: true }).click();
    await expect(context.getByRole('button', { name: '전체 목록으로 돌아가기', exact: true })).toBeVisible();
  });
}
