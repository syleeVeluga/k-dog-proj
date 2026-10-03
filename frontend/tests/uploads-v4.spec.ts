import { test, expect } from '@playwright/test';

test('세 브라우저 수신·연결 충돌·재접속은 파일 재전송 없이 처리한다', async ({ page, browser }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20261002', 'S1 browser fixture required');
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('admin');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const headers = { 'X-KDOG-Request': '1' };
  const users = ['upload-a', 'upload-b', 'upload-c'];
  for (const username of users) {
    const response = await page.request.post('/api/admin/users', { headers, data: { username, password: 'Browser-test-only-42', role: 'operator' } });
    expect(response.status()).toBe(201);
  }
  const created = await page.request.post('/api/cases', { headers, data: { event_id: 'UPLOAD-S1', participant_id: '3PC-001', dog_name: '동시 수신 합성견' } });
  const item = await created.json();
  expect(created.status()).toBe(201);
  const contexts = await Promise.all(users.map(() => browser.newContext()));
  const pages = await Promise.all(contexts.map(context => context.newPage()));
  const errors: string[] = []; let transmissions = 0;
  try {
    await Promise.all(pages.map(async (client, i) => {
      client.on('pageerror', error => errors.push(error.message));
      client.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/content?request_id=')) transmissions++; });
      await client.goto('/');
      await client.getByLabel('계정', { exact: true }).fill(users[i]);
      await client.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
      await client.getByRole('button', { name: '로그인', exact: true }).click();
      await expect(client.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
      await client.getByRole('button', { name: '촬영', exact: true }).click();
      await client.getByLabel('수신 파일', { exact: true }).setInputFiles({ name: `synthetic-cam${i + 1}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic video camera ${i + 1}`) });
      await client.getByRole('button', { name: '파일 수신 시작·재시도', exact: true }).click();
      const card = client.getByRole('article', { name: `수신물 synthetic-cam${i + 1}.mp4`, exact: true });
      await expect(card.getByText('수신 완료 · 연결 대기', { exact: true })).toBeVisible();
      await card.getByLabel('연결 참가자', { exact: true }).selectOption(item.case_id);
      await card.getByLabel('카메라 ID', { exact: true }).fill(`CAM${i + 1}`);
    }));
    expect(transmissions).toBe(3);
    // Hold three real GET responses until all PCs have read the same revision.
    let reads = 0; let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    for (const client of pages) await client.route(`**/api/cases/${item.case_id}`, async route => {
      const response = await route.fetch(); reads++; if (reads === 3) release(); await barrier; await route.fulfill({ response });
    });
    const responses = pages.map(client => client.waitForResponse(response => response.url().includes('/api/uploads/') && response.url().endsWith('/link')));
    await Promise.all(pages.map((client, i) => client.getByRole('article', { name: `수신물 synthetic-cam${i + 1}.mp4`, exact: true }).getByRole('button', { name: '대상 연결·충돌 재시도' }).click()));
    const results = await Promise.all(responses);
    expect(results.map(result => result.status()).sort()).toEqual([200, 409, 409]);
    for (let i = 0; i < pages.length; i++) {
      await pages[i].unroute(`**/api/cases/${item.case_id}`);
      const card = pages[i].getByRole('article', { name: `수신물 synthetic-cam${i + 1}.mp4`, exact: true });
      if (results[i].status() === 409) {
        await expect(card.getByRole('alert')).toContainText('수신 완료 파일은 보관');
        await card.getByRole('button', { name: '대상 연결·충돌 재시도' }).click();
      }
      await expect(card.getByText('대상 연결 완료', { exact: true })).toBeVisible();
    }
    expect(transmissions).toBe(3);
    const current = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
    const videos = current.manifest.sessions[0].videos;
    expect(videos).toHaveLength(3);
    expect(Object.fromEntries(videos.map((video: { camera_id: string; source_original_number: string }) => [video.camera_id, video.source_original_number]))).toEqual({ CAM1: '1', CAM2: '3', CAM3: '2' });
    await pages[0].reload();
    await pages[0].getByRole('button', { name: '촬영', exact: true }).click();
    await expect(pages[0].getByText('대상 연결 완료', { exact: true })).toHaveCount(3);
    expect(transmissions).toBe(3);
    await pages[0].getByLabel('수신 파일', { exact: true }).setInputFiles({ name: 'synthetic-source.insv', mimeType: 'application/octet-stream', buffer: Buffer.from('synthetic INSV storage only') });
    await pages[0].getByRole('button', { name: '파일 수신 시작·재시도', exact: true }).click();
    const insv = pages[0].getByRole('article', { name: '수신물 synthetic-source.insv', exact: true });
    await expect(insv.getByText(/INSV 원본 보관 전용/)).toBeVisible();
    await expect(insv.getByRole('link', { name: '보관 원본 내려받기' })).toBeVisible();
    await pages[0].screenshot({ path: testInfo.outputPath('three-browser-uploads.png'), animations: 'disabled' });
    expect(errors).toEqual([]);
  } finally { await Promise.allSettled(contexts.map(context => context.close())); }
});
