import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };
const password = 'Browser-test-only-42';

test('v3 independent scoring: assignments, source windows, lock, exposure and conflict', async ({ page, request, browser }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20260929', 'Run with the current intake fixture.');
  test.setTimeout(90000);
  await request.post('/api/auth/login', { headers, data: { username: 'admin', password } });
  expect((await request.post('/api/admin/users', { headers, data: { username: 'reviewer2', password, role: 'reviewer' } })).status()).toBe(201);
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'V3-SHEET', participant_id: 'v3sheet', dog_name: '독립 채점 합성견' } })).json();
  const source = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc=size=96x64:rate=12:duration=10', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=10', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  item = await (await request.post(`/api/cases/${item.case_id}/videos`, { headers, params: { session_id: item.selected_session_id, expected_revision: item.input_revision, filename: 'synthetic-sheets.mp4' }, data: source })).json();
  const endpoint = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const videoId = item.manifest.sessions[0].videos[0].video_id;
  const spans: [string, number | null, number | null][] = [['entry', 0, 1], ['baseline', 1, 2], ['alone', null, null], ['reunion', null, null], ['ignore', 2, 3], ['walk', 3.2, 4.4], ['stranger', 5, 7], ['exit', 7.2, 8.2]];
  const recording = { video_id: videoId, segments: spans.map(([segment, start_sec, end_sec]) => ({ segment, video_id: videoId, start_sec, end_sec, state: start_sec === null ? 'not_performed' : 'performed', reason: start_sec === null ? '분리 요청 없음' : null })),
    walk_phases: ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'].map((phase, i) => ({ phase, video_id: videoId, start_sec: Number((3.2 + .2 * i).toFixed(1)), end_sec: Number((3.4 + .2 * i).toFixed(1)) })),
    events: [{ event_id: 'object-stop', kind: 'object_stop', video_id: videoId, segment: 'entry', status: 'observed', seconds: .2, end_seconds: .4, note: '합성 실제 정지' }] };
  item = await (await request.put(endpoint + '/recording', { headers, data: { expected_revision: item.input_revision, recording, confirm: true } })).json();
  async function login(username: string) {
    await page.goto('/');
    await page.getByLabel('계정', { exact: true }).fill(username);
    await page.getByLabel('비밀번호', { exact: true }).fill(password);
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeEnabled();
  }
  async function openScoring() {
    await page.getByRole('button', { name: '독립 채점', exact: true }).click();
    await page.getByRole('button', { name: 'v3sheet 독립 채점 열기', exact: true }).click();
  }
  await login('operator');
  await openScoring();
  await page.getByText('평가자 배정', { exact: true }).click();
  await page.getByLabel('입력 계정', { exact: true }).selectOption('reviewer');
  await page.getByLabel('평가자 ID', { exact: true }).fill('expert-one');
  await page.getByLabel('평가자 표시 이름', { exact: true }).fill('독립 전문가1');
  await page.getByRole('button', { name: '시트 배정', exact: true }).click();
  await expect(page.getByText('독립 전문가1', { exact: true })).toBeVisible();
  const first = (await (await request.get(endpoint + '/sheets')).json())[0];
  const second = await (await request.post(endpoint + '/sheets', { headers, data: { expected_revision: item.input_revision, assigned_username: 'reviewer2', rater_id: 'expert-two', rater_name: '독립 전문가2', source_sheet_id: first.sheet_id } })).json();
  expect(second.source_hash).toBe(first.source_hash);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login('reviewer');
  await openScoring();
  await expect(page.getByText('독립 전문가2', { exact: true })).toHaveCount(0);
  await expect(page.getByText('평가자 배정', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '내 시트 열기', exact: true }).click();
  const editor = page.getByLabel('내 채점 시트', { exact: true });
  await editor.getByLabel('원코드/항목 검색', { exact: true }).fill('바5');
  const row = editor.getByLabel('바5 원관찰', { exact: true });
  await row.getByLabel('바5 기록 상태', { exact: true }).selectOption('observed');
  await row.getByLabel('바5 원값', { exact: true }).selectOption('0');
  await row.getByText('바5 실제 관찰창·영상 근거', { exact: true }).click();
  for (let i = 0; i < 2; i++) {
    await row.getByRole('button', { name: '이 항목 영상 근거 추가', exact: true }).click();
    const evidence = row.locator('.evidence-editor').nth(i);
    await evidence.getByLabel('근거 관찰창', { exact: true }).selectOption('entry');
    await evidence.getByLabel('원본 근거 시작 초', { exact: true }).fill(String(i * .5));
    await evidence.getByLabel('원본 근거 끝 초', { exact: true }).fill(String((i + 1) * .5));
    await evidence.getByLabel('실제 확인 초', { exact: true }).fill('.5');
    await evidence.getByLabel('영상/조건 근거', { exact: true }).fill(`독립 원본 ${i + 1}번째 범위`);
  }
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByRole('button', { name: '독립 채점', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(row.getByLabel('바5 원값', { exact: true })).toHaveValue('0');
  await editor.getByRole('button', { name: '채점 초안 저장', exact: true }).click();
  await expect(editor.getByRole('button', { name: '채점 초안 저장', exact: true })).toBeDisabled();
  await expect(editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true })).toBeEnabled();
  let view = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  expect(view.document.sheet.observations[0].value).toBe(0);
  expect(view.document.sheet.observations[0].evidence).toHaveLength(2);
  await editor.getByLabel('원코드/항목 검색', { exact: true }).fill('개45');
  const leash = editor.getByLabel('개45 원관찰', { exact: true });
  await leash.getByLabel('개45 기록 상태', { exact: true }).selectOption('observed');
  await leash.getByLabel('개45 원값', { exact: true }).selectOption('0');
  await leash.getByText('개45 실제 관찰창·영상 근거', { exact: true }).click();
  await expect(leash).toContainText('0~0.2초 / 0.4~1초');
  for (let i = 0; i < 2; i++) {
    await leash.getByRole('button', { name: '이 항목 영상 근거 추가', exact: true }).click();
    const evidence = leash.locator('.evidence-editor').nth(i);
    await evidence.getByLabel('근거 관찰창', { exact: true }).selectOption('entry_leash');
    await evidence.getByLabel('원본 근거 시작 초', { exact: true }).fill(i ? '.5' : '0');
    await evidence.getByLabel('원본 근거 끝 초', { exact: true }).fill(i ? '.6' : '.1');
    await evidence.getByLabel('실제 확인 초', { exact: true }).fill('.05');
    await evidence.getByLabel('영상/조건 근거', { exact: true }).fill('물건 정지 제외 실제 줄 창');
  }
  const player = leash.locator('video').first();
  await player.evaluate(element => element.load());
  await expect.poll(() => player.evaluate(element => element.readyState)).toBeGreaterThan(0);
  await leash.getByRole('button', { name: '0.4~1초 범위 시작으로 이동', exact: true }).first().click();
  await expect.poll(() => player.evaluate(element => element.currentTime)).toBeCloseTo(.4);
  await editor.getByRole('button', { name: '채점 초안 저장', exact: true }).click();
  await expect(editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true })).toBeEnabled();
  view = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  expect(view.document.sheet.observations.find((item: { code: string }) => item.code === '개45').evidence).toHaveLength(2);
  await editor.getByLabel('원코드/항목 검색', { exact: true }).fill('바5');
  const catalog = await (await request.get('/api/catalog/behavior-v3')).json();
  const observations = catalog.items.filter((item: { usage: string }) => item.usage === 'direct').map((item: { code: string }) => view.document.sheet.observations.find((raw: { code: string }) => raw.code === item.code) ?? ({ code: item.code, value: null, status: 'unobserved', reason: '합성 시험: 실제 평가 미실시' }));
  expect((await page.request.put(`/api/sheets/${first.sheet_id}`, { headers, data: { expected_revision: view.summary.revision, observations } })).status()).toBe(200);
  await expect(editor.getByText('직접 입력109행 중 109행 기록.', { exact: false })).toBeVisible();
  await editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true }).click();
  await expect(editor.getByText('제출본 잠금', { exact: false })).toBeVisible();
  view = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  const independentRevision = view.summary.revision;
  await expect(editor.getByText('명시 공개된 완료본', { exact: true })).toHaveCount(0);
  const otherContext = await browser.newContext();
  try {
    const other = otherContext.request;
    await other.post('http://127.0.0.1:8765/api/auth/login', { headers, data: { username: 'reviewer2', password } });
    const saved = await (await other.put(`http://127.0.0.1:8765/api/sheets/${second.sheet_id}`, { headers, data: { expected_revision: second.revision, observations } })).json();
    const submitted = await (await other.post(`http://127.0.0.1:8765/api/sheets/${second.sheet_id}/submit`, { headers, data: { expected_revision: saved.revision, reason: '전문가2 독립 원자료 제출' } })).json();
    expect((await request.post(`/api/sheets/${first.sheet_id}/grants`, { headers, data: { expected_revision: view.summary.revision, target_sheet_id: second.sheet_id, target_revision: submitted.revision, reason: '독립 완료 후 명시 공개 시험' } })).status()).toBe(200);
  } finally { await otherContext.close(); }
  await editor.getByText('명시 공개된 완료본', { exact: true }).click();
  await editor.getByRole('button', { name: /공개 완료본 r.*열고 노출 기록/ }).click();
  await expect(editor.getByRole('heading', { name: '독립 전문가1 · 공개 후 검수', exact: true })).toBeVisible();
  view = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  expect(view.document.exposures).toHaveLength(1);
  expect((await page.request.get(`/api/sheets/${second.sheet_id}`)).status()).toBe(403);
  expect((await request.post(`/api/sheets/${first.sheet_id}/reopen`, { headers, data: { expected_revision: view.summary.revision, reason: '공개 후 수정 흐름 시험' } })).status()).toBe(200);
  await expect(row.getByLabel('바5 원값', { exact: true })).toBeEnabled();
  await row.getByLabel('바5 원값', { exact: true }).selectOption('2');
  const remote = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  const changed = remote.document.sheet.observations.map((item: { code: string }) => item.code === '바5' ? { ...item, value: 1 } : item);
  expect((await page.request.put(`/api/sheets/${first.sheet_id}`, { headers, data: { expected_revision: remote.summary.revision, observations: changed } })).status()).toBe(200);
  await expect(editor.getByText('다른 변경이 저장되었습니다.', { exact: false })).toBeVisible();
  await editor.getByRole('button', { name: '채점 초안 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('다른 채점 변경');
  await expect(row.getByLabel('바5 원값', { exact: true })).toHaveValue('2');
  page.once('dialog', dialog => dialog.accept());
  await editor.getByRole('button', { name: '미저장 입력 버리고 최신 조회', exact: true }).click();
  await expect(row.getByLabel('바5 원값', { exact: true })).toHaveValue('1');
  await editor.getByLabel('보존본 조회', { exact: true }).selectOption(String(independentRevision));
  await expect(editor.getByRole('heading', { name: '독립 전문가1 · 독립 원자료', exact: true })).toBeVisible();
  await expect(row.getByLabel('바5 원값', { exact: true })).toHaveValue('0');
  await expect(row.getByLabel('바5 원값', { exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('scoring-v3.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 360, height: 780 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('scoring-v3-mobile.png'), fullPage: true, animations: 'disabled' });
  const current = await (await page.request.get(`/api/sheets/${first.sheet_id}`)).json();
  expect((await request.patch(`/api/sheets/${first.sheet_id}/assignment`, { headers, data: { expected_revision: current.summary.revision, reason: '배정 취소 시험', active: false } })).status()).toBe(200);
  await expect(editor).toHaveCount(0);
  expect((await page.request.get(`/api/sheets/${first.sheet_id}`)).status()).toBe(403);
});
