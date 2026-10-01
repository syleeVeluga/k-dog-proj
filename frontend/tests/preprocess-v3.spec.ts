import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };

test('v3 preprocessing: skipped windows, original frames, audio and immutable retry', async ({ page }, testInfo) => {
  test.setTimeout(60000);
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20260929', 'Run with the current intake fixture.');
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeEnabled();
  let item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'V3-PRE', participant_id: 'v3pre', dog_name: '신판 전처리 합성견' } })).json();
  const source = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc=size=96x64:rate=12:duration=10', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  item = await (await page.request.post(`/api/cases/${item.case_id}/videos`, { headers, params: { session_id: item.selected_session_id, expected_revision: item.input_revision, filename: 'synthetic-v3-pre.mp4' }, data: source })).json();
  const endpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const videoId = item.manifest.sessions[0].videos[0].video_id;
  const spans: [string, number | null, number | null][] = [['entry', 0, 1], ['baseline', 1, 2], ['alone', null, null], ['reunion', null, null], ['ignore', 2, 3], ['walk', 3.2, 4.4], ['stranger', 5, 7], ['exit', 7.2, 8.2]];
  const recording = { video_id: videoId, segments: spans.map(([segment, start_sec, end_sec]) => ({ segment, video_id: videoId, start_sec, end_sec, state: start_sec === null ? 'not_performed' : 'performed', reason: start_sec === null ? '보호자 요청 분리 생략' : null })),
    walk_phases: ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'].map((phase, i) => ({ phase, video_id: videoId, start_sec: Number((3.2 + .2 * i).toFixed(1)), end_sec: Number((3.4 + .2 * i).toFixed(1)) })),
    events: [{ event_id: 'no-contact', kind: 'stranger_contact_start', video_id: videoId, segment: 'stranger', status: 'not_occurred', seconds: null, note: '접촉하지 않음' }] };
  item = await (await page.request.put(endpoint + '/recording', { headers, data: { expected_revision: item.input_revision, recording, confirm: true } })).json();
  await page.getByRole('button', { name: '전처리', exact: true }).click();
  await page.getByRole('button', { name: 'v3pre 전처리 열기', exact: true }).click();
  const panel = page.getByLabel('전처리 상태', { exact: true });
  await expect(panel.getByText('항목별 관찰창과 제외 사유', { exact: true })).toBeVisible();
  await expect(panel.getByText('재회 실제 접촉', { exact: false })).toContainText('미실시');
  await expect(panel.getByText('요원 실제 접촉', { exact: false })).toContainText('기회 없음');
  await expect(panel.getByText('원본 프레임/속도 · 연속 영상·오디오 유지', { exact: false })).toBeVisible();
  await panel.getByRole('button', { name: '이 촬영 전처리 시작', exact: true }).click();
  await expect(panel.getByRole('heading', { name: /완료된 결과/ })).toBeVisible({ timeout: 30000 });
  const first = await (await page.request.get(endpoint + '/preprocess')).json();
  expect(first.result.clips.every((clip: { fps: string; audio_status: string; end_sec: number; start_sec: number }) => clip.fps === '12/1' && clip.audio_status === 'present' && clip.end_sec > clip.start_sec)).toBe(true);
  expect(first.result.windows.find((window: { window_id: string }) => window.window_id === 'stranger_contact').clip_names).toEqual([]);
  await expect(panel.getByText(/청취\/발성 미평가/).first()).toBeVisible();
  await panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true }).click();
  await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true })).toBeEnabled({ timeout: 30000 });
  const second = await (await page.request.get(endpoint + '/preprocess')).json();
  expect(second.result.batch_id).not.toBe(first.result.batch_id);
  await page.route('**' + endpoint + '/preprocess', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { ...second, status: 'failed', result: null, ready: true, message: '전처리 클립 해시가 다릅니다. 다시 전처리하세요.' } });
    } else {
      await route.continue();
    }
  });
  await expect(panel.getByText('전처리 클립 해시가 다릅니다. 다시 전처리하세요.', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true })).toBeEnabled();
  await page.unroute('**' + endpoint + '/preprocess');
  await panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true }).click();
  await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true })).toBeEnabled({ timeout: 30000 });
  await expect(panel.getByRole('heading', { name: /완료된 결과/ })).toBeVisible({ timeout: 30000 });
  const recovered = await (await page.request.get(endpoint + '/preprocess')).json();
  expect(recovered.result.batch_id).not.toBe(second.result.batch_id);
  const shortRecording = { ...recording, events: [
    { event_id: 'actual-contact-start', kind: 'stranger_contact_start', video_id: videoId, segment: 'stranger', status: 'observed', seconds: 5.001, note: '실제 짧은 접촉 시작' },
    { event_id: 'actual-contact-end', kind: 'stranger_contact_end', video_id: videoId, segment: 'stranger', status: 'observed', seconds: 5.002, note: '실제 짧은 접촉 끝' },
  ] };
  item = await (await page.request.put(endpoint + '/recording', { headers, data: { expected_revision: item.input_revision, recording: shortRecording, confirm: true } })).json();
  await expect(panel.getByText('이전 입력 기준 결과입니다.', { exact: false })).toBeVisible();
  await panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true }).click();
  await expect(panel.getByText('현재 완료 결과의 관찰창 상태입니다.', { exact: true })).toBeVisible({ timeout: 30000 });
  await expect(panel.getByText('요원 실제 접촉', { exact: false })).toContainText('미관찰');
  await expect(panel.getByText('요원 실제 접촉', { exact: false })).toContainText('영상 프레임이 없습니다');
  await page.screenshot({ path: testInfo.outputPath('preprocess-v3-no-frame.png'), fullPage: true, animations: 'disabled' });
  recording.segments[7].end_sec = 8.3;
  expect((await page.request.put(endpoint + '/recording', { headers, data: { expected_revision: item.input_revision, recording, confirm: true } })).status()).toBe(200);
  await expect(panel.getByText('이전 입력 기준 결과입니다.', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('preprocess-v3.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.getByLabel('계정', { exact: true }).fill('reviewer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '전처리', exact: true }).click();
  await page.getByRole('button', { name: 'v3pre 전처리 열기', exact: true }).click();
  await expect(panel.getByText('교수/검토자는 상태와 결과만 조회합니다.', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: '이 촬영 전처리 다시 시작', exact: true })).toHaveCount(0);
});
