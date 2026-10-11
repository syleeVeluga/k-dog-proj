import { test, expect } from '@playwright/test';
import { videoCounts } from '../src/progressText';
import type { Case } from '../src/types';

for (const width of [1366, 820, 390]) test(`${width}px 접수 제목의 참가자 수가 읽을 수 있는 폭을 유지한다`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const count = page.locator('.count span');
  await expect(count).toBeVisible();
  expect((await count.boundingBox())!.width).toBeGreaterThanOrEqual(50);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`review-intake-${width}.png`), fullPage: true });
});

test('이전 회차에는 현재 회차의 영상 집계를 붙이지 않는다', () => {
  const item = { selected_session_id: 'current', manifest: { sessions: [
    { session_id: 'previous', videos: [] }, { session_id: 'current', videos: [{}, {}] },
  ] }, progress: { session_id: 'current', videos_total: 2, videos_usable: 1 } } as unknown as Case;
  expect(videoCounts(item, 0)).toBe('0개');
  expect(videoCounts(item, 1)).toBe('2개 · 사용 가능 1 · 확인 대기 1');
});

test('모바일 메뉴는 Tab과 Shift+Tab으로 메뉴 안에서 순환한다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '메뉴', exact: true }).click();
  const buttons = page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button');
  await buttons.last().focus();
  await page.keyboard.press('Tab');
  await expect(buttons.first()).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(buttons.last()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: '메뉴', exact: true })).toBeFocused();
});

test('채점한 참가자는 접수 목록에 채점 전으로 표시하지 않는다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const headers = { 'X-KDOG-Request': '1' };
  const response = await page.request.post('/api/cases', { headers, data: {
    event_id: 'UIUX-REVIEW', participant_id: 'SCORED', dog_name: '검토견',
  } });
  expect(response.status()).toBe(201);
  const item = await response.json();
  try {
    await page.route('**/api/cases', async route => {
      const upstream = await route.fetch();
      const rows = await upstream.json();
      await route.fulfill({ response: upstream, json: rows.map((row: Case) => row.case_id === item.case_id
        ? { ...row, progress: { ...row.progress, scoring: 'done', preprocess: 'outdated' } } : row) });
    });
    await page.getByRole('button', { name: '새로고침', exact: true }).click();
    const row = page.getByRole('row').filter({ hasText: 'SCORED' });
    await expect(row).toBeVisible();
    await expect(row).not.toContainText('채점 전');
    await expect(row).toContainText('채점 제출 완료');
    await row.getByRole('button', { name: 'SCORED 상세 열기', exact: true }).click();
    await page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '독립 채점', exact: true }).click();
    await expect(page.getByRole('region', { name: '선행 조건', exact: true })).toContainText('새 입력의 전처리 결과가 필요하면 운영자에게 재실행을 요청하세요.');
  } finally {
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  }
});
