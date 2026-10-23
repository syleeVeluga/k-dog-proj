import { test, expect } from '@playwright/test';
import { openMenu } from './menu';

test('녹화 도구의 4개 MKV 파일명으로 카메라를 제안하고 원본 번호 1/3/2/null로 연결한다', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const created = await page.request.post('/api/cases', { headers: { 'X-KDOG-Request': '1' }, data: { event_id: 'VC02', participant_id: 'FOUR-CAMERAS', dog_name: '합성4카메라견' } });
  expect(created.status()).toBe(201);
  const item = await created.json();
  await page.reload();
  await openMenu(page, '영상 파일 업로드');
  await page.getByRole('button', { name: '공용 업로드 보관함 열기', exact: true }).click();
  const names = ['6_CAM1_복도-정면.mkv', '6_CAM2_테스트룸-입구.mkv', '6_CAM3_참여자-왼쪽.mkv', '6_CAM4_참여자-오른쪽.mkv'];
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles(names.map(name => ({ name, mimeType: 'video/x-matroska', buffer: Buffer.from(`synthetic ${name}`) })));
  await page.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  for (const [index, name] of names.entries()) {
    const card = page.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });
    await expect(card.getByText('업로드 완료', { exact: true })).toBeVisible();
    await expect(card.getByLabel('촬영 카메라 번호', { exact: true })).toHaveValue(String(index + 1));
    await expect(card.getByLabel('원본 번호', { exact: true })).toHaveValue('');
    if (index === 3) await expect(card.getByLabel('원본 번호', { exact: true })).toHaveAttribute('placeholder', '없음');
    await card.getByLabel('참가자', { exact: true }).selectOption(item.case_id);
    const saved = page.waitForResponse(response => response.request().method() === 'POST' && /\/uploads\/[^/]+\/link$/.test(response.url()));
    await card.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
    expect((await saved).status()).toBe(200);
  }
  const current = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(current.manifest.sessions[0].videos.map((video: { camera_id: string; source_original_number: string | null }) => [video.camera_id, video.source_original_number])).toEqual([['CAM1', '1'], ['CAM2', '3'], ['CAM3', '2'], ['CAM4', null]]);
  await page.getByText(/^정보 저장 완료한 파일/).click();
  await expect(page.getByRole('article', { name: `업로드 파일 ${names[3]}`, exact: true }).getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
  await page.getByRole('article', { name: `업로드 파일 ${names[3]}`, exact: true }).screenshot({ path: testInfo.outputPath('four-camera-uploads.png'), animations: 'disabled' });
});

test('S1 파일 묶음의 부분 실패·응답 유실 재시도는 완료 업로드 파일을 다시 전송하지 않는다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await openMenu(page, '영상 파일 업로드');
  await page.getByRole('button', { name: '공용 업로드 보관함 열기', exact: true }).click();
  const inbox = page.getByRole('region', { name: '업로드 파일 목록', exact: true });
  const names = ['partial-ok.mp4', 'partial-retry.mp4', 'partial-response-lost.mp4'];
  const transmissions: Record<string, number> = {};
  await page.route('**/api/uploads/*/content?*', async route => {
    const name = route.request().postDataBuffer()!.toString();
    transmissions[name] = (transmissions[name] ?? 0) + 1;
    if (name === names[1] && transmissions[name] === 1) return route.fulfill({ status: 503, json: { detail: '합성 일시 장애' } });
    if (name === names[2] && transmissions[name] === 1) { await route.fetch(); return route.abort('failed'); }
    await route.continue();
  });
  await inbox.getByLabel('영상 파일', { exact: true }).setInputFiles(names.map(name => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) })));
  const start = inbox.getByRole('button', { name: '업로드 시작·재시도', exact: true });
  await start.click();
  const queue = inbox.locator('.upload-queue');
  await expect(queue.getByRole('status').filter({ hasText: '업로드 확인 필요' })).toHaveCount(2);
  await expect(start).toBeEnabled();
  expect(transmissions).toEqual(Object.fromEntries(names.map(name => [name, 1])));
  const received = (await (await page.request.get('/api/uploads')).json()).filter((value: { filename: string }) => names.includes(value.filename));
  expect(received).toHaveLength(3);
  expect(received.filter((value: { state: string }) => value.state === 'complete')).toHaveLength(2);
  await start.click();
  await expect(queue.getByRole('status').filter({ hasText: /^업로드 완료$/ })).toHaveCount(3);
  expect(transmissions).toEqual({ [names[0]]: 1, [names[1]]: 2, [names[2]]: 1 });
  const retried = (await (await page.request.get('/api/uploads')).json()).filter((value: { filename: string }) => names.includes(value.filename));
  expect(retried).toHaveLength(3);
  expect(retried.every((value: { state: string }) => value.state === 'complete')).toBe(true);
  expect(retried.map((value: { upload_id: string }) => value.upload_id).sort()).toEqual(received.map((value: { upload_id: string }) => value.upload_id).sort());
  await page.reload();
  await openMenu(page, '영상 파일 업로드');
  await page.getByRole('button', { name: '공용 업로드 보관함 열기', exact: true }).click();
  for (const name of names) await expect(inbox.getByRole('article', { name: `업로드 파일 ${name}`, exact: true }).getByText('업로드 완료', { exact: true })).toBeVisible();
});

test('세 브라우저 업로드·연결 충돌·재접속은 파일 재전송 없이 처리한다', async ({ page, browser }, testInfo) => {
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
      await openMenu(client, '영상 파일 업로드');
  await client.getByRole('button', { name: '공용 업로드 보관함 열기', exact: true }).click();
      await client.getByLabel('영상 파일', { exact: true }).setInputFiles({ name: `three-browser-cam${i + 1}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic video camera ${i + 1}`) });
      await client.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
      const card = client.getByRole('article', { name: `업로드 파일 three-browser-cam${i + 1}.mp4`, exact: true });
      await expect(card.getByText('업로드 완료', { exact: true })).toBeVisible();
      await card.getByLabel('참가자', { exact: true }).selectOption(item.case_id);
      await card.getByLabel('촬영 카메라 번호', { exact: true }).fill(`${i + 1}`);
    }));
    expect(transmissions).toBe(3);
    // Hold three real GET responses until all PCs have read the same revision.
    let reads = 0; let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    for (const client of pages) await client.route(`**/api/cases/${item.case_id}`, async route => {
      const response = await route.fetch(); reads++; if (reads === 3) release(); await barrier; await route.fulfill({ response });
    });
    const responses = pages.map(client => client.waitForResponse(response => response.url().includes('/api/uploads/') && response.url().endsWith('/link')));
    await Promise.all(pages.map((client, i) => client.getByRole('article', { name: `업로드 파일 three-browser-cam${i + 1}.mp4`, exact: true }).getByRole('button', { name: '영상 정보 저장', exact: true }).click()));
    const results = await Promise.all(responses);
    expect(results.map(result => result.status()).sort()).toEqual([200, 409, 409]);
    for (let i = 0; i < pages.length; i++) {
      await pages[i].unroute(`**/api/cases/${item.case_id}`);
      const card = pages[i].getByRole('article', { name: `업로드 파일 three-browser-cam${i + 1}.mp4`, exact: true });
      if (results[i].status() === 409) {
        await expect(card.getByRole('alert')).toContainText('업로드 완료 파일은 보관');
        const retried = pages[i].waitForResponse(response => response.url().includes('/api/uploads/') && response.url().endsWith('/link'));
        await expect(card.getByRole('button', { name: '다시 저장', exact: true })).toBeVisible();
        await card.getByRole('button', { name: '다시 저장', exact: true }).click();
        const linked = await retried; expect(linked.status(), await linked.text()).toBe(200);
      }
      await pages[i].getByText(/^정보 저장 완료한 파일/).click();
      await expect(card.getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
    }
    expect(transmissions).toBe(3);
    const current = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
    const videos = current.manifest.sessions[0].videos;
    expect(videos).toHaveLength(3);
    expect(Object.fromEntries(videos.map((video: { camera_id: string; source_original_number: string }) => [video.camera_id, video.source_original_number]))).toEqual({ CAM1: '1', CAM2: '3', CAM3: '2' });
    await pages[0].reload();
    await openMenu(pages[0], '영상 파일 업로드');
  await pages[0].getByRole('button', { name: '공용 업로드 보관함 열기', exact: true }).click();
    await pages[0].getByText(/^정보 저장 완료한 파일/).click();
    for (let i = 0; i < 3; i++) await expect(pages[0].getByRole('article', { name: `업로드 파일 three-browser-cam${i + 1}.mp4`, exact: true }).getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
    expect(transmissions).toBe(3);
    await pages[0].screenshot({ path: testInfo.outputPath('three-browser-uploads.png'), animations: 'disabled' });
    expect(errors).toEqual([]);
  } finally { await Promise.allSettled(contexts.map(context => context.close())); }
});
