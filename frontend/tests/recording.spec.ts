import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };

test('촬영 menu: several files with a partial failure, eight segment times, order check, confirm and lock', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  await page.request.post('/api/cases', { headers, data: { event_id: 'REC-TEST', participant_id: '0021', dog_name: '촬영 검증견', sequence_no: 21 } });
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  await expect(page.getByRole('heading', { name: '촬영', exact: true })).toBeVisible();
  const row = page.getByRole('row', { name: /0021/ });
  await expect(row.getByRole('cell', { name: '없음', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '0021 촬영 열기' }).click();
  const panel = page.getByLabel('촬영 자료');
  let failed = false;
  await page.route('**/api/cases/*/videos?*', async route => {
    const name = new URL(route.request().url()).searchParams.get('filename')!;
    if (name === 'second.mp4' && !failed) { failed = true; await route.fulfill({ status: 503, json: { detail: '합성 일시 장애' } }); }
    else await route.continue();
  });
  await panel.getByLabel('영상 파일', { exact: true }).setInputFiles(['first.mp4', 'second.mp4', 'third.mp4'].map(name => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) })));
  await panel.getByRole('button', { name: '영상 등록', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1개 저장 · 1개 실패 · 1개 대기' })).toBeVisible();
  await panel.getByRole('button', { name: '영상 등록', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '3개 저장 · 0개 실패 · 0개 대기' })).toBeVisible();
  await expect(panel.getByText('3 FILES', { exact: true })).toBeVisible();
  await expect(panel.getByText('카메라', { exact: false })).toHaveCount(0);
  await panel.getByLabel('구간 기준 영상').nth(1).check();
  const order = ['입장', '기준', '혼자', '낯선 사람', '재회', '무시', '걷기', '퇴장'];
  for (const [i, label] of order.entries()) {
    await panel.getByLabel(`${label} 시작`, { exact: true }).fill(`${Math.floor(i * 20 / 60)}:${String(i * 20 % 60).padStart(2, '0')}`);
    await panel.getByLabel(`${label} 끝`, { exact: true }).fill(`${Math.floor((i * 20 + 15) / 60)}:${String((i * 20 + 15) % 60).padStart(2, '0')}`);
  }
  await panel.getByLabel('기준 끝', { exact: true }).fill('0:45');  // overlaps 혼자 0:40
  await panel.getByRole('button', { name: '초안 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('8구간은 절차 순서대로');
  await panel.getByLabel('기준 끝', { exact: true }).fill('0:35');
  await panel.getByRole('button', { name: '초안 저장', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '초안으로 저장했습니다' })).toBeVisible();
  await expect(row.getByRole('cell', { name: '초안', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '8구간 확정', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '확정했습니다' })).toBeVisible();
  await expect(row.getByRole('cell', { name: '확정', exact: true })).toBeVisible();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toBeDisabled();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toHaveValue('2:35.0');
  await page.screenshot({ path: testInfo.outputPath('recording-confirmed.png'), fullPage: true, animations: 'disabled' });
  await page.reload();
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  await page.getByRole('button', { name: '0021 촬영 열기' }).click();
  await expect(page.getByLabel('촬영 자료').getByLabel('입장 시작', { exact: true })).toBeDisabled();
  await page.getByLabel('촬영 자료').getByRole('button', { name: '확정 해제 후 수정' }).click();
  await expect(page.getByLabel('촬영 자료').getByLabel('입장 시작', { exact: true })).toBeEnabled();
  const item = (await (await page.request.get('/api/cases')).json()).find((c: { participant_id: string }) => c.participant_id === '0021');
  expect(item.manifest.sessions[0].segments.confirmed).toBe(true);
  expect(item.manifest.sessions[0].segments.windows[7]).toEqual({ segment: 'exit', start_sec: 140, end_sec: 155 });
  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
