import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

test('RP04 photo-free report preserves content offline at mobile, desktop and A4 print', async ({ page, context }, testInfo) => {
  test.setTimeout(180000);
  const directory = testInfo.outputPath('reports');
  execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-m', 'tests.build_report_design_v4', '--output', directory], { cwd: resolve('../backend'), encoding: 'utf8' });
  const external: string[] = [], errors: string[] = [];
  page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
  page.on('pageerror', error => errors.push(error.message));
  await context.setOffline(true);
  async function load(name: string) {
    await page.goto(pathToFileURL(resolve(directory, name + '.html')).href);
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('main > section')).toHaveCount(6);
    await expect(page.locator('.card')).toHaveCount(4);
    await expect(page.locator('img, script, .scene, .photo-missing')).toHaveCount(0);
    await expect(page.locator('.comparison tbody tr')).toHaveCount(28);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await load('filled');
  await page.screenshot({ path: testInfo.outputPath('rp04-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 360, height: 800 });
  for (const name of ['filled', 'partial', 'missing', 'long', 'comparison', 'actions0', 'actions1', 'actions2', 'actions3']) {
    await load(name);
    if (name.startsWith('actions')) await expect(page.locator('.tip')).toHaveCount(Number(name.slice(-1)));
    if (name === 'long') await expect(page.getByText(/마지막검증표식/)).toHaveCount(1);
    if (name === 'comparison') await expect(page.getByText(/자체 평균/).first()).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('rp04-mobile-' + name + '.png'), fullPage: true });
  }
  await page.emulateMedia({ media: 'print' });
  for (const name of ['filled', 'missing', 'long', 'comparison']) {
    await load(name);
    const pdf = await page.pdf({ path: testInfo.outputPath('rp04-browser-' + name + '.pdf'), printBackground: true, preferCSSPageSize: true });
    expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
    expect(await page.locator('section').evaluateAll(elements => elements.every(element => getComputedStyle(element).breakAfter !== 'page' && getComputedStyle(element).overflow !== 'hidden'))).toBe(true);
  }
  expect(external).toEqual([]); expect(errors).toEqual([]);
});
