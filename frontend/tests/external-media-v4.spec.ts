import { test, expect, type Page } from '@playwright/test';
import { openMenu } from './menu';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page, account = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(account);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function prepare(page: Page, id: string) {
  await login(page);
  const created = await page.request.post('/api/cases', { headers, data: { event_id: 'MP02', participant_id: id, dog_name: '통합 합성견' } });
  expect(created.status()).toBe(201);
  await openMenu(page, '영상 파일 업로드');
  return created.json();
}

test('원본 없이 통합 MP4 하나를 등록·정정·새로고침하고 모바일에서 확인한다', async ({ page }, testInfo) => {
  const item = await prepare(page, 'MP02-SINGLE');
  let transmissions = 0;
  page.on('request', request => { if (request.method() === 'PUT' && request.url().includes('/content?request_id=')) transmissions++; });
  const inbox = page.getByRole('region', { name: '업로드 파일 목록' });
  await inbox.getByLabel('영상 파일 구분').selectOption('external_360_mp4');
  await expect(inbox.getByLabel('변환 부모 원본')).toHaveCount(0);
  await expect(inbox.getByLabel('영상 파일', { exact: true })).toHaveAttribute('accept', '.mp4');
  await expect(inbox.getByLabel('영상 파일', { exact: true })).not.toHaveAttribute('multiple');
  await page.screenshot({ path: testInfo.outputPath('mp02-option.png'), animations: 'disabled' });
  const name = '원본1-mp02-single-long-studio-export-filename-for-mobile-acceptance.mp4', data = Buffer.from('synthetic externally prepared MP4');
  await inbox.getByLabel('영상 파일', { exact: true }).setInputFiles({ name, mimeType: 'video/mp4', buffer: data });
  // New-file defaults must not reclassify the file already in the queue.
  await inbox.getByLabel('영상 파일 구분').selectOption('original');
  await inbox.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  let card = inbox.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });
  await expect(card.getByText('업로드 완료', { exact: true })).toBeVisible();
  await expect(card.getByLabel('촬영 카메라 번호')).toHaveCount(0);
  await expect(card.getByLabel('원본 번호', { exact: true })).toHaveCount(0);
  await card.getByLabel('참가자', { exact: true }).selectOption(item.case_id);
  await card.screenshot({ path: testInfo.outputPath('mp02-file-complete.png'), animations: 'disabled' });
  await card.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
  await inbox.getByText(/^정보 저장 완료한 파일/).click();
  await expect(card.getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
  const before = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  const video = before.manifest.sessions[0].videos[0];
  expect(video.source_kind).toBe('external_360_mp4');
  expect([video.camera_id, video.source_original_number, video.parents]).toEqual(['EXT360', null, []]);
  expect(video.external_processing.projection).toBe('unknown');
  const receipt = (await (await page.request.get('/api/uploads')).json()).find((value: { filename: string }) => value.filename === name);
  const downloaded = await page.request.get(`/api/uploads/${receipt.upload_id}/content`);
  expect(downloaded.status()).toBe(200); expect(await downloaded.body()).toEqual(data);
  await card.getByText('처리 정보 확인·정정', { exact: true }).click();
  await card.getByLabel('영상 배치').selectOption('flat');
  await card.getByLabel('촬영 시간', { exact: true }).selectOption('preserved');
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith('/external-processing'));
  await card.getByRole('button', { name: '처리 정보 저장', exact: true }).click();
  expect((await saved).status()).toBe(200);
  await expect(card.getByText(/^현재 입력/)).toContainText('일반 화면 · 촬영 시간 유지');
  await expect(card.getByText(/^업로드 당시:/)).toContainText('영상 배치 미확인');
  const after = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(after.input_revision).toBe(before.input_revision + 1);
  expect(after.manifest.sessions[0].videos[0].sha256).toBe(video.sha256);
  expect(after.manifest.sessions[0].videos[0].video_id).toBe(video.video_id);
  expect(transmissions).toBe(1);
  await page.reload(); await openMenu(page, '영상 파일 업로드');
  await inbox.getByText(/^정보 저장 완료한 파일/).click();
  card = inbox.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });
  await expect(card.getByText(/사용자 제공 외부 처리 정보/)).toContainText('일반 화면 · 촬영 시간 유지');
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(card.getByText('360 통합 영상', { exact: true }).first()).toBeVisible();
    const overflow = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: window.innerWidth,
      elements: Array.from(document.querySelectorAll('main *')).filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
        .slice(-8).map(element => ({ tag: element.tagName, class: element.className, text: element.textContent?.slice(0, 80), right: element.getBoundingClientRect().right })) }));
    expect(overflow.width <= overflow.viewport + 1, JSON.stringify(overflow)).toBe(true);
    await card.screenshot({ path: testInfo.outputPath(`mp02-registered-${width}.png`), animations: 'disabled' });
  }
  expect(await page.locator('main').innerText()).not.toContain('EXT360');
  await inbox.getByLabel('영상 파일 구분').selectOption('received_conversion');
  const parent = inbox.getByLabel('변환 부모 원본').locator('option').filter({ hasText: name });
  await expect(parent).toContainText('360 통합 영상');
  await expect(parent).not.toContainText('EXT360');
  expect(transmissions).toBe(1);
});

test('접수 응답 유실 뒤 옵션을 바꾸어도 최초 출처와 처리 정보로 재시도한다', async ({ page }) => {
  await prepare(page, 'MP02-RETRY');
  const inbox = page.getByRole('region', { name: '업로드 파일 목록' });
  await inbox.getByLabel('영상 파일 구분').selectOption('external_360_mp4');
  await inbox.getByLabel('영상 배치').selectOption('equirectangular');
  await inbox.getByLabel('촬영 시간', { exact: true }).selectOption('edited');
  const name = 'mp02-lost-response.mp4';
  await inbox.getByLabel('영상 파일', { exact: true }).setInputFiles({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) });
  const requests: Record<string, unknown>[] = [];
  await page.route('**/api/uploads', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) { await route.fetch(); return route.abort('failed'); }
    await route.continue();
  });
  const start = inbox.getByRole('button', { name: '업로드 시작·재시도', exact: true });
  await start.click();
  await expect(inbox.locator('.upload-queue').getByRole('status')).toHaveText('업로드 확인 필요');
  await inbox.getByLabel('영상 파일 구분').selectOption('received_conversion');
  await start.click();
  await expect(inbox.locator('.upload-queue').getByRole('status')).toHaveText('업로드 완료');
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
  const card = inbox.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });
  await expect(card.getByText('일반 화면으로 재구도한 MP4가 필요합니다.')).toBeVisible();
  await expect(card.getByText(/촬영 시각 대응을 확인해야 합니다/)).toBeVisible();
});

test('처리 정보 저장 충돌은 파일을 재전송하지 않고 최신 판본을 다시 확인한다', async ({ page }) => {
  const item = await prepare(page, 'MP02-CONFLICT');
  const inbox = page.getByRole('region', { name: '업로드 파일 목록' });
  await inbox.getByLabel('영상 파일 구분').selectOption('external_360_mp4');
  const name = 'mp02-conflict.mp4';
  await inbox.getByLabel('영상 파일', { exact: true }).setInputFiles({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) });
  await inbox.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  const card = inbox.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });
  await expect(card.getByText('업로드 완료', { exact: true })).toBeVisible();
  await card.getByLabel('참가자', { exact: true }).selectOption(item.case_id);
  await card.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
  await inbox.getByText(/^정보 저장 완료한 파일/).click();
  await card.getByText('처리 정보 확인·정정', { exact: true }).click();
  await card.getByLabel('영상 배치').selectOption('flat');
  const current = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  const video = current.manifest.sessions[0].videos[0];
  expect((await page.request.patch(`/api/cases/${item.case_id}/videos/${video.video_id}/external-processing`, { headers, data: {
    session_id: item.selected_session_id, expected_revision: current.input_revision,
    external_processing: { projection: 'equirectangular', timeline: 'preserved' },
  } })).status()).toBe(200);
  const conflict = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith('/external-processing'));
  await card.getByRole('button', { name: '처리 정보 저장', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await expect(card.getByRole('alert')).toBeVisible();
  await expect(card.getByRole('button', { name: '처리 정보 저장', exact: true })).toBeDisabled();
  page.once('dialog', dialog => dialog.accept());
  await card.getByRole('button', { name: '입력 버리고 최신 값 보기', exact: true }).click();
  await expect(card.getByLabel('영상 배치')).toHaveValue('equirectangular');
  await card.getByLabel('영상 배치').selectOption('flat');
  await card.getByRole('button', { name: '처리 정보 저장', exact: true }).click();
  await expect(card.getByRole('status')).toHaveCount(0);
  // Another operator changes the shared selected session while this editor is dirty.
  await card.getByLabel('영상 배치').selectOption('equirectangular');
  const latest = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect((await page.request.post(`/api/cases/${item.case_id}/sessions`, { headers, data: { expected_revision: latest.input_revision } })).status()).toBe(200);
  await expect(card.getByText(/선택 촬영 회차가 변경되었습니다. 입력은 보존 중입니다/)).toBeVisible();
  await expect(card.getByLabel('영상 배치')).toHaveValue('equirectangular');
  await expect(card.getByRole('status')).toContainText('처리 정보 · 저장 전');
  await expect(card.getByRole('button', { name: '처리 정보 저장', exact: true })).toBeDisabled();
  // Folding the completed list must also preserve the dirty editor.
  await inbox.getByText(/^정보 저장 완료한 파일/).click();
  await inbox.getByText(/^정보 저장 완료한 파일/).click();
  await expect(card.getByLabel('영상 배치')).toHaveValue('equirectangular');
  page.once('dialog', dialog => dialog.accept());
  await card.getByRole('button', { name: '입력 버리고 최신 값 보기', exact: true }).click();
  await expect(card.getByLabel('영상 배치')).toHaveValue('flat');
});

test('실제 합성 전처리는 미지원 통합본을 제외하고 정정 뒤에도 과거 실행의 정보를 보존한다', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  let item = await prepare(page, 'MP02-MIXED');
  for (const [index, filter] of ['testsrc2', 'smptebars'].entries()) {
    const bytes = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', `${filter}=size=64x64:rate=4:duration=6`,
      '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-c:a', 'aac', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
      '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
    const created = await page.request.post('/api/uploads', { headers, data: { request_id: `mp02-mixed-${index}`, filename: `mp02-mixed-${index}.mp4`,
      expected_size: bytes.length, ...(index === 1 ? { source_kind: 'external_360_mp4', external_processing: {} } : {}) } });
    expect(created.status()).toBe(201);
    const receipt = await created.json();
    expect((await page.request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: bytes })).status()).toBe(200);
    expect((await page.request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: {
      case_id: item.case_id, session_id: item.selected_session_id, camera_id: index === 1 ? 'EXT360' : 'CAM1', expected_revision: item.input_revision,
    } })).status()).toBe(200);
    item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  }
  const [normal, external] = item.manifest.sessions[0].videos;
  const recording = { video_id: external.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '합성 실제 시각',
    segments: ['entry', 'baseline', 'alone', 'reunion', 'ignore', 'walk', 'stranger', 'exit'].map(segment => ({ segment, video_id: external.video_id,
      ...(segment === 'entry' ? { start_sec: 0, end_sec: 4 } : { state: 'not_performed', reason: '합성 시험 생략' }) })) };
  const recordPath = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/recording-s1`;
  expect((await page.request.put(recordPath, { headers, data: { expected_revision: item.input_revision, recording } })).status()).toBe(422);
  const saved = await page.request.put(recordPath, { headers, data: { expected_revision: item.input_revision,
    recording: { ...recording, video_id: normal.video_id, segments: recording.segments.map(value => ({ ...value, video_id: normal.video_id })),
      video_offsets: [{ video_id: external.video_id, confirmed: false, offset_seconds: null, note: '미확인 목록' }] } } });
  expect(saved.status(), await saved.text()).toBe(200); item = await saved.json();
  expect((await page.request.post('/api/admin/users', { headers, data: { username: 'mp02-mixed', password: 'Browser-test-only-42', role: 'operator' } })).status()).toBe(201);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'mp02-mixed');
  await openMenu(page, '전처리');
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await page.getByRole('button', { name: 'MP02-MIXED 전처리 열기', exact: true }).click();
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  const endpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/preprocess-s1`;
  const completed = page.waitForResponse(response => response.url().endsWith(endpoint) && response.request().method() === 'POST');
  await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  const response = await completed; expect(response.status(), await response.text()).toBe(200);
  const batch = await response.json();
  expect(batch.status).toBe('partial'); expect(batch.clips).toHaveLength(1);
  expect(batch.clips[0].video_id).toBe(normal.video_id);
  const window = panel.getByLabel('입장 전체 전처리 결과', { exact: true });
  await window.locator('summary').click();
  const row = window.getByRole('row').filter({ hasText: '360 통합 영상 · mp02-mixed-1.mp4' });
  await expect(row).toContainText('영상 배치를 확인하세요');
  await expect(row).toContainText('촬영 시각 대응을 확인해야 합니다');
  let posts = 0; page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(endpoint)) posts++; });
  item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect((await page.request.patch(`/api/cases/${item.case_id}/videos/${external.video_id}/external-processing`, { headers, data: {
    session_id: item.selected_session_id, expected_revision: item.input_revision, external_processing: { projection: 'flat', timeline: 'preserved' },
  } })).status()).toBe(200);
  await expect(panel.getByText(/이전 입력 기준 결과입니다/)).toBeVisible();
  await expect(panel.locator('article').filter({ hasText: '현재 입력 · 360 통합 영상' })).toContainText('일반 화면 · 촬영 시간 유지');
  await expect(panel.locator('article').filter({ hasText: '이 결과의 처리 정보 · 360 통합 영상' })).toContainText('영상 배치 미확인 · 촬영 시각 대응 미확인');
  await expect(panel.getByRole('button', { name: '검증된 결과 재사용', exact: true })).toBeDisabled();
  expect(posts).toBe(0);
  expect(await page.locator('main').innerText()).not.toContain('EXT360');
  for (const width of [1366, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.screenshot({ path: testInfo.outputPath(`mp02-preprocess-${width}.png`), fullPage: true, animations: 'disabled' });
  }
});
