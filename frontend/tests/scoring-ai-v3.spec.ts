import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test('v3 AI settings and explicit queued run: no worker or real provider', async ({ page, request }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20260929', 'Current intake fixture required.');
  test.setTimeout(90000);
  const headers = { 'X-KDOG-Request': '1' }, password = 'Browser-test-only-42';
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  async function login(username: string) {
    await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username);
    await page.getByLabel('비밀번호', { exact: true }).fill(password);
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  }
  await login('developer');
  const settings = page.getByLabel('신판 AI 설정', { exact: true });
  await expect(settings).toContainText('기본 계획 37회');
  await settings.getByLabel('설정 항목군', { exact: true }).selectOption({ index: 1 });
  await settings.getByLabel('Provider 요청 fps', { exact: true }).fill('6');
  await settings.getByLabel('Q11 운영 AI 적용 범위를 확인한 설정', { exact: true }).check();
  await settings.getByRole('button', { name: '신판 초안 저장', exact: true }).click();
  await expect(settings.getByText('활성본과의 차이', { exact: false })).toBeVisible();
  await expect(settings.getByRole('button', { name: '이 신판 초안 활성화', exact: true })).toBeEnabled();
  await settings.getByRole('button', { name: '계약 시험', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'schema 합성 시험: schema_valid' })).toBeVisible();
  await settings.getByRole('button', { name: '이 신판 초안 활성화', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '신판 설정을 활성화했습니다.' })).toBeVisible();
  await settings.screenshot({ path: testInfo.outputPath('C07B-settings-desktop.png') });
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await settings.screenshot({ path: testInfo.outputPath('C07B-settings-360.png') });
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await request.post('/api/auth/login', { headers, data: { username: 'admin', password } });
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'AI-SYNTHETIC', participant_id: 'ai-fixture', dog_name: 'AI 계약 합성견', consents: { analysis_feedback: 'confirmed', stranger_contact: 'unknown' } } })).json();
  const source = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=c=gray:s=96x64:r=12:d=10', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  item = await (await request.post(`/api/cases/${item.case_id}/videos`, { headers, params: { session_id: item.selected_session_id, expected_revision: item.input_revision, filename: 'ai-fixture.mp4' }, data: source })).json();
  const path = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`, video_id = item.manifest.sessions[0].videos[0].video_id;
  const spans: [string, number, number][] = [['entry', 0, 1], ['baseline', 1, 2], ['alone', 2, 3], ['reunion', 3, 4], ['ignore', 4, 5], ['walk', 5.2, 6.4], ['stranger', 7, 8], ['exit', 8.2, 9.2]];
  item = await (await request.put(path + '/recording', { headers, data: { expected_revision: item.input_revision, confirm: true, recording: { video_id,
    segments: spans.map(([segment, start_sec, end_sec]) => ({ segment, video_id, start_sec, end_sec })),
    walk_phases: ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'].map((phase, i) => ({ phase, video_id, start_sec: Number((5.2 + i * .2).toFixed(1)), end_sec: Number((5.4 + i * .2).toFixed(1)) })) } } })).json();
  expect((await request.post(path + '/preprocess', { headers, data: { expected_revision: item.input_revision } })).status()).toBe(200);
  await login('operator');
  let creates = 0;
  page.on('request', req => { if (req.method() === 'POST' && req.url().endsWith('/runs-v3')) creates++; });
  await page.getByRole('button', { name: '독립 채점', exact: true }).click();
  await page.getByRole('button', { name: 'ai-fixture 독립 채점 열기', exact: true }).click();
  const runs = page.getByLabel('독립 AI 실행', { exact: true });
  await expect(runs.getByRole('button', { name: '현재 입력으로 AI 새 실행 생성', exact: true })).toBeEnabled();
  expect(creates).toBe(0);
  await runs.getByRole('button', { name: '현재 입력으로 AI 새 실행 생성', exact: true }).click();
  await expect(runs.getByRole('heading', { name: '접수됨', exact: true })).toBeVisible();
  expect(creates).toBe(1);
  await runs.getByRole('button', { name: '이 실행 중지', exact: true }).click();
  await expect(runs.getByRole('heading', { name: '중지', exact: true })).toBeVisible();
  await runs.getByRole('button', { name: '고정 입력으로 재시도', exact: true }).click();
  await expect(runs.getByRole('heading', { name: '접수됨', exact: true })).toBeVisible();
  expect(creates).toBe(1);
  await runs.screenshot({ path: testInfo.outputPath('C07B-run-360.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
