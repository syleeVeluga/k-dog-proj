import { test, expect } from '@playwright/test';
import { openMenu } from './menu';

test('Gemini slots: stale edits clear secrets, late tests keep references and whole stop clears both slots', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('developer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await openMenu(page, '개발 설정');
  const panel = page.locator('.developer-settings');
  await panel.getByRole('button', { name: '예비키 연결 시험', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Gemini 예비키 연결 시험: 개발자 설정 필요' })).toBeVisible();
  const state = await (await page.request.get('/api/developer/settings')).json();
  const primary = state.gemini_slots.find((slot: { slot: string }) => slot.slot === 'primary');
  const rotated = await page.request.put('/api/developer/keys/gemini/slots/primary', {
    headers: { 'X-KDOG-Request': '1' }, data: { value: 'synthetic-other-editor-key', expected_reference: primary.reference },
  });
  expect(rotated.status()).toBe(200);
  const newReference = (await rotated.json()).reference;
  let submissions = 0;
  page.on('request', request => { if (request.url().endsWith('/keys/gemini/slots/primary') && request.method() === 'PUT') submissions++; });
  const secret = 'synthetic-stale-browser-key';
  await panel.getByLabel('Gemini 주키 API 키').fill(secret);
  await panel.getByRole('button', { name: '주키 등록·교체', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '최신 상태를 확인한 뒤 키를 다시 입력하세요' })).toBeVisible();
  await expect(panel.getByLabel('Gemini 주키 API 키')).toHaveValue('');
  expect(submissions).toBe(1);
  const nextRequest = page.waitForRequest(request => request.url().endsWith('/keys/gemini/slots/primary') && request.method() === 'PUT');
  await panel.getByLabel('Gemini 주키 API 키').fill('synthetic-current-browser-key');
  await panel.getByRole('button', { name: '주키 등록·교체', exact: true }).click();
  expect((await nextRequest).postDataJSON().expected_reference).toBe(newReference);
  await expect(page.getByRole('status').filter({ hasText: 'Gemini 주키를 보호하여 저장했습니다.' })).toBeVisible();
  await panel.getByLabel('Gemini 예비키 API 키').fill('synthetic-backup-browser-key');
  await panel.getByRole('button', { name: '예비키 등록·교체', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Gemini 예비키를 보호하여 저장했습니다.' })).toBeVisible();
  await expect(panel.getByLabel('Gemini 예비키 API 키')).toHaveValue('');
  const backup = (await (await page.request.get('/api/developer/settings')).json()).gemini_slots.find((slot: { slot: string }) => slot.slot === 'backup');
  let completeTest!: () => void;
  const pause = new Promise<void>(resolve => { completeTest = resolve; });
  const arrived = page.waitForRequest('**/api/developer/keys/gemini/slots/backup/test');
  await page.route('**/api/developer/keys/gemini/slots/backup/test', async route => {
    await pause;
    await route.fulfill({ json: { provider: 'gemini', slot: 'backup', reference: backup.reference, status: 'connected', tested_at: new Date().toISOString() } });
  });
  await panel.getByRole('button', { name: '예비키 연결 시험', exact: true }).click();
  await arrived;
  expect((await page.request.put('/api/developer/keys/gemini/slots/backup', { headers: { 'X-KDOG-Request': '1' },
    data: { value: 'synthetic-rotated-backup-ui', expected_reference: backup.reference } })).status()).toBe(200);
  completeTest();
  await expect(page.getByRole('status').filter({ hasText: '교체 전 키 시험 결과입니다' })).toBeVisible();
  await panel.getByRole('button', { name: '주키를 앱에서 제거', exact: true }).click();
  await expect(panel.getByRole('region', { name: 'Gemini 예비키', exact: true }).getByText('앱에 등록됨', { exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Gemini 주키를 앱에서 제거했습니다.' })).toBeVisible();
  expect((await (await page.request.get('/api/developer/settings')).json()).gemini_slots.find((slot: { slot: string }) => slot.slot === 'backup').available).toBe(true);
  expect(await page.locator('body').innerText()).not.toContain(secret);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(secret);
  await page.getByRole('button', { name: '알림 닫기', exact: true }).click();
  for (const width of [390, 1366]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await panel.screenshot({ path: info.outputPath(`gemini-slots-${width}.png`) });
  }
  await panel.getByRole('button', { name: 'Gemini 전체 키 사용 중지', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Gemini 전체 키 사용을 중지했습니다.' })).toBeVisible();
  const finalState = await (await page.request.get('/api/developer/settings')).json();
  expect(finalState.gemini_slots.every((slot: { available: boolean }) => !slot.available)).toBe(true);
  expect(errors).toEqual([]);
});

test('actual server Worker fallback shows roles, retry wait and uncertain cost in scoring and report UI', async ({ page }, info) => {
  test.setTimeout(120000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('developer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const seed = await page.request.post('/api/test-fixtures/gemini-fallback/seed', { headers: { 'X-KDOG-Request': '1' } });
  expect(seed.status(), await seed.text()).toBe(200);
  const source = await seed.json();
  await page.reload();
  await openMenu(page, '독립 채점');
  await page.getByRole('button', { name: 'S1-RUN 독립 채점 열기', exact: true }).click();
  const ai = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(ai.getByText(/예비키 전환 대기/).first()).toBeVisible();
  const advance = await page.request.post('/api/test-fixtures/gemini-fallback/advance', { headers: { 'X-KDOG-Request': '1' } });
  expect(advance.status(), await advance.text()).toBe(200);
  const related = await advance.json();
  await ai.getByRole('button', { name: 'AI 실행 상태 새로고침' }).click();
  await expect(ai.getByText(/예비키 사용/).first()).toBeVisible();
  await ai.getByText('기술 정보 · 단계별 시간·호출·부분 실패', { exact: true }).click();
  await expect(ai.getByText('과금 여부 미확인', { exact: true })).toBeVisible();
  await expect(ai.getByText('공급자 임시 파일 정리 미완료', { exact: true })).toBeVisible();
  const scored = await (await page.request.get(`/api/runs-s1/${source.score_run_id}`)).json();
  expect(scored.reserved_calls).toBe(44);
  expect(scored.credential_slot).toBe('backup');
  expect(JSON.stringify(scored)).not.toContain('credential_reference');
  const complete = await page.request.post('/api/test-fixtures/gemini-fallback/advance', { headers: { 'X-KDOG-Request': '1' } });
  expect(complete.status(), await complete.text()).toBe(200);
  const path = `/api/cases/${source.case_id}/sessions/${source.session_id}`;
  const attachment = await (await page.request.get(`${path}/opinions-s1/attachment-runs/${related.attachment_run_id}`)).json();
  expect(attachment.status).toBe('succeeded');
  expect(attachment.credential_slot).toBe('backup');
  expect(attachment.reserved_calls).toBe(2);
  await openMenu(page, '리포트 발급');
  await expect(page.getByRole('region', { name: '리포트 실행', exact: true })).toBeVisible();
  await expect(page.getByText(/예비키 사용/).first()).toBeVisible();
  await page.getByText('기술 정보 · 단계·시도·시간·재사용', { exact: true }).click();
  await expect(page.getByText('과금 여부 미확인', { exact: true })).toBeVisible();
  const report = await (await page.request.get(`/api/report-runs-s1/${related.report_run_id}`)).json();
  expect(report.status).toBe('succeeded');
  expect(report.credential_slot).toBe('backup');
  expect(report.steps.filter((step: { provider_calls: number }) => step.provider_calls).length).toBe(2);
  await page.screenshot({ path: info.outputPath('gemini-report-role.png'), fullPage: true });
  await openMenu(page, '독립 채점');
  const final = page.getByRole('region', { name: '의견과 최종 결과', exact: true });
  await final.getByRole('button', { name: '현재 의견의 고정 기본 결과 선택', exact: true }).click();
  // Display the real completed standalone run without creating another provider request.
  await page.route(`**${path}/opinions-s1/attachment-runs`, route => route.fulfill({ json: attachment }));
  const standalone = final.getByRole('region', { name: '완료 애착 의견 AI 해석', exact: true });
  await standalone.getByRole('button', { name: '완료 애착 의견을 AI로 해석', exact: true }).click();
  await expect(standalone.getByText(/예비키 사용/).first()).toBeVisible();
  await standalone.getByText('애착 해석 키 사용·시도 기록', { exact: true }).click();
  await expect(standalone.getByText(/주키 사용/).first()).toBeVisible();
  await expect(standalone.getByText('과금 여부 미확인', { exact: true })).toBeVisible();
  // Supplement actual-server coverage with deterministic historical/limit DTOs.
  const localFailure = { credential_slot: 'primary', credential_selected_at: null, fallback_reason: 'primary_removed', fallback_status: 'backup_unavailable' };
  const reused = { ...scored.steps[0], credential_slot: null, credential_selected_at: null, fallback_status: null, fallback_reason: null,
    stage: 'score_v4', key: 'reused-source', attempt: 1, status: 'succeeded', code: null, reused: true, call_reserved: false,
    timing: {}, source_credential_slot: 'backup', source_fallback_reason: 'primary_authentication' };
  const historical = { ...reused, key: 'historical-source', source_credential_slot: null, source_fallback_reason: null };
  const mocked = { ...scored, ...localFailure, status: 'failed', steps: [
    { ...reused, ...localFailure, key: 'local-failure', reused: false }, reused, historical,
    { ...reused, key: 'attempt-limit', reused: false, credential_slot: 'primary', credential_selected_at: '2026-10-14T00:00:00Z', fallback_status: 'attempt_limit' },
    { ...reused, key: 'call-limit', reused: false, fallback_status: 'call_limit' },
  ] };
  await page.route(`**${path}/runs-s1`, route => route.fulfill({ json: [mocked] }));
  await page.route(`**/api/runs-s1/${source.score_run_id}`, route => route.fulfill({ json: mocked }));
  await ai.getByRole('button', { name: 'AI 실행 상태 새로고침' }).click();
  await ai.getByText('기술 정보 · 단계별 시간·호출·부분 실패', { exact: true }).click();
  const local = ai.getByRole('row').filter({ hasText: 'local-failure' });
  await expect(local).toContainText('주키 선택 미완료'); await expect(local).not.toContainText('주키 사용');
  await expect(local).toContainText('예비키 미가용');
  await expect(ai.getByRole('row').filter({ hasText: 'reused-source' })).toContainText('재사용 출처 · 예비키 사용 기록');
  await expect(ai.getByRole('row').filter({ hasText: 'historical-source' })).toContainText('키 역할 기록 없음');
  await expect(ai.getByRole('row').filter({ hasText: 'attempt-limit' })).toContainText('시도 상한 도달');
  await expect(ai.getByRole('row').filter({ hasText: 'call-limit' })).toContainText('호출 상한 도달');
  expect(errors).toEqual([]);
});
