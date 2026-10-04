import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

test('S1 standalone report stays offline, preserves source scales, escapes text and adapts to 360px', async ({ page, context }, testInfo) => {
  test.setTimeout(120000);
  const directory = testInfo.outputPath('html');
  execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-m', 'tests.build_report_preview_v4', '--output', directory], { cwd: resolve('../backend'), encoding: 'utf8' });
  const expected = JSON.parse(readFileSync(resolve(directory, 'expected.json'), 'utf8'));
  const external: string[] = [], errors: string[] = [];
  page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
  page.on('pageerror', error => errors.push(error.message));
  await context.setOffline(true);
  async function load(name: string) {
    await page.goto(pathToFileURL(resolve(directory, name + '.html')).href); await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('[data-section]')).toHaveCount(6);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await load('filled');
  expect(await page.locator('.sheet > h2').allTextContents()).toEqual(expected.sections);
  await expect(page.locator('.card')).toHaveCount(4); await expect(page.locator('.scene')).toHaveCount(3);
  await expect(page.getByText('관찰 리포트', { exact: true })).toHaveCount(6);
  await expect(page.getByText('검토용 미리보기', { exact: true })).toHaveCount(0);
  const fear = page.locator('.survey-row').filter({ hasText: '낯선 사람 두려움' });
  await expect(fear.locator('.survey')).toHaveText('0'); expect(await fear.locator('.fill').evaluate(element => element.getBoundingClientRect().width)).toBe(0);
  await expect(fear).toContainText('0 ÷ 2');
  await expect(page.locator('[data-section="4"]')).toContainText('원응답 1 (1~5) / 역채점 5 (1~5)');
  await expect(page.locator('[data-section="4"]')).toContainText('-2');
  expect(await page.locator('.survey').first().evaluate(element => getComputedStyle(element).color)).toBe('rgb(201, 82, 60)');
  expect(await page.locator('.video').first().evaluate(element => getComputedStyle(element).color)).toBe('rgb(8, 127, 119)');
  expect(await page.evaluate(() => document.fonts.check('16px KDog'))).toBe(true);
  await page.locator('[data-section="1"]').screenshot({ path: testInfo.outputPath('report-desktop-cover.png') });
  await page.setViewportSize({ width: 360, height: 800 }); await load('filled');
  const cards = await page.locator('.card').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().x));
  expect(new Set(cards).size).toBe(1);
  for (let section = 1; section <= 6; section++) await page.locator(`[data-section="${section}"]`).screenshot({ path: testInfo.outputPath(`report-mobile-${section}.png`) });
  await load('missing'); await expect(page.locator('.fill')).toHaveCount(0); await expect(page.getByText(/직접 확인 과제 없음/).first()).toBeVisible();
  await load('images'); await expect(page.locator('img')).toHaveCount(expected.scenes);
  expect(await page.locator('img').evaluateAll(elements => elements.every(image => image.complete && image.naturalWidth > 0 && image.src.startsWith('data:')))).toBe(true);
  await load('escaped'); await expect(page.locator('h1')).toContainText(expected.unsafe_name); await expect(page.locator('script, [onerror], img')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { reportXss?: number }).reportXss)).toBeUndefined();
  await load('preview'); await expect(page.getByText('검토용 미리보기', { exact: true })).toHaveCount(6);
  await load('long'); await expect(page.getByText(new RegExp(expected.long_marker))).toHaveCount(2);
  expect(await page.locator('.sheet').evaluateAll(elements => elements.every(element => element.scrollHeight <= element.clientHeight + 1 && getComputedStyle(element).overflow !== 'hidden'))).toBe(true);
  expect(external).toEqual([]); expect(errors).toEqual([]);
});

test('S1 browser print keeps six baseline sections and continues long Korean without clipping', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  const directory = testInfo.outputPath('html');
  execFileSync('uv', ['run', '--locked', 'python', '-X', 'utf8', '-m', 'tests.build_report_preview_v4', '--output', directory], { cwd: resolve('../backend'), encoding: 'utf8' });
  await page.emulateMedia({ media: 'print' });
  for (const name of ['filled', 'missing', 'long']) {
    await page.goto(pathToFileURL(resolve(directory, name + '.html')).href); await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('.sheet')).toHaveCount(6);
    expect(await page.locator('.sheet').evaluateAll(elements => elements.every(element => element.scrollHeight <= element.clientHeight + 1 && getComputedStyle(element).overflow !== 'hidden'))).toBe(true);
    const pdf = await page.pdf({ path: testInfo.outputPath(`browser-${name}.pdf`), printBackground: true, preferCSSPageSize: true });
    const pages = pdf.toString('latin1').match(/\/Type \/Page\b/g)?.length ?? 0;
    if (name === 'long') expect(pages).toBeGreaterThan(6); else expect(pages).toBe(6);
  }
});
