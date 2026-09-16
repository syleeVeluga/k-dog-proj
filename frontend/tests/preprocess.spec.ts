import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };
test('명시적 전처리 시작과 재시도, 교수 조회 및 이전 입력 표시', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  let item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'PRE', participant_id: 'manual', dog_name: '전처리합성견' } })).json();
  try {
    const video = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc=size=160x120:rate=12:duration=8', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
    item = await (await page.request.post(`/api/cases/${item.case_id}/videos?session_id=${item.selected_session_id}&filename=synthetic.mp4&expected_revision=${item.input_revision}`, { headers, data: video })).json();
    const segmentData = { video_id: item.manifest.sessions[0].videos[0].video_id, confirm: true, windows: ['entry', 'baseline', 'alone', 'stranger', 'reunion', 'ignore', 'walk', 'exit'].map((segment, i) => ({ segment, start_sec: i, end_sec: i + 1 })) };
    item = await (await page.request.put(`/api/cases/${item.case_id}/sessions/${item.selected_session_id}/segments`, { headers, data: { ...segmentData, expected_revision: item.input_revision } })).json();
    let requests = 0;
    page.on('request', request => { if (request.url().endsWith('/preprocess') && request.method() === 'POST') requests++; });
    await page.getByRole('button', { name: '전처리', exact: true }).click();
    await page.getByRole('button', { name: 'manual 전처리 열기' }).click();
    const panel = page.getByLabel('전처리 상태', { exact: true });
    await expect(panel).toContainText('실행 가능합니다');
    expect(requests).toBe(0);
    await panel.getByRole('button', { name: '이 촬영 전처리 시작', exact: true }).click();
    await expect(panel.getByRole('heading', { name: '완료된 결과 8개' })).toBeVisible({ timeout: 30000 });
    await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작' })).toBeEnabled();
    expect(requests).toBe(1);
    await panel.getByRole('button', { name: '이 촬영 전처리 다시 시작' }).click();
    await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작' })).toBeEnabled({ timeout: 30000 });
    expect(requests).toBe(2);
    item = await (await page.request.put(`/api/cases/${item.case_id}/sessions/${item.selected_session_id}/segments`, { headers, data: { ...segmentData, expected_revision: item.input_revision, confirm: false } })).json();
    await expect(panel).toContainText('이전 입력 기준 결과');
    await page.getByRole('button', { name: '로그아웃' }).click();
    await page.getByLabel('계정', { exact: true }).fill('reviewer');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await page.getByRole('button', { name: '전처리', exact: true }).click();
    await page.getByRole('button', { name: 'manual 전처리 열기' }).click();
    await expect(panel).toContainText('교수/검토자는 상태와 결과만 조회');
    await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작' })).toHaveCount(0);
    await page.setViewportSize({ width: 768, height: 1024 });
    await panel.getByText('관리 정보 · 파일 참조와 해시', { exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('preprocess-reviewer-768.png'), fullPage: true });
  } finally {
    await page.request.post('/api/auth/login', { headers, data: { username: 'operator', password: 'Browser-test-only-42' } });
    item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  }
});
