import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page, account = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(account);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}

test('S1 synthetic media: multi-camera output, actual frames, reuse, revision conflict and reviewer', async ({ page }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20261002', 'S1 browser fixture required');
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  let item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'S1-PREPROCESS', participant_id: 's1preprocess', dog_name: '전처리 합성견' } })).json();
  for (const [index, filter] of ['testsrc2', 'smptebars', 'testsrc'].entries()) {
    const bytes = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', `${filter}=size=64x64:rate=4:duration=6`,
      ...(index === 0 ? ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-c:a', 'aac'] : []),
      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
    const created = await page.request.post('/api/uploads', { headers, data: { request_id: `s1-preprocess-cam-${index}`, filename: `s1-preprocess-cam${index + 1}.mp4`, expected_size: bytes.length } });
    expect(created.status(), await created.text()).toBe(201);
    const receipt = await created.json();
    expect((await page.request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: bytes })).status()).toBe(200);
    expect((await page.request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: { case_id: item.case_id, session_id: item.selected_session_id, camera_id: `CAM${index + 1}`, expected_revision: item.input_revision } })).status()).toBe(200);
    item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  }
  const [one, two, three] = item.manifest.sessions[0].videos;
  const endpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/preprocess-s1`;
  const recordEndpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/recording-s1`;
  let recording = { video_id: one.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '합성 실제 구간·프레임 검증',
    segments: ['entry', 'baseline', 'alone', 'reunion', 'ignore', 'walk', 'stranger', 'exit'].map(segment => ({ segment, video_id: one.video_id,
      ...(segment === 'entry' ? { start_sec: 0, end_sec: 4 } : { state: 'not_performed', reason: '합성 시험에서 생략' }) })),
    video_offsets: [{ video_id: two.video_id, offset_seconds: 1, confirmed: true, note: '합성 오프셋 1초' },
      { video_id: three.video_id, offset_seconds: null as number | null, confirmed: false, note: '합성 미확인 카메라' }],
    coverage: [{ evidence_id: 'whole-one', window_id: 'entry_whole', video_id: one.video_id, start_seconds: 0, end_seconds: 4, observed_seconds: 4, coverage: 'whole', modality: 'visual', note: '합성 전체 확인' }],
    events: [
      { event_id: 'cover-one', kind: 'occlusion', video_id: one.video_id, segment: 'entry', status: 'observed', seconds: 1, end_seconds: 2, note: '합성 화면 가림', affected_codes: [] },
      { event_id: 'body-two', kind: 'body_not_visible', video_id: two.video_id, segment: 'entry', status: 'observed', seconds: 2, end_seconds: 3, note: '합성 신체 미관찰', affected_codes: [] },
      { event_id: 'audio-one', kind: 'audio_loss', video_id: one.video_id, segment: 'entry', status: 'observed', seconds: 1.5, end_seconds: 2, note: '합성 오디오 손실', affected_codes: [] },
    ] };
  const save = await page.request.put(recordEndpoint, { headers, data: { expected_revision: item.input_revision, recording } });
  expect(save.status(), await save.text()).toBe(200);
  item = await save.json();
  await page.getByRole('button', { name: '전처리', exact: true }).click();
  await page.getByRole('button', { name: 's1preprocess 전처리 열기' }).click();
  const panel = page.getByRole('region', { name: 'S1 다중 카메라 전처리', exact: true });
  const fresh = panel.getByRole('button', { name: '새 클립으로 전처리', exact: true });
  const reuse = panel.getByRole('button', { name: '검증된 결과 재사용', exact: true });
  await expect(fresh).toBeEnabled();
  await expect(reuse).toBeDisabled();
  const firstResponse = page.waitForResponse(response => response.url().endsWith('/preprocess-s1') && response.request().method() === 'POST');
  await fresh.click();
  const first = await firstResponse;
  expect(first.status(), await first.text()).toBe(200);
  const batch = await first.json();
  expect(batch.status).toBe('partial');
  expect(batch.clips).toHaveLength(2);
  await expect(panel.getByRole('heading', { name: '저장된 결과 · 일부만 완성', exact: true })).toBeVisible();
  const window = panel.getByLabel('입장 전체 전처리 결과', { exact: true });
  await window.locator('summary').click();
  await expect(window.getByText('오디오 손실: 1.5초 ~ 2초', { exact: true })).toBeVisible();
  await expect(window.getByText(/CAM1 · s1-preprocess-cam1.mp4 · 가용 시간이 긴 오디오 우선/)).toBeVisible();
  await expect(window.getByRole('row').filter({ hasText: 'CAM3 · s1-preprocess-cam3.mp4' })).toContainText('오프셋 미확인');
  await expect(window.getByText(/영상 있음 \/ 영상 가림/)).toBeVisible();
  await expect(window.getByText(/영상 있음 \/ 신체 미관찰/)).toBeVisible();
  await expect(window.getByText(/영상 가용 4초 · 대표 오디오 가용 3.5초/)).toBeVisible();
  await expect(window.getByText(/실제 청취·발성 초: 아직 판정하지 않음/)).toBeVisible();
  await panel.getByRole('combobox', { name: '클립 제작 방식', exact: true }).selectOption('ai');
  const preview = panel.getByRole('article', { name: '전처리 클립 미리보기', exact: true });
  await expect(preview.getByText(/AI용: 1초마다 실제 프레임 최대 1장 · 4프레임/)).toBeVisible();
  await expect.poll(() => preview.locator('video').evaluate((video: HTMLVideoElement) => video.readyState)).toBeGreaterThanOrEqual(1);
  await preview.getByLabel('확인할 실제 프레임 번호', { exact: true }).fill('3');
  await expect(preview.getByText(/클립 2초 → 원본 2초 → 기준 영상 2초/)).toBeVisible();
  const clipResponse = await page.request.get(await preview.locator('video').getAttribute('src') ?? '');
  expect(clipResponse.status()).toBe(200);
  expect(clipResponse.headers()['content-type']).toContain('video');
  await panel.getByRole('button', { name: 'CAM2 우선순위 올리기', exact: true }).click();
  await expect(reuse).toBeDisabled();
  await panel.getByRole('button', { name: '이 결과의 설정 불러오기', exact: true }).click();
  await expect(reuse).toBeEnabled();
  const secondResponse = page.waitForResponse(response => response.url().endsWith('/preprocess-s1') && response.request().method() === 'POST');
  await reuse.click();
  const second = await secondResponse;
  expect(second.status(), await second.text()).toBe(200);
  const reused = await second.json();
  expect(reused.batch_id).not.toBe(batch.batch_id);
  expect(reused.reuse_manifest).toBeTruthy();
  expect(reused.clips.map((value: { original: { hash: string } }) => value.original.hash)).toEqual(batch.clips.map((value: { original: { hash: string } }) => value.original.hash));
  await expect(panel.getByText('해시를 검증한 기존 결과를 명시적으로 재사용했습니다.', { exact: true })).toBeVisible();
  // Change the immutable input only after the browser has dispatched its old revision.
  await page.route(`**${endpoint}`, async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
    recording = { ...recording, video_offsets: recording.video_offsets.map(value => ({ ...value, confirmed: true, offset_seconds: value.offset_seconds ?? 0 })) };
    expect((await page.request.put(recordEndpoint, { headers, data: { expected_revision: item.input_revision, recording } })).status()).toBe(200);
    await route.continue();
  });
  const conflict = page.waitForResponse(response => response.url().endsWith('/preprocess-s1') && response.request().method() === 'POST');
  await fresh.click();
  expect((await conflict).status()).toBe(409);
  await expect(panel.getByRole('alert')).toContainText('상태와 최신 입력을 새로고침');
  await page.unroute(`**${endpoint}`);
  await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
  await expect(panel.getByText(/이전 입력 기준 결과입니다/)).toBeVisible();
  await expect(reuse).toBeDisabled();
  const finalResponse = page.waitForResponse(response => response.url().endsWith('/preprocess-s1') && response.request().method() === 'POST');
  await fresh.click();
  const final = await finalResponse;
  expect(final.status(), await final.text()).toBe(200);
  const completed = await final.json();
  expect(completed.status).toBe('complete');
  expect(completed.clips).toHaveLength(3);
  expect(completed.reuse_manifest).toBeNull();
  expect(completed.clips[0].original.ref).not.toBe(batch.clips[0].original.ref);
  await expect(panel.getByRole('heading', { name: '저장된 결과 · 완성', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('preprocess-s1.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 360, height: 800 });
  await panel.getByText('입력·원본·제작 출처 확인', { exact: true }).click();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'reviewer');
  await page.getByRole('button', { name: '전처리', exact: true }).click();
  await page.getByRole('button', { name: 's1preprocess 전처리 열기' }).click();
  await expect(panel.getByRole('heading', { name: '저장된 결과 · 완성', exact: true })).toBeVisible();
  await expect(fresh).toHaveCount(0);
  await expect(panel.getByRole('combobox', { name: '대표 오디오 선택', exact: true })).toBeDisabled();
  const denied = await page.request.post(endpoint, { headers, data: { request_id: 'reviewer-denied', expected_revision: completed.input_revision } });
  expect(denied.status()).toBe(403);
  expect(errors).toEqual([]);
});

test('S1 state refresh shows running, interrupted, failed and unavailable without polling', async ({ page }) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20261002', 'S1 browser fixture required');
  await login(page);
  const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'S1-PREPROCESS-STATE', participant_id: 's1state', dog_name: '상태 표시 합성견' } })).json();
  let current = 'running', count = 0;
  await page.route('**/preprocess-s1', route => {
    count++;
    if (current === 'error') return route.fulfill({ status: 503, json: { detail: '합성 상태 조회 실패' } });
    return route.fulfill({ json: { case_id: item.case_id, session_id: item.selected_session_id, input_revision: item.input_revision,
      ready: current !== 'not_ready', status: current, message: '합성 상태 검증', outdated: false, result_pointer: null, result: null } });
  });
  await page.getByRole('button', { name: '전처리', exact: true }).click();
  await page.getByRole('button', { name: 's1state 전처리 열기' }).click();
  const panel = page.getByRole('region', { name: 'S1 다중 카메라 전처리', exact: true });
  const start = panel.getByRole('button', { name: '새 클립으로 전처리', exact: true });
  await expect(panel.getByRole('status')).toContainText('진행 중');
  await expect(start).toBeDisabled();
  expect(count).toBe(1);
  for (const [state, label] of [['interrupted', '중단됨'], ['failed', '실패'], ['not_ready', '촬영 기록 확인 필요']]) {
    current = state;
    await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText(label);
    if (state === 'not_ready') await expect(start).toBeDisabled(); else await expect(start).toBeEnabled();
  }
  current = 'error';
  await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
  await expect(panel.getByRole('alert')).toHaveText('합성 상태 조회 실패');
  await expect(start).toBeDisabled();
  current = 'ready';
  await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
  await expect(start).toBeEnabled();
  await expect(panel.getByRole('alert')).toHaveCount(0);
});
