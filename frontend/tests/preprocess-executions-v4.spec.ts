import { test, expect, type Page } from '@playwright/test';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page, account = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(account);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function setup(page: Page, id: string) {
  await login(page);
  const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'ES02', participant_id: id, dog_name: '실행 합성견' } })).json();
  return { item, path: `/api/cases/${item.case_id}/sessions/${item.selected_session_id}/preprocess-s1` };
}
function execution(item: any, id = 'synthetic-execution') {
  return { execution_id: id, case_id: item.case_id, session_id: item.selected_session_id, participant_id: item.participant_id,
    dog_name: item.dog_name, event_id: item.event_id, sequence_no: null, guardian_name: '', input_revision: item.input_revision,
    request_id: 'synthetic-request', requested_by: 'operator', started_at: '2026-10-12T10:00:00Z', finished_at: null,
    status: 'running', current_stage: 'clips', stage_updated_at: '2026-10-12T10:00:01Z', message: '합성 실행 중',
    outdated: false, result_pointer: null, result: null };
}
function shared(item: any, state = 'ready') {
  return { case_id: item.case_id, session_id: item.selected_session_id, input_revision: item.input_revision,
    ready: true, status: state, message: '합성 준비 상태', outdated: false, result_pointer: null, result: null };
}
async function choose(page: Page, id: string) {
  await openMenu(page, '전처리');
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await page.getByRole('button', { name: `${id} 전처리 열기`, exact: true }).click();
}

test('내 실행 목록은 전처리 상태만 필터하고 빈 이력에서도 공유 대상을 선택한다', async ({ page }) => {
  await setup(page, 'ES02-EMPTY');
  await openMenu(page, '전처리');
  await expect(page.getByRole('heading', { name: '아직 실행한 전처리가 없습니다.' })).toBeVisible();
  await expect(page.getByLabel('진행 단계 필터', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: '전처리 상태', exact: true }).locator('option')).toHaveText(['전체', '실행 중', '완료', '확인 필요']);
  await page.getByLabel('검색', { exact: true }).fill('없음');
  await expect(page.getByRole('heading', { name: '조건에 맞는 전처리 작업이 없습니다.' })).toBeVisible();
  await page.getByLabel('검색', { exact: true }).fill('');
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await page.getByRole('button', { name: 'ES02-EMPTY 전처리 열기', exact: true }).click();
  await expect(page.getByRole('region', { name: '다중 카메라 전처리', exact: true }).getByRole('status')).toContainText('촬영 기록 확인 필요');
});

test('지정 실행은 공유 최신 실패와 분리하고 계정 전환에서 목록을 비운다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES02-MINE');
  const value = { ...execution(item), status: 'complete', current_stage: 'verify_save', finished_at: '2026-10-12T10:00:02Z', message: '내 완료 결과', outdated: true };
  let own = true;
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: own ? [value] : [], next_cursor: null } }));
  await page.route(`**${path}`, route => route.fulfill({ json: shared(item, 'failed') }));
  await page.route(`**${path}/executions/*`, route => route.fulfill({ json: value }));
  await openMenu(page, '전처리');
  const row = page.getByRole('row').filter({ hasText: 'ES02-MINE' });
  await expect(row).toContainText('완료'); await expect(row).toContainText('현재 입력과 다름');
  await row.getByRole('button', { name: '상세 보기' }).click();
  await expect(page.getByRole('status')).toContainText('완료 · 내 완료 결과');
  const changed = await page.request.post(`/api/cases/${item.case_id}/sessions`, { headers, data: { expected_revision: item.input_revision, note: '다른 직원의 합성 새 회차' } });
  expect(changed.status()).toBe(200);
  await page.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
  await expect(page.getByRole('region', { name: '다중 카메라 전처리', exact: true }).getByRole('status')).toContainText('완료 · 내 완료 결과');
  await expect(page.getByText('ES02-MINE · 보존된 1회차 실행 · operator', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  own = false;
  await login(page, 'reviewer'); await openMenu(page, '전처리');
  await expect(page.getByRole('heading', { name: '아직 실행한 전처리가 없습니다.' })).toBeVisible();
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('kdog-preprocess:')))).toEqual([]);
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await expect(page.getByRole('button', { name: 'ES02-MINE 전처리 열기', exact: true })).toBeVisible();
});

test('느린 POST 동안 단계와 재연결을 표시하고 종료 후 조회를 멈춘다', async ({ page }, testInfo) => {
  const { item, path } = await setup(page, 'ES02-SLOW');
  let value = execution(item), accepted = false, posts = 0, reads = 0, failures = 0;
  let release!: () => void;
  const postWait = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: accepted ? [value] : [], next_cursor: null } }));
  await page.route(`**${path}`, async route => {
    if (route.request().method() === 'POST') { posts++; accepted = true; value.request_id = route.request().postDataJSON().request_id; await postWait; await route.fulfill({ json: { batch_id: value.execution_id } }); }
    else await route.fulfill({ json: shared(item) });
  });
  await page.route(`**${path}/executions/*`, async route => {
    reads++;
    if (failures > 0) { failures--; await route.fulfill({ status: 503, json: { detail: '합성 연결 실패' } }); }
    else await route.fulfill({ json: value });
  });
  await choose(page, 'ES02-SLOW');
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await panel.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  await expect(panel.getByRole('status')).toHaveText('전처리 실행 요청 중');
  await expect(panel.getByText('현재 단계: 클립 제작', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true })).toBeEnabled();
  failures = 2;
  await expect(panel.getByRole('alert')).toContainText('상태 조회 연결 끊김', { timeout: 6000 });
  await expect(panel.getByText('현재 단계: 클립 제작', { exact: true })).toBeVisible();
  value = { ...value, current_stage: 'windows' };
  await expect(panel.getByText('현재 단계: 관찰창 결과 정리', { exact: true })).toBeVisible({ timeout: 10000 });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`preprocess-progress-${width}.png`), fullPage: true });
  }
  value = { ...value, status: 'complete', message: '합성 완료', finished_at: '2026-10-12T10:00:03Z' };
  release();
  await expect(panel.getByRole('status')).toContainText('완료 · 합성 완료');
  await page.waitForTimeout(500); const finishedReads = reads;
  await page.waitForTimeout(2300); expect(reads).toBe(finishedReads); expect(posts).toBe(1);
});

test('응답 유실은 접수 조회로 복구하고 새로고침에서 재POST하지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES02-LOST');
  let value = execution(item), accepted = false, posts = 0;
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: accepted ? [value] : [], next_cursor: null } }));
  await page.route(`**${path}`, async route => {
    if (route.request().method() === 'POST') { posts++; accepted = true; value.request_id = route.request().postDataJSON().request_id; await route.abort('failed'); }
    else await route.fulfill({ json: shared(item) });
  });
  await page.route(`**${path}/executions/*`, route => route.fulfill({ json: value }));
  await choose(page, 'ES02-LOST');
  await page.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  await expect(page.getByText('현재 단계: 클립 제작', { exact: true })).toBeVisible();
  await page.reload(); await openMenu(page, '전처리');
  await page.getByRole('row').filter({ hasText: 'ES02-LOST' }).getByRole('button', { name: '상태 확인' }).click();
  await expect(page.getByText('현재 단계: 클립 제작', { exact: true })).toBeVisible();
  value = { ...value, status: 'interrupted', message: '합성 중단' };
  await expect(page.getByRole('status')).toContainText('중단됨 · 합성 중단');
  expect(posts).toBe(1);
});

test('새 실행의 상세를 기다리는 동안 이전 완료 실행을 다시 표시하지 않는다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-NEW-DETAIL');
  const previous = { ...execution(item, 'previous-execution'), status: 'complete', message: '이전 완료 실행' };
  const current = { ...execution(item, 'new-execution'), message: '새 실행 진행 중' };
  await page.evaluate(({ key, id }) => sessionStorage.setItem(key, JSON.stringify({ executionId: id })),
    { key: `kdog-preprocess:operator:${item.case_id}:${item.selected_session_id}:current`, id: previous.execution_id });
  let waiting = false, release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: [], next_cursor: null } }));
  await page.route(`**${path}`, route => route.fulfill({ json: route.request().method() === 'POST' ? { batch_id: current.execution_id } : shared(item) }));
  await page.route(`**${path}/executions/*`, async route => {
    if (route.request().url().endsWith('/' + current.execution_id)) { waiting = true; await gate; await route.fulfill({ json: current }); }
    else await route.fulfill({ json: previous });
  });
  await choose(page, 'AC02-NEW-DETAIL');
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await expect(panel.getByRole('status')).toContainText('완료 · 이전 완료 실행');
  await panel.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  await expect.poll(() => waiting).toBe(true);
  try {
    await expect(panel.getByRole('status')).toHaveText('전처리 실행 요청 중');
    await expect(panel.getByText('현재 단계: 클립 제작', { exact: true })).toHaveCount(0);
  } finally { release(); }
  await expect(panel.getByRole('status')).toContainText('실행 중 · 새 실행 진행 중');
});

test('같은 회차 입력판 변경은 늦은 POST를 버리고 원래 접수 요청으로만 복구한다', async ({ page }) => {
  const { item, path } = await setup(page, 'AC02-PREPROCESS-REVISION');
  let revision = item.input_revision, posts = 0, details = 0, request: any = null, release!: () => void;
  const lookups: string[] = [], gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/api/cases/${item.case_id}/sessions`, async route => {
    const response = await route.fetch(), changed = await response.json();
    revision = changed.input_revision;
    await route.fulfill({ response, json: changed });
  });
  await page.route('**/api/preprocess-s1/executions?**', route => {
    const id = new URL(route.request().url()).searchParams.get('request_id');
    if (id) lookups.push(id);
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.route(`**${path}`, async route => {
    if (route.request().method() === 'POST') {
      posts++; request = route.request().postDataJSON(); await gate;
      await route.fulfill({ json: { batch_id: 'late-revision-execution' } });
    } else await route.fulfill({ json: { ...shared(item), input_revision: revision } });
  });
  await page.route(`**${path}/executions/*`, route => {
    details++;
    return route.fulfill({ json: { ...execution(item, 'late-revision-execution'), message: '버려야 할 이전 입력판 실행' } });
  });
  await choose(page, 'AC02-PREPROCESS-REVISION');
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await panel.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  const key = `kdog-preprocess:operator:${item.case_id}:${item.selected_session_id}:current`;
  let original: string | null;
  try {
    await expect.poll(() => posts).toBe(1);
    original = await page.evaluate(key => sessionStorage.getItem(key), key);
    expect(JSON.parse(original!).request.expected_revision).toBe(item.input_revision);
    const changed = page.waitForResponse(response => response.url().endsWith(`/cases/${item.case_id}/sessions`) && response.request().method() === 'POST');
    await page.getByLabel('선택 세션', { exact: true }).selectOption(item.selected_session_id);
    expect((await changed).status()).toBe(200);
    expect(revision).toBeGreaterThan(item.input_revision);
    await expect(panel.getByRole('status')).toHaveText('요청 접수 여부 확인 중');
    await expect(panel.getByRole('button', { name: 'CAM1 우선순위 내리기', exact: true })).toBeEnabled();
    await expect.poll(() => lookups.length).toBeGreaterThan(0);
  } catch (error) { release(); throw error; }
  const lateResponse = page.waitForResponse(response => response.url().endsWith(path) && response.request().method() === 'POST');
  release(); await (await lateResponse).finished();
  const refreshed = page.waitForResponse(response => response.url().endsWith(path) && response.request().method() === 'GET');
  await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
  await (await refreshed).finished();
  await expect(panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true })).toBeEnabled();
  await expect(panel.getByRole('status')).toHaveText('요청 접수 여부 확인 중');
  await expect(panel.getByRole('alert')).toHaveCount(0);
  expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBe(original!);
  expect(request.expected_revision).toBe(item.input_revision);
  expect(lookups.every(id => id === request.request_id)).toBe(true);
  expect(posts).toBe(1); expect(details).toBe(0);
});

for (const sharedFailure of [403, 404, 503]) {
  test(`공유 준비 상태 ${sharedFailure}는 지정 실행을 보존하고 상세 접근 상실만 정리한다`, async ({ page }) => {
    const { item, path } = await setup(page, `AC02-SHARED-${sharedFailure}`);
    const value = { ...execution(item), status: 'complete', message: '보존할 지정 실행' };
    const key = `kdog-preprocess:operator:${item.case_id}:${item.selected_session_id}:current`;
    await page.evaluate(({ key, id }) => sessionStorage.setItem(key, JSON.stringify({ executionId: id })), { key, id: value.execution_id });
    let detailLost = false;
    await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.route(`**${path}`, route => route.fulfill({ status: sharedFailure, json: { detail: '공유 준비 조회 실패' } }));
    await page.route(`**${path}/executions/*`, route => detailLost
      ? route.fulfill({ status: 404, json: { detail: '지정 실행 접근 상실' } }) : route.fulfill({ json: value }));
    await choose(page, `AC02-SHARED-${sharedFailure}`);
    const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
    await expect(panel.getByRole('status')).toContainText('완료 · 보존할 지정 실행');
    await expect(panel.getByRole('alert')).toContainText('공유 준비 조회 실패 지정 실행 결과는 보존됩니다.');
    await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toBeDisabled();
    detailLost = true;
    await panel.getByRole('button', { name: '전처리 상태 새로고침', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('지정 실행 접근 상실');
    await expect(panel.getByRole('status')).not.toContainText('보존할 지정 실행');
    expect(await page.evaluate(key => sessionStorage.getItem(key), key)).toBeNull();
  });
}

test('늦은 running 조회가 POST 완료를 되돌리지 않고 메뉴 이동 뒤 응답을 버린다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES02-LATE');
  let value = execution(item), accepted = false, delayed = false, detailReads = 0;
  let finishPost!: () => void, finishRead!: () => void;
  const postWait = new Promise<void>(resolve => { finishPost = resolve; });
  const readWait = new Promise<void>(resolve => { finishRead = resolve; });
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: accepted ? [value] : [], next_cursor: null } }));
  await page.route(`**${path}`, async route => {
    if (route.request().method() === 'POST') { accepted = true; value.request_id = route.request().postDataJSON().request_id; await postWait; await route.fulfill({ json: { batch_id: value.execution_id } }); }
    else await route.fulfill({ json: shared(item) });
  });
  await page.route(`**${path}/executions/*`, async route => {
    detailReads++; const captured = { ...value };
    if (detailReads === 2) { delayed = true; await readWait; }
    await route.fulfill({ json: captured });
  });
  await choose(page, 'ES02-LATE');
  await page.getByRole('button', { name: '새 클립으로 전처리', exact: true }).click();
  await expect(page.getByText('현재 단계: 클립 제작', { exact: true })).toBeVisible();
  await expect.poll(() => delayed).toBe(true);
  value = { ...value, status: 'complete', message: '확정 완료' }; finishPost();
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await expect(panel.getByRole('status')).toContainText('완료 · 확정 완료'); finishRead();
  await page.waitForTimeout(300); await expect(panel.getByRole('status')).toContainText('완료 · 확정 완료');
  await openMenu(page, '설문 현황');
  await expect(page.getByRole('region', { name: '다중 카메라 전처리', exact: true })).toHaveCount(0);
});

test('이전 회차의 지정 실행과 현재 저장 회차를 구분한다', async ({ page }) => {
  const { item, path } = await setup(page, 'ES02-HISTORY');
  const value = { ...execution(item), status: 'complete', message: '이전 회차 완료', outdated: true };
  const changed = await page.request.post(`/api/cases/${item.case_id}/sessions`, { headers, data: { expected_revision: item.input_revision, note: '합성 2회차' } });
  expect(changed.status()).toBe(200);
  await page.route('**/api/preprocess-s1/executions?**', route => route.fulfill({ json: { items: [value], next_cursor: null } }));
  await page.route(`**${path}`, route => route.fulfill({ json: shared(item, 'not_ready') }));
  await page.route(`**${path}/executions/*`, route => route.fulfill({ json: value }));
  await openMenu(page, '전처리');
  await page.getByRole('row').filter({ hasText: 'ES02-HISTORY' }).getByRole('button', { name: '상세 보기' }).click();
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await expect(panel.getByRole('status')).toContainText('완료 · 이전 회차 완료');
  await page.waitForTimeout(3200);
  await expect(panel.getByRole('status')).toContainText('완료 · 이전 회차 완료');
  await expect(page.getByText('ES02-HISTORY · 보존된 1회차 실행 · operator', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toHaveCount(0);
});

test('더 보기의 running을 계속 조회하고 느린 페이지 요청 중에도 폴링을 복구한다', async ({ page }) => {
  const { item } = await setup(page, 'ES02-PAGES');
  const base = execution(item);
  let later = { ...base, execution_id: 'page-second', participant_id: 'ES02-PAGE-SECOND' }, firstReads = 0, secondReads = 0;
  await page.route('**/api/preprocess-s1/executions?**', async route => {
    if (new URL(route.request().url()).searchParams.has('cursor')) {
      secondReads++;
      if (secondReads === 1) await new Promise(resolve => setTimeout(resolve, 2300));
      await route.fulfill({ json: { items: [later], next_cursor: null } });
    } else {
      firstReads++;
      await route.fulfill({ json: { items: [{ ...base, status: firstReads === 1 ? 'running' : 'complete', participant_id: 'ES02-PAGE-FIRST' }], next_cursor: 123 } });
    }
  });
  await openMenu(page, '전처리'); await page.getByRole('button', { name: '더 보기', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'ES02-PAGE-SECOND' })).toContainText('실행 중');
  await expect.poll(() => firstReads).toBeGreaterThan(1);
  later = { ...later, status: 'complete', message: '추가 페이지 완료' };
  await expect(page.getByRole('row').filter({ hasText: 'ES02-PAGE-SECOND' })).toContainText('완료', { timeout: 8000 });
  await expect(page.getByRole('row').filter({ hasText: 'ES02-PAGE-FIRST' })).toHaveCount(1);
});

test('느린 목록 조회 중 수동 새로고침을 반복해도 메뉴 이동에서 예약을 정리한다', async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).es02TimerCallbacks = 0;
    const original = window.setTimeout.bind(window);
    window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: any[]) => original(() => {
      if (delay === 2000) (window as any).es02TimerCallbacks++;
      if (typeof handler === 'function') handler(...args);
    }, delay)) as typeof window.setTimeout;
  });
  await setup(page, 'ES02-TIMER');
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/preprocess-s1/executions?**', async route => { await wait; await route.fulfill({ json: { items: [], next_cursor: null } }); });
  await openMenu(page, '전처리');
  const refresh = page.getByRole('button', { name: '내 실행 새로고침', exact: true });
  await refresh.click(); await refresh.click(); await openMenu(page, '설문 현황');
  await page.waitForTimeout(4500);
  expect(await page.evaluate(() => (window as any).es02TimerCallbacks)).toBe(0);
  release();
});

test('느린 목록 조회가 완료되면 수동 갱신의 대기 타이머도 취소한다', async ({ page }) => {
  await setup(page, 'ES02-FINISH-TIMER');
  let release!: () => void, reads = 0;
  const wait = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/preprocess-s1/executions?**', async route => { reads++; await wait; await route.fulfill({ json: { items: [], next_cursor: null } }); });
  await openMenu(page, '전처리');
  const refresh = page.getByRole('button', { name: '내 실행 새로고침', exact: true });
  await refresh.click(); await refresh.click(); release();
  await expect(page.getByRole('heading', { name: '아직 실행한 전처리가 없습니다.' })).toBeVisible();
  await page.waitForTimeout(2500); expect(reads).toBe(1);
});
