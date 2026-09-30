import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };

test('v3 recording: actual media, skip, transitions, conflict and reviewer', async ({ page }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20260929', 'Run with the current intake fixture.');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  let item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'V3-REC', participant_id: 'v3rec', dog_name: '신판 촬영 합성견' } })).json();
  const video = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc=size=96x64:rate=2:duration=100', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  item = await (await page.request.post(`/api/cases/${item.case_id}/videos`, { headers, params: { session_id: item.selected_session_id, expected_revision: item.input_revision, filename: 'synthetic-v3.mp4' }, data: video })).json();
  const endpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/recording`;
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  await page.getByRole('button', { name: 'v3rec 촬영 열기' }).click();
  const panel = page.getByLabel('신판 촬영 기록', { exact: true });
  await panel.getByLabel('기준 영상', { exact: true }).selectOption(item.manifest.sessions[0].videos[0].video_id);
  const labels = ['입장', '기준', '혼자', '재회', '무시', '걷기', '낯선 사람', '퇴장'];
  const spans = [[0, 10], [10, 20], [20, 30], [30, 40], [40, 50], [52, 64], [70, 80], [82, 92]];
  expect(await panel.locator('tbody select').allTextContents()).toHaveLength(8);
  for (const [i, label] of labels.entries()) {
    await expect(panel.getByLabel(`${label} 시작`, { exact: true })).toHaveValue('');
    await panel.getByLabel(`${label} 시작`, { exact: true }).fill(String(spans[i][0]));
    await panel.getByLabel(`${label} 끝`, { exact: true }).fill(String(spans[i][1]));
  }
  for (const [i, label] of ['이동1', '정지1', '이동2', '정지2', '이동3', '정지3'].entries()) {
    await panel.getByLabel(`${label} 시작`, { exact: true }).fill(String(52 + 2 * i));
    await panel.getByLabel(`${label} 끝`, { exact: true }).fill(String(54 + 2 * i));
  }
  await panel.getByLabel('추가할 사건', { exact: true }).selectOption('stranger_contact_start');
  await panel.getByLabel('사건 상태', { exact: true }).selectOption('not_occurred');
  await panel.getByLabel('실제 맥락·사유', { exact: true }).fill('요원이 접촉하지 않음');
  await panel.getByLabel('영향 항목', { exact: false }).fill('개53,보22');
  await expect(panel.getByLabel('실제 사건 초', { exact: true })).toHaveValue('');
  await panel.getByRole('button', { name: '촬영 기록 확정', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '실제 촬영 기록을 확정했습니다.' })).toBeVisible();
  await expect(panel.getByLabel('재회 시작', { exact: true })).toBeDisabled();
  await panel.getByRole('button', { name: '확정본 수정 시작', exact: true }).click();
  for (const label of ['혼자', '재회']) {
    await panel.getByLabel(`${label} 상태`, { exact: true }).selectOption('not_performed');
    await panel.getByLabel(`${label} 사유`, { exact: true }).fill('보호자 요청으로 분리·재회 생략');
    await expect(panel.getByLabel(`${label} 시작`, { exact: true })).toHaveValue('');
  }
  const skippedSave = page.waitForResponse(response => response.url().endsWith('/recording') && response.request().method() === 'PUT');
  await panel.getByRole('button', { name: '촬영 기록 확정', exact: true }).click();
  expect((await skippedSave).status()).toBe(200);
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeEnabled();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toBeDisabled();
  item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(item.manifest.sessions[0].recording.segments[2].start_sec).toBeNull();
  expect(item.manifest.sessions[0].recording.events[0].affected_codes).toEqual(['개53', '보22']);
  const cleanChange = structuredClone(item.manifest.sessions[0].recording);
  cleanChange.events[0].affected_codes = ['개53'];
  expect((await page.request.put(endpoint, { headers, data: { expected_revision: item.input_revision, recording: cleanChange, confirm: true } })).status()).toBe(200);
  await expect(panel.getByLabel('영향 항목', { exact: false })).toHaveValue('개53');
  item = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  await panel.getByRole('button', { name: '확정본 수정 시작', exact: true }).click();
  await panel.getByLabel('퇴장 끝', { exact: true }).fill('93');
  const alternate = structuredClone(item.manifest.sessions[0].recording);
  alternate.segments[7].end_sec = 94;
  expect((await page.request.put(endpoint, { headers, data: { expected_revision: item.input_revision, recording: alternate, confirm: true } })).status()).toBe(200);
  await expect(panel.getByText(/다른 변경이 저장되었습니다/)).toBeVisible();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toHaveValue('93');
  const conflict = page.waitForResponse(response => response.url().endsWith('/recording') && response.request().method() === 'PUT');
  await panel.getByRole('button', { name: '촬영 기록 초안 저장', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toHaveValue('93');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '전체 목록으로 돌아가기', exact: true }).click();
  await expect(panel).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '촬영 입력 버리고 최신 값 보기', exact: true }).click();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toHaveValue('94');
  await page.screenshot({ path: testInfo.outputPath('recording-v3.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.getByLabel('계정', { exact: true }).fill('reviewer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '촬영', exact: true }).click();
  await page.getByRole('button', { name: 'v3rec 촬영 열기' }).click();
  await expect(panel.getByLabel('퇴장 끝', { exact: true })).toBeDisabled();
  await expect(panel.getByRole('button', { name: '촬영 기록 확정', exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
