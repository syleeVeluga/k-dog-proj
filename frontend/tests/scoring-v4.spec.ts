import { test, expect, type Locator } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const headers = { 'X-KDOG-Request': '1' };
const password = 'Browser-test-only-42';

test('S1 scoring preserves explicit zero, null states, source evidence, independent locks and exposure', async ({ page, request, browser }, testInfo) => {
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await request.post('/api/auth/login', { headers, data: { username: 'admin', password } });
  expect((await request.post('/api/admin/users', { headers, data: { username: 's1reviewer2', password, role: 'reviewer' } })).status()).toBe(201);
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'S1-SHEET', participant_id: 's1sheet', dog_name: '독립 채점 합성견' } })).json();
  const source = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=2:duration=48', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=48', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  const receipt = await (await request.post('/api/uploads', { headers, data: { request_id: 's1-scoring-synthetic', filename: 'synthetic-scoring.mp4', expected_size: source.length } })).json();
  expect((await request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: source })).status()).toBe(200);
  expect((await request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: { case_id: item.case_id, session_id: item.selected_session_id, camera_id: 'CAM1', expected_revision: item.input_revision } })).status()).toBe(200);
  item = await (await request.get(`/api/cases/${item.case_id}`)).json();
  const sessionPath = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const video = item.manifest.sessions[0].videos[0];
  const spans: [string, number, number][] = [['entry', 0, 3], ['baseline', 3, 6], ['alone', 6, 12], ['reunion', 12, 18], ['ignore', 18, 21], ['walk', 22, 28], ['stranger', 30, 38], ['exit', 40, 44]];
  const recording = { video_id: video.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '합성 S1 촬영 순서 확인',
    segments: spans.map(([segment, start_sec, end_sec]) => ({ segment, video_id: video.video_id, state: 'performed', start_sec, end_sec, reason: null })),
    walk_phases: ['move_1', 'stop_1', 'move_2', 'stop_2', 'move_3', 'stop_3'].map((phase, index) => ({ phase, video_id: video.video_id, state: 'performed', start_sec: 22 + index, end_sec: 23 + index, reason: null, proximity_exception: 'none', proximity_note: null })),
    events: [], video_offsets: [], coverage: [], tail_selections: [], linked_memos: [], safe_base_sequence: null };
  const confirmed = await request.put(sessionPath + '/recording-s1', { headers, data: { expected_revision: item.input_revision, recording } });
  expect(confirmed.status(), await confirmed.text()).toBe(200); item = await confirmed.json();
  async function login(username: string) {
    await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username); await page.getByLabel('비밀번호', { exact: true }).fill(password);
    await page.getByRole('button', { name: '로그인', exact: true }).click(); await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  }
  async function openScoring() {
    await page.getByRole('button', { name: '독립 채점', exact: true }).click();
    await page.getByRole('button', { name: 's1sheet 독립 채점 열기', exact: true }).click();
  }
  await login('operator'); await openScoring();
  await expect(page.getByText(/S1 Excel 가져오기 비활성/)).toBeVisible();
  await page.getByText('평가자 배정', { exact: true }).click();
  await page.getByLabel('입력 계정', { exact: true }).selectOption('reviewer');
  await page.getByLabel('평가자 ID', { exact: true }).fill('s1-one'); await page.getByLabel('평가자 표시 이름', { exact: true }).fill('S1 전문가1');
  const assigned = page.waitForResponse(value => value.url().endsWith('/sheets-s1') && value.request().method() === 'POST');
  await page.getByRole('button', { name: '시트 배정', exact: true }).click();
  const assignResponse = await assigned; expect(assignResponse.status(), await assignResponse.text()).toBe(201);
  const first = await assignResponse.json();
  const second = await (await request.post(sessionPath + '/sheets-s1', { headers, data: { expected_revision: item.input_revision, assigned_username: 's1reviewer2', rater_id: 's1-two', rater_name: 'S1 전문가2', source_sheet_id: first.sheet_id } })).json();
  expect(second.source_hash).toBe(first.source_hash);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click(); await login('reviewer'); await openScoring();
  await expect(page.getByText('S1 전문가2', { exact: true })).toHaveCount(0);
  await expect(page.getByText('평가자 배정', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '내 시트 열기', exact: true }).click();
  const editor = page.getByLabel('내 S1 채점 시트', { exact: true });
  await expect(editor.getByText('직접 입력 86행 중 0행 기록', { exact: false })).toBeVisible();
  await expect(editor.getByLabel('개26 자동 계산', { exact: true }).getByRole('textbox')).toHaveCount(0);
  await expect(editor.getByLabel('8구간 필터', { exact: true }).locator('option')).toHaveCount(9);
  async function selectRow(code: string) {
    await editor.getByLabel('원코드/항목 검색', { exact: true }).fill(code);
    return editor.getByLabel(`${code} 원관찰`, { exact: true });
  }
  async function addEvidence(row: Locator, code: string, windowId: string, start: number, end: number, note: string) {
    await row.getByText(`${code} F 관찰 근거·영상`, { exact: true }).click();
    await row.getByRole('button', { name: '영상 근거 추가', exact: true }).click();
    const evidence = row.locator('.evidence-editor').first();
    await expect(evidence.getByLabel('근거 원본 영상', { exact: true })).toHaveValue('');
    await expect(evidence.getByLabel('실제 확인 초', { exact: true })).toHaveValue('');
    await evidence.getByLabel('근거 관찰창', { exact: true }).selectOption(windowId);
    await evidence.getByLabel('근거 원본 영상', { exact: true }).selectOption(video.video_id);
    await evidence.getByLabel('원본 근거 시작 초', { exact: true }).fill(String(start));
    await evidence.getByLabel('원본 근거 끝 초', { exact: true }).fill(String(end));
    await evidence.getByLabel('실제 확인 초', { exact: true }).fill(String(end - start));
    await evidence.getByLabel('F 관찰 근거', { exact: true }).fill(note);
    return evidence;
  }
  const count = await selectRow('바14');
  await expect(count.getByLabel('바14 기록 상태', { exact: true })).toHaveValue('');
  await count.getByLabel('바14 기록 상태', { exact: true }).selectOption('observed'); await count.getByLabel('바14 원값', { exact: true }).fill('0');
  await count.getByLabel('시행 유효 상태', { exact: true }).selectOption('valid'); await count.getByLabel('관찰 기회', { exact: true }).selectOption('present');
  await count.getByLabel('실제 전체 구간 관찰 완료', { exact: true }).check();
  const evidence = await addEvidence(count, '바14', 'entry_whole', 0, 3, '합성 입장 전체에서 사건 없음 확인');
  await count.getByLabel('바14 G 양식 검토메모', { exact: true }).fill('양식 검토 전용, 분석 문장에 사용하지 않음');
  const player = evidence.locator('video'); await player.evaluate(element => element.load());
  await expect.poll(() => player.evaluate(element => element.readyState)).toBeGreaterThan(0);
  page.once('dialog', dialog => dialog.dismiss()); await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(count.getByLabel('바14 원값', { exact: true })).toHaveValue('0');
  const vocal = await selectRow('바6'); await vocal.getByLabel('바6 기록 상태', { exact: true }).selectOption('observed'); await vocal.getByLabel('바6 원값', { exact: true }).selectOption('1');
  await vocal.getByLabel('시행 유효 상태', { exact: true }).selectOption('valid'); await addEvidence(vocal, '바6', 'entry_whole', 0, 3, '합성 전체 3초 청취');
  await vocal.getByText('바6 전체 청취·누적 발성량', { exact: true }).click(); await vocal.getByRole('button', { name: '청취 기록 추가', exact: true }).click();
  await vocal.getByLabel('실제 청취 초', { exact: true }).fill('3'); await vocal.getByLabel('누적 발성 초', { exact: true }).fill('1');
  await vocal.getByLabel('전체 실제 구간 청취 판독 완료', { exact: true }).check(); await vocal.getByLabel('청취·발성량 근거', { exact: true }).fill('1/3 경계 합성 시험');
  const walk = await selectRow('개38'); await walk.getByLabel('개38 기록 상태', { exact: true }).selectOption('observed'); await walk.getByLabel('개38 원값', { exact: true }).selectOption('1');
  await walk.getByLabel('시행 유효 상태', { exact: true }).selectOption('valid'); await addEvidence(walk, '개38', 'walk_phase_1', 22, 23, '첫 이동 국면 실제 관찰');
  await walk.getByText('개38 걷기 거리 예외', { exact: true }).click(); await walk.getByLabel('거리 예외', { exact: true }).selectOption('recheck'); await walk.getByLabel('거리 예외 근거', { exact: true }).fill('합성 안전 거리 재확인');
  const memo = await selectRow('보25'); await memo.getByLabel('보25 기록 상태', { exact: true }).selectOption('observed'); await memo.getByLabel('보25 원값', { exact: true }).fill('관찰 메모 원문'); await memo.getByLabel('시행 유효 상태', { exact: true }).selectOption('valid');
  const policy = await selectRow('개21'); await policy.getByLabel('개21 기록 상태', { exact: true }).selectOption('policy_pending'); await policy.getByLabel('개21 빈값 사유', { exact: true }).fill('D03 복수 사건 종합 규칙 대기');
  for (const [code, sequence] of [['개9', '−2'], ['보10', '+2 → +1 → 0 → -1 → -2']]) {
    const row = await selectRow(code);
    await expect(row.getByText(code === '개9' ? '선택 순서: -2 → -1 → 0 → +1 → +2' : `선택 순서: ${sequence}`, { exact: true })).toBeVisible();
  }
  await editor.getByText('개59 연결 메모 · 별도 보존', { exact: true }).click(); await editor.getByRole('button', { name: '개59 연결 메모 추가', exact: true }).click();
  await editor.getByLabel('개59 메모', { exact: true }).fill('원점수를 덮지 않는 연결 맥락'); await editor.getByLabel('개59 연결 항목', { exact: true }).selectOption(['바14']);
  await editor.getByLabel('저장·정정 사유', { exact: true }).fill('합성 원관찰 입력');
  const saved = page.waitForResponse(value => value.url().endsWith(`/score-sheets-s1/${first.sheet_id}`) && value.request().method() === 'PUT');
  await editor.getByRole('button', { name: '채점 초안 저장', exact: true }).click(); const saveResponse = await saved; expect(saveResponse.status(), await saveResponse.text()).toBe(200);
  let view = await (await page.request.get(`/api/score-sheets-s1/${first.sheet_id}`)).json();
  const observations = view.document.sheet.observations;
  expect(observations.find((value: { code: string }) => value.code === '바14').value).toBe(0);
  expect(observations.find((value: { code: string }) => value.code === '바14').evidence[0]).toMatchObject({ video_sha256: video.sha256, camera_id: 'CAM1', observed_seconds: 3 });
  expect(observations.find((value: { code: string }) => value.code === '개21').value).toBeNull();
  expect(view.document.sheet.walk_phases[0].proximity_exception).toBe('recheck'); expect(view.document.sheet.linked_memos[0].code).toBe('개59');
  expect(observations.some((value: { code: string }) => value.code === '개59')).toBe(false);
  await expect(editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true })).toBeDisabled();
  const catalog = await (await request.get('/api/catalog/behavior-s1')).json();
  const all = catalog.items.filter((value: { usage: string; optional: boolean }) => value.usage !== 'automatic' && !value.optional).map((value: { code: string }) => observations.find((raw: { code: string }) => raw.code === value.code) ?? { code: value.code, value: null, status: 'unobserved', reason: '합성 시험 관찰 미실시' });
  expect(all).toHaveLength(84);
  expect((await page.request.put(`/api/score-sheets-s1/${first.sheet_id}`, { headers, data: { expected_revision: view.summary.revision, observations: all, walk_phases: view.document.sheet.walk_phases, linked_memos: view.document.sheet.linked_memos, reason: '필수 미실시 사유 합성 fixture' } })).status()).toBe(200);
  await expect(editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true })).toBeEnabled(); await editor.getByRole('button', { name: '독립 원자료 제출·잠금', exact: true }).click();
  await expect(editor.getByText(/제출본 잠금/)).toBeVisible(); view = await (await page.request.get(`/api/score-sheets-s1/${first.sheet_id}`)).json();
  const independentRevision = view.summary.revision;
  expect(view.document.sheet.observations).toHaveLength(86);
  expect(view.document.sheet.observations.find((value: { code: string }) => value.code === '바54').value).toBeNull();
  const otherContext = await browser.newContext();
  try {
    const other = otherContext.request; const base = 'http://127.0.0.1:8765';
    await other.post(base + '/api/auth/login', { headers, data: { username: 's1reviewer2', password } });
    const secondSave = await (await other.put(`${base}/api/score-sheets-s1/${second.sheet_id}`, { headers, data: { expected_revision: second.revision, observations: all, reason: '두 번째 합성 독립 입력' } })).json();
    const secondSubmit = await (await other.post(`${base}/api/score-sheets-s1/${second.sheet_id}/submit`, { headers, data: { expected_revision: secondSave.revision, reason: '두 번째 합성 독립 제출' } })).json();
    expect((await request.post(`/api/score-sheets-s1/${first.sheet_id}/grants`, { headers, data: { expected_revision: view.summary.revision, target_sheet_id: second.sheet_id, target_revision: secondSubmit.revision, reason: '두 독립 제출 뒤 명시 공개' } })).status()).toBe(200);
  } finally { await otherContext.close(); }
  await editor.getByText('명시 공개된 완료본', { exact: true }).click(); await editor.getByRole('button', { name: /공개 완료본 r.*열고 노출 기록/ }).click();
  await expect(editor.getByRole('heading', { name: 'S1 전문가1 · 공개 후 검수', exact: true })).toBeVisible();
  view = await (await page.request.get(`/api/score-sheets-s1/${first.sheet_id}`)).json(); expect(view.document.exposures).toHaveLength(1); expect(view.document.initial_submission.revision).toBe(independentRevision);
  expect((await page.request.get(`/api/score-sheets-s1/${second.sheet_id}`)).status()).toBe(403);
  expect((await request.post(`/api/score-sheets-s1/${first.sheet_id}/reopen`, { headers, data: { expected_revision: view.summary.revision, reason: '공개 후 수정 시험' } })).status()).toBe(200);
  const changedRow = await selectRow('바14'); await expect(changedRow.getByLabel('바14 원값', { exact: true })).toBeEnabled(); await changedRow.getByLabel('바14 원값', { exact: true }).fill('2');
  await editor.getByLabel('저장·정정 사유', { exact: true }).fill('동시 변경 합성 시험');
  const remote = await (await page.request.get(`/api/score-sheets-s1/${first.sheet_id}`)).json();
  expect((await page.request.put(`/api/score-sheets-s1/${first.sheet_id}`, { headers, data: { expected_revision: remote.summary.revision, observations: remote.document.sheet.observations.map((value: { code: string }) => value.code === '바14' ? { ...value, value: 1 } : value), reason: '다른 창 저장 합성 시험' } })).status()).toBe(200);
  await expect(editor.getByText(/다른 변경이 저장되었습니다/)).toBeVisible(); await editor.getByRole('button', { name: '채점 초안 저장', exact: true }).click();
  await expect(editor.getByRole('alert')).toContainText('다른 채점 변경'); await expect(changedRow.getByLabel('바14 원값', { exact: true })).toHaveValue('2');
  page.once('dialog', dialog => dialog.accept()); await editor.getByRole('button', { name: '미저장 입력 버리고 최신 조회', exact: true }).click();
  await expect(changedRow.getByLabel('바14 원값', { exact: true })).toHaveValue('1');
  await editor.getByLabel('보존본 조회', { exact: true }).selectOption(String(independentRevision));
  await expect(editor.getByText('보존본 읽기 전용', { exact: true })).toBeVisible(); await expect(changedRow.getByLabel('바14 원값', { exact: true })).toHaveValue('0'); await expect(changedRow.getByLabel('바14 원값', { exact: true })).toBeDisabled();
  await page.setViewportSize({ width: 360, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('scoring-s1-360.png'), fullPage: true, animations: 'disabled' });
  expect(errors).toEqual([]);
});
