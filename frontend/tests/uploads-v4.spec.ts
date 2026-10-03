import { test, expect } from '@playwright/test';

test('S1 파일 묶음의 부분 실패·응답 유실 재시도는 완료 수신물을 다시 전송하지 않는다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  const inbox = page.getByRole('region', { name: 'S1 영상 수신 보관함', exact: true });
  const names = ['partial-ok.mp4', 'partial-retry.mp4', 'partial-response-lost.mp4'];
  const transmissions: Record<string, number> = {};
  await page.route('**/api/uploads/*/content?*', async route => {
    const name = route.request().postDataBuffer()!.toString();
    transmissions[name] = (transmissions[name] ?? 0) + 1;
    if (name === names[1] && transmissions[name] === 1) return route.fulfill({ status: 503, json: { detail: '합성 일시 장애' } });
    if (name === names[2] && transmissions[name] === 1) { await route.fetch(); return route.abort('failed'); }
    await route.continue();
  });
  await inbox.getByLabel('수신 파일', { exact: true }).setInputFiles(names.map(name => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) })));
  const start = inbox.getByRole('button', { name: '파일 수신 시작·재시도', exact: true });
  await start.click();
  const queue = inbox.locator('.upload-queue');
  await expect(queue.getByRole('status').filter({ hasText: '수신 확인 필요' })).toHaveCount(2);
  await expect(start).toBeEnabled();
  expect(transmissions).toEqual(Object.fromEntries(names.map(name => [name, 1])));
  const received = (await (await page.request.get('/api/uploads')).json()).filter((value: { filename: string }) => names.includes(value.filename));
  expect(received).toHaveLength(3);
  expect(received.filter((value: { state: string }) => value.state === 'complete')).toHaveLength(2);
  await start.click();
  await expect(queue.getByRole('status').filter({ hasText: /^수신 완료$/ })).toHaveCount(3);
  expect(transmissions).toEqual({ [names[0]]: 1, [names[1]]: 2, [names[2]]: 1 });
  const retried = (await (await page.request.get('/api/uploads')).json()).filter((value: { filename: string }) => names.includes(value.filename));
  expect(retried).toHaveLength(3);
  expect(retried.every((value: { state: string }) => value.state === 'complete')).toBe(true);
  expect(retried.map((value: { upload_id: string }) => value.upload_id).sort()).toEqual(received.map((value: { upload_id: string }) => value.upload_id).sort());
  await page.reload();
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  for (const name of names) await expect(inbox.getByRole('article', { name: `수신물 ${name}`, exact: true }).getByText('수신 완료 · 연결 대기', { exact: true })).toBeVisible();
});

test('세 브라우저 수신·연결 충돌·재접속은 파일 재전송 없이 처리한다', async ({ page, browser }, testInfo) => {
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
      await client.getByLabel('수신 파일', { exact: true }).setInputFiles({ name: `three-browser-cam${i + 1}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic video camera ${i + 1}`) });
      await client.getByRole('button', { name: '파일 수신 시작·재시도', exact: true }).click();
      const card = client.getByRole('article', { name: `수신물 three-browser-cam${i + 1}.mp4`, exact: true });
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
    await Promise.all(pages.map((client, i) => client.getByRole('article', { name: `수신물 three-browser-cam${i + 1}.mp4`, exact: true }).getByRole('button', { name: '대상 연결·충돌 재시도' }).click()));
    const results = await Promise.all(responses);
    expect(results.map(result => result.status()).sort()).toEqual([200, 409, 409]);
    for (let i = 0; i < pages.length; i++) {
      await pages[i].unroute(`**/api/cases/${item.case_id}`);
      const card = pages[i].getByRole('article', { name: `수신물 three-browser-cam${i + 1}.mp4`, exact: true });
      if (results[i].status() === 409) {
        await expect(card.getByRole('alert')).toContainText('수신 완료 파일은 보관');
        const retried = pages[i].waitForResponse(response => response.url().includes('/api/uploads/') && response.url().endsWith('/link'));
        await card.getByRole('button', { name: '대상 연결·충돌 재시도' }).click();
        const linked = await retried; expect(linked.status(), await linked.text()).toBe(200);
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
    for (let i = 0; i < 3; i++) await expect(pages[0].getByRole('article', { name: `수신물 three-browser-cam${i + 1}.mp4`, exact: true }).getByText('대상 연결 완료', { exact: true })).toBeVisible();
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
