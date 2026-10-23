import { test, expect } from '@playwright/test';

test('재촬영은 새 회차로 열리고 촬영 이력은 기존 설문과 미저장 입력을 보존한다', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  const headers = { 'X-KDOG-Request': '1' };
  const participant = `HISTORY-${testInfo.repeatEachIndex}`;
  const created = await page.request.post('/api/cases', { headers, data: { event_id: 'HISTORY', participant_id: participant, dog_name: '이력 합성견' } });
  expect(created.status()).toBe(201);
  const item = await created.json();
  const saved = await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: {
    expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3',
    answers: Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, i === 0 ? 3 : null])),
  } });
  expect(saved.ok(), await saved.text()).toBe(true);
  await page.reload();
  await page.getByRole('button', { name: `${participant} 촬영 기록`, exact: true }).click();
  const context = page.getByRole('region', { name: '선택 참가자', exact: true });
  const tabs = page.getByRole('navigation', { name: '참가자 작업' });
  await expect(context.getByRole('heading')).toContainText('1차 촬영');
  await expect(context.getByRole('combobox')).toHaveCount(0);
  await expect(context.getByText(/^촬영 이력/)).toHaveCount(0);
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '영상 등록', exact: true }).click();
  await page.getByText('새로 촬영한 영상을 등록할 때', { exact: true }).click();
  await page.getByRole('button', { name: '새 촬영 회차 만들기', exact: true }).click();
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true }).getByRole('heading')).toContainText('2차 촬영');
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '촬영 기록', exact: true }).click();
  await expect(context.getByRole('heading')).toContainText('2차 촬영');
  await tabs.getByRole('button', { name: '설문 확인', exact: true }).click();
  await expect(page.locator('.survey-summary')).toHaveText('전체 28문항 · 응답 0개 · 미응답 28개 · 해당 없음 0개');
  await expect(page.locator('.survey-responses td[data-label="미응답 사유"]')).toHaveText(Array(28).fill('사유 미입력'));
  // A poll that started before the session change must not restore its old input revision.
  let release!: () => void, started!: () => void, held = false;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const oldRead = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/api/cases', async route => {
    if (held) { await route.continue(); return; }
    held = true;
    const response = await route.fetch();
    started(); await gate;
    await route.fulfill({ response });
  });
  await oldRead;
  await context.getByText('촬영 이력 (2회)', { exact: true }).click();
  await context.getByRole('button', { name: '1차 촬영 열기', exact: true }).click();
  await expect(context.getByRole('heading')).toContainText('1차 촬영');
  await expect(page.locator('.survey-summary')).toHaveText('전체 28문항 · 응답 1개 · 미응답 27개 · 해당 없음 0개');
  await expect(page.getByRole('status').filter({ hasText: '처리 중입니다' })).toHaveCount(0);
  const lateRead = page.waitForResponse(response => response.url().endsWith('/api/cases'));
  release(); await (await lateRead).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await context.getByRole('heading').textContent()).toContain('1차 촬영');
  await expect(page.locator('.survey-responses tbody tr').first().locator('td[data-label="응답"]')).toHaveText('3');
  await tabs.getByRole('button', { name: '촬영 기록', exact: true }).click();
  await page.getByText('촬영 메모 (선택)', { exact: true }).evaluate(element => { element.closest('details')!.open = true; });
  await page.getByRole('textbox', { name: '촬영 메모', exact: true }).fill('이력 이동 전 미저장 입력');
  await context.getByText('촬영 이력 (2회)', { exact: true }).click();
  page.once('dialog', dialog => dialog.dismiss());
  await context.getByRole('button', { name: '2차 촬영 열기', exact: true }).click();
  await expect(context.getByRole('heading')).toContainText('1차 촬영');
  await expect(page.getByRole('textbox', { name: '촬영 메모', exact: true })).toHaveValue('이력 이동 전 미저장 입력');
  const before = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(before.selected_session_id).toBe(item.selected_session_id);
  page.once('dialog', dialog => dialog.accept());
  await context.getByRole('button', { name: '2차 촬영 열기', exact: true }).click();
  await expect(context.getByRole('heading')).toContainText('2차 촬영');
  await page.getByText('촬영 메모 (선택)', { exact: true }).click();
  await expect(page.getByRole('textbox', { name: '촬영 메모', exact: true })).toHaveValue('');
  const after = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(after.manifest.sessions).toHaveLength(2);
  expect(after.manifest.sessions[0].survey.s01).toBe(3);
  expect(after.manifest.sessions[1].survey.s01).toBeNull();
  await page.setViewportSize({ width: 390, height: 800 });
  await context.getByText('촬영 이력 (2회)', { exact: true }).click();
  await expect(context.getByRole('button', { name: '1차 촬영 열기', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await context.screenshot({ path: testInfo.outputPath('session-history-mobile.png') });
});
