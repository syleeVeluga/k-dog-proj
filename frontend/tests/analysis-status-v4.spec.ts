import { test, expect, type Page } from '@playwright/test';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page, username = 'operator') {
  await page.goto('/'); await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function setup(page: Page, participant: string) {
  await login(page);
  const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'ES03', participant_id: participant, dog_name: '분석 합성견' } })).json();
  return { item, path: `/api/cases/${item.case_id}/sessions/${item.selected_session_id}` };
}
function run(item: any, id = 'current-run', status = 'queued', current: string | null = null) {
  const order = ['score_v4', 'calculate_v4', 'attachment_v4', 'publish_v4'];
  return { run_id: id, case_id: item.case_id, session_id: item.selected_session_id, kind: 's1', input_revision: item.input_revision,
    requested_by: 'operator', created_at: '2026-10-12T10:00:00Z', updated_at: '2026-10-12T10:00:01Z', status,
    retry_at: status === 'retry_wait' ? '2026-10-12T10:00:30Z' : null, outdated: false, settings_outdated: false,
    failure_code: null as string | null, result_available: status === 'succeeded' || status === 'partial_failed',
    steps: [] as any[], planned_provider_calls: 2, reserved_calls: 0, max_ai_calls: 100, judgement_status: 'implemented_professor_test_pending',
    progress: { current_stage: current, state_uncertain: status === 'running' && !current, stages: order.map((stage, index) => {
      const state = status === 'succeeded' || current && index < order.indexOf(current) ? 'succeeded' : stage === current ? 'running' : 'waiting';
      return { stage, keys: [{ key: stage === 'score_v4' ? 'synthetic-entry' : 'session', status: state, attempt: state === 'waiting' ? null : 1, reused: false }], completed: state === 'succeeded' ? 1 : 0, failed: 0, running: state === 'running' ? 1 : 0, waiting: state === 'waiting' ? 1 : 0 };
    }) } };
}
async function ready(page: Page, item: any, path: string) {
  await page.route('**/api/scoring-ai-s1/readiness', route => route.fulfill({ json: { active_version: 'synthetic-settings', enabled: true, planned_provider_calls: 2, judgement_status: 'implemented_professor_test_pending' } }));
  await page.route(`**${path}/preprocess-s1`, route => route.fulfill({ json: { status: 'complete', input_revision: item.input_revision, outdated: false, result_pointer: { ref: 'synthetic/batch.json', hash: 'a'.repeat(64) } } }));
}
async function open(page: Page, participant: string) { await openMenu(page, '독립 채점'); await page.getByRole('button', { name: `${participant} 독립 채점 열기`, exact: true }).click(); }

test('이전 성공보다 선택 실행을 우선하고 예정 단계부터 게시 완료까지 표시한다', async ({ page }, testInfo) => {
  const { item, path } = await setup(page, 'ES03-STAGES'); await ready(page, item, path);
  let current = run(item), reads = 0;
  const previous = { ...run(item, 'old-run', 'succeeded'), created_at: '2026-10-11T10:00:00Z' };
  await page.route(`**${path}/runs-s1`, route => { reads++; return route.fulfill({ json: [current, previous] }); });
  await open(page, 'ES03-STAGES');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true }), card = panel.getByRole('region', { name: '현재 AI 분석 실행', exact: true });
  await expect(panel.getByText('AI 초안: 분석 대기', { exact: true })).toBeVisible();
  await expect(card.getByRole('listitem')).toHaveCount(4); await expect(panel.getByText('이전 분석 결과 있음', { exact: true })).toBeVisible();
  for (const [stage, name] of [['score_v4', '항목군 관찰'], ['calculate_v4', '기본 계산'], ['attachment_v4', '애착 판단'], ['publish_v4', '결과 게시']]) {
    current = run(item, 'current-run', 'running', stage);
    await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
    await expect(card.getByText(`현재 단계: ${name}`, { exact: true })).toBeVisible();
    await expect(panel.getByText('AI 초안: 분석 중', { exact: true })).toBeVisible();
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`analysis-progress-${width}.png`), fullPage: true });
  }
  current = run(item, 'current-run', 'succeeded');
  await expect(panel.getByText('AI 초안: 분석 완료', { exact: true })).toBeVisible();
  await page.waitForTimeout(500); const count = reads; await page.waitForTimeout(2300); expect(reads).toBe(count);
});

test('부분 게시·중지·만료 점유와 재시도 대기를 정상 완료와 구분한다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-STATES'); await ready(page, item, path);
  let current = run(item, 'state-run', 'partial_failed'); current.failure_code = 'synthetic_failure';
  await page.route(`**${path}/runs-s1`, route => route.fulfill({ json: [current] }));
  await open(page, 'ES03-STATES');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(panel.getByText('AI 초안: 일부 완료 · 확인 필요', { exact: true })).toBeVisible();
  for (const [status, text] of [['stopped', '중지됨'], ['failed', '분석 실패'], ['retry_wait', '자동 재시도 대기']]) {
    current = run(item, 'state-run', status);
    await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
    await expect(panel.getByText(`AI 초안: ${text}`, { exact: true })).toBeVisible();
  }
  await expect(panel.getByText(/자동 재시도 예정:/)).toBeVisible();
  current = run(item, 'state-run', 'running');
  await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
  await expect(panel.getByText(/실행 상태 확인 필요/)).toBeVisible();
  await expect(panel.getByRole('region', { name: '현재 AI 분석 실행', exact: true }).getByText(/현재 단계:/)).toHaveCount(0);
});

test('반복 조회 오류는 마지막 상태를 유지하며 자동 복구하고 배경 조회는 제어를 잠그지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-RECONNECT'); await ready(page, item, path);
  let fail = 0, current = run(item, 'connected-run', 'running', 'score_v4'), reads = 0;
  await page.route(`**${path}/runs-s1`, route => {
    reads++; if (fail > 0) { fail--; return route.fulfill({ status: 503, json: { detail: '합성 일시 조회 실패' } }); }
    return route.fulfill({ json: [current] });
  });
  await open(page, 'ES03-RECONNECT');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await panel.getByLabel('실행 제어 사유', { exact: true }).fill('합성 중지 사유');
  await expect(panel.getByRole('button', { name: '이 AI 실행 중지', exact: true })).toBeEnabled();
  fail = 2;
  await expect(panel.getByRole('alert')).toContainText('합성 일시 조회 실패', { timeout: 6000 });
  await expect(panel.getByText('현재 단계: 항목군 관찰', { exact: true })).toBeVisible();
  await expect(panel.getByText('개발자가 AI 설정을 활성화해야 실행할 수 있습니다.', { exact: true })).toHaveCount(0);
  current = run(item, 'connected-run', 'running', 'calculate_v4');
  await expect(panel.getByText('현재 단계: 기본 계산', { exact: true })).toBeVisible({ timeout: 10000 });
  await expect(panel.getByRole('button', { name: '이 AI 실행 중지', exact: true })).toBeEnabled(); expect(reads).toBeGreaterThan(2);
});

test('응답 유실과 일시적 미발견은 접수 조회로 복구하며 설정 변경 후에도 재POST하지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-LOST'); await ready(page, item, path);
  let current = run(item, 'lost-run'), accepted = false, found = false, posts = 0, resolvers = 0;
  const previous = run(item, 'prior-stop-target', 'queued');
  await page.route(`**${path}/runs-s1`, async route => {
    if (route.request().method() === 'POST') { posts++; accepted = true; await route.abort('failed'); }
    else await route.fulfill({ json: found ? [current, previous] : [previous] });
  });
  await page.route(`**${path}/runs-s1/by-request/*`, route => { resolvers++; return route.fulfill({ json: { found, run: found ? current : null } }); });
  await open(page, 'ES03-LOST'); const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await panel.getByLabel('실행 제어 사유', { exact: true }).fill('이전 실행 제어 사유');
  await panel.getByRole('button', { name: 'AI 분석 시작', exact: true }).click();
  await expect(panel.getByText('AI 초안: 요청 접수 여부 확인 중', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeDisabled();
  await expect(panel.getByRole('button', { name: '이 AI 실행 중지', exact: true })).toBeDisabled();
  await page.route('**/api/scoring-ai-s1/readiness', route => route.fulfill({ json: { active_version: 'inactive', enabled: false, planned_provider_calls: 0, judgement_status: 'implemented_professor_test_pending' } }));
  await expect.poll(() => resolvers).toBeGreaterThan(1); expect(accepted).toBe(true);
  found = true;
  await expect(panel.getByText('AI 초안: 분석 대기', { exact: true })).toBeVisible();
  await page.reload(); await open(page, 'ES03-LOST');
  await expect(panel.getByText('AI 초안: 분석 대기', { exact: true })).toBeVisible(); expect(posts).toBe(1);
});

test('같은 회차의 입력판이 바뀌면 이전 제어 요청중과 늦은 응답을 새 문맥에 적용하지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-REVISION'); await ready(page, item, path);
  let current = run(item, 'revision-run', 'running', 'score_v4'), stopped = false;
  let release!: () => void; const wait = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/runs-s1`, route => route.fulfill({ json: [current] }));
  await page.route('**/api/runs-s1/revision-run/stop', async route => { stopped = true; await wait; await route.fulfill({ json: run(item, 'revision-run', 'stopped') }); });
  await open(page, 'ES03-REVISION'); const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await panel.getByLabel('실행 제어 사유', { exact: true }).fill('합성 판본 전환 중지');
  await panel.getByRole('button', { name: '이 AI 실행 중지', exact: true }).click();
  await expect(panel.getByText('AI 초안: 중지 요청 중', { exact: true })).toBeVisible();
  expect(stopped).toBe(true);
  current = { ...current, outdated: true };
  // Explicit same-session selection reloads the current input revision in the parent.
  const changed = page.waitForResponse(response => response.url().endsWith(`/cases/${item.case_id}/sessions`) && response.request().method() === 'POST');
  await page.getByLabel('선택 세션', { exact: true }).selectOption(item.selected_session_id);
  expect((await changed).status()).toBe(200);
  await expect(panel.getByText('AI 초안: 중지 요청 중', { exact: true })).toHaveCount(0);
  release(); await page.waitForTimeout(300);
  await expect(panel.getByText('AI 초안: 분석 중', { exact: true })).toBeVisible();
});

test('느린 분석 생성의 늦은 응답은 로그아웃과 다른 계정 문맥을 덮지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-ACCOUNT'); await ready(page, item, path);
  let release!: () => void, posted = false;
  const wait = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/runs-s1`, async route => {
    if (route.request().method() === 'POST') { posted = true; await wait; await route.fulfill({ status: 201, json: run(item, 'old-account-run') }); }
    else await route.fulfill({ json: [] });
  });
  await page.route(`**${path}/runs-s1/by-request/*`, route => route.fulfill({ json: { found: false, run: null } }));
  await open(page, 'ES03-ACCOUNT'); await page.getByRole('button', { name: 'AI 분석 시작', exact: true }).click();
  await expect(page.getByText('AI 초안: 분석 요청 중', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'reviewer'); await open(page, 'ES03-ACCOUNT'); release();
  await page.waitForTimeout(300);
  await expect(page.getByText('내가 시작한 이번 실행', { exact: false })).toHaveCount(0);
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.includes('kdog-ai:operator:')))).toEqual([]);
  expect(posted).toBe(true);
});

test('제어 응답 이후의 중지를 늦은 running 조회가 되돌리지 않고 명시 재시도는 queued로 갱신한다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES03-STOP'); await ready(page, item, path);
  let current = run(item, 'control-run', 'running', 'score_v4'), reads = 0, delayed = false;
  let release!: () => void; const wait = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/runs-s1`, async route => {
    reads++; const captured = { ...current };
    if (reads === 2) { delayed = true; await wait; }
    await route.fulfill({ json: [captured] });
  });
  await page.route('**/api/runs-s1/control-run/*', route => {
    const status = route.request().url().endsWith('/stop') ? 'stopped' : 'queued'; current = run(item, 'control-run', status);
    return route.fulfill({ json: current });
  });
  await open(page, 'ES03-STOP'); const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await panel.getByLabel('실행 제어 사유', { exact: true }).fill('합성 제어'); await expect.poll(() => delayed).toBe(true);
  await expect(panel.getByRole('button', { name: '이 AI 실행 중지', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: '이 AI 실행 중지', exact: true }).click();
  await expect(panel.getByText('AI 초안: 중지됨', { exact: true })).toBeVisible(); release();
  await page.waitForTimeout(300); await expect(panel.getByText('AI 초안: 중지됨', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '고정 입력으로 AI 재시도', exact: true }).click();
  await expect(panel.getByText('AI 초안: 분석 대기', { exact: true })).toBeVisible();
});

test('조회 중 사용자가 선택한 실행은 늦은 목록 응답과 저장에서 유지된다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-SELECTION'); await ready(page, item, path);
  const first = run(item, 'first-run', 'failed'), second = run(item, 'second-run', 'succeeded');
  let hold = false, waiting = false, release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/runs-s1`, async route => {
    if (hold) { waiting = true; await gate; }
    await route.fulfill({ json: [first, second] });
  });
  await open(page, 'AC02-SELECTION');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(panel.getByText('AI 초안: 분석 실패', { exact: true })).toBeVisible();
  hold = true;
  await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
  await expect.poll(() => waiting).toBe(true);
  try {
    await panel.getByRole('article', { name: 'AI 실행 기록 second-r', exact: true }).getByRole('button', { name: '이 실행 상태 보기', exact: true }).click();
    await expect(panel.getByText('AI 초안: 분석 완료', { exact: true })).toBeVisible();
  } finally { release(); }
  await expect(panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true })).toBeEnabled();
  await expect(panel.getByText('AI 초안: 분석 완료', { exact: true })).toBeVisible();
  const saved = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)!), `kdog-ai:operator:${item.case_id}:${item.selected_session_id}`);
  expect(saved).toEqual({ runId: 'second-run' });
});

test('준비 상태 조회만 실패하면 성공한 AI 목록은 보존하고 새 실행을 차단한다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-AI-PARTIAL'); await ready(page, item, path);
  const current = run(item, 'partial-read-run', 'succeeded');
  await page.route(`**${path}/runs-s1`, route => route.fulfill({ json: [current] }));
  await page.route('**/api/scoring-ai-s1/readiness', route => route.fulfill({ status: 503, json: { detail: '합성 준비 설정 연결 실패' } }));
  await open(page, 'AC02-AI-PARTIAL');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(panel.getByText('AI 초안: 분석 완료', { exact: true })).toBeVisible();
  await expect(panel.getByRole('alert')).toContainText('합성 준비 설정 연결 실패');
  await expect(panel.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeDisabled();
  await expect(panel.getByText('개발자가 AI 설정을 활성화해야 실행할 수 있습니다.', { exact: true })).toHaveCount(0);
});

test('접근 상실로 정리한 요청은 늦은 POST 성공 응답으로 복원하지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-ACCESS-LOST'); await ready(page, item, path);
  let posted = false, release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/runs-s1`, async route => {
    if (route.request().method() === 'POST') {
      posted = true; await gate;
      await route.fulfill({ status: 201, json: run(item, 'late-accepted-run') });
    } else await route.fulfill({ json: [] });
  });
  await page.route(`**${path}/runs-s1/by-request/*`, route => route.fulfill({ status: 403, json: { detail: '합성 실행 접근 상실' } }));
  await open(page, 'AC02-ACCESS-LOST');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await panel.getByRole('button', { name: 'AI 분석 시작', exact: true }).click();
  const key = `kdog-ai:operator:${item.case_id}:${item.selected_session_id}`;
  try {
    await expect.poll(() => posted).toBe(true);
    await expect(panel.getByRole('alert')).toContainText('합성 실행 접근 상실');
    expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBeNull();
  } catch (error) { release(); throw error; }
  const lateResponse = page.waitForResponse(response => response.url().endsWith(path + '/runs-s1') && response.request().method() === 'POST');
  release(); await (await lateResponse).finished();
  const refreshed = page.waitForResponse(response => response.url().endsWith(path + '/runs-s1') && response.request().method() === 'GET');
  await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
  await (await refreshed).finished();
  await expect(panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true })).toBeEnabled();
  await expect(panel.getByRole('region', { name: '현재 AI 분석 실행', exact: true })).toHaveCount(0);
  expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBeNull();
});

test('AI 접수 정보 저장 실패는 POST를 보내지 않고 요청 중 상태를 해제한다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-STORAGE-FAILURE'); await ready(page, item, path);
  let posts = 0;
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.route(`**${path}/runs-s1`, route => {
    if (route.request().method() === 'POST') { posts++; return route.fulfill({ json: run(item) }); }
    return route.fulfill({ json: [] });
  });
  await page.route(`**${path}/runs-s1/by-request/*`, route => route.fulfill({ json: { found: false, run: null } }));
  await open(page, 'AC02-STORAGE-FAILURE');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(panel.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeEnabled();
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key.startsWith('kdog-ai:')) throw new DOMException('합성 접수 저장 공간 부족', 'QuotaExceededError');
      original.call(this, key, value);
    };
    Object.assign(window, { restoreAiStorage: () => { Storage.prototype.setItem = original; } });
  });
  try {
    await panel.getByRole('button', { name: 'AI 분석 시작', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('합성 접수 저장 공간 부족');
    await expect(panel.getByText('AI 초안: 요청 접수 여부 확인 중', { exact: true })).toBeVisible();
    await expect(panel.getByLabel('실행 제어 사유', { exact: true })).toBeEnabled();
    expect(posts).toBe(0);
    expect(browserErrors).toEqual([]);
    const key = `kdog-ai:operator:${item.case_id}:${item.selected_session_id}`;
    expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBeNull();
  } finally {
    await page.evaluate(() => (window as unknown as { restoreAiStorage: () => void }).restoreAiStorage());
  }
});

test('손상된 AI 접수 JSON을 복원하고 명시 409 거절의 대기 상태를 정리한다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC09-AI-CORRUPT-REJECT'); await ready(page, item, path);
  const key = `kdog-ai:operator:${item.case_id}:${item.selected_session_id}`;
  await page.evaluate(key => sessionStorage.setItem(key, '{broken'), key);
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  let posts = 0;
  await page.route(`**${path}/runs-s1`, route => {
    if (route.request().method() === 'POST') { posts++; return route.fulfill({ status: 409, json: { detail: '합성 AI 접수 명시 거절' } }); }
    return route.fulfill({ json: [] });
  });
  await open(page, 'AC09-AI-CORRUPT-REJECT');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(panel.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeEnabled();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBe('{broken');
  await panel.getByRole('button', { name: 'AI 분석 시작', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('합성 AI 접수 명시 거절');
  await expect(panel.getByRole('button', { name: 'AI 분석 시작', exact: true })).toBeEnabled();
  await expect(panel.getByLabel('실행 제어 사유', { exact: true })).toBeEnabled();
  await expect(panel.getByText('요청 접수 여부 확인 중 · 상태 조회로 같은 요청을 확인합니다.', { exact: true })).toHaveCount(0);
  expect(JSON.parse((await page.evaluate(key => sessionStorage.getItem(key), key))!)).toEqual({});
  await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true })).toBeEnabled();
  expect(posts).toBe(1); expect(browserErrors).toEqual([]);
});
