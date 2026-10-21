import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// Synthetic reports only: issued through the real backend admission, worker and renderers.
test('CM04 누적·미국 비교 패널은 오프라인 HTML의 390px·데스크톱·인쇄에서 판독된다', async ({ page, context }, testInfo) => {
  test.setTimeout(300000);
  const directory = testInfo.outputPath('reports');
  execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-m', 'tests.build_cumulative_report_v4', '--output', directory], { cwd: resolve('../backend'), encoding: 'utf8' });
  const external: string[] = [], errors: string[] = [];
  page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
  page.on('pageerror', error => errors.push(error.message));
  await context.setOffline(true);
  async function load(name: string) {
    await page.goto(pathToFileURL(resolve(directory, name + '.html')).href);
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('article.metric')).toHaveCount(9);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  const marks = (name: string) => page.locator(`article.metric[data-metric="${name}"] .mark`);
  for (const width of [1100, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await load('full');
    await expect(marks('S03')).toHaveCount(3); await expect(marks('S04')).toHaveCount(3); await expect(marks('S01')).toHaveCount(2);
    await expect(page.locator('article.metric[data-metric="S01"] .mark.us')).toHaveCount(0);
    const nf = await marks('S04').evaluateAll(items => items.map(item => [item.className, item.getBoundingClientRect().left, item.getBoundingClientRect().top]));
    const cumulative = nf.find(item => String(item[0]).includes('cumulative'))!, individual = nf.find(item => String(item[0]).includes('individual'))!;
    expect(Math.abs(Number(cumulative[1]) - Number(individual[1]))).toBeLessThan(0.5);
    expect(Number(individual[2])).toBeGreaterThan(Number(cumulative[2]) + 8);
    await expect(page.getByText('우리 누적 참여견 평균 1.00 (n=3)', { exact: true })).toBeVisible();
    await expect(page.getByText(/국내 표준이나 진단 기준은 아닙니다/)).toBeVisible();
    await page.locator('main > section').nth(1).screenshot({ path: testInfo.outputPath(`cm04-full-${width}.png`) });
    await load('missing');
    await expect(marks('S03')).toHaveCount(0);
    await expect(page.locator('article.metric[data-metric="S03"]')).toContainText('응답이 부족하여');
    await expect(marks('S04')).toHaveCount(3);
    await load('single');
    await expect(marks('S03')).toHaveCount(1);
    await expect(page.locator('article.metric[data-metric="S03"]')).toContainText('현재 n=1');
  }
  await page.emulateMedia({ media: 'print' });
  for (const name of ['full', 'missing', 'single']) {
    await load(name);
    const pdf = await page.pdf({ path: testInfo.outputPath(`cm04-browser-${name}.pdf`), printBackground: true, preferCSSPageSize: true });
    expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
    expect(await page.locator('article.metric').evaluateAll(items => items.every(item => getComputedStyle(item).breakInside === 'avoid'))).toBe(true);
  }
  expect(external).toEqual([]); expect(errors).toEqual([]);
});
