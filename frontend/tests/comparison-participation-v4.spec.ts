import { test, expect } from '@playwright/test';
import { openMenu } from './menu';

// All participants and answers are synthetic.
test('CM02 설문 상세에서 참여쌍 연결·최초 제출·재방문·정정·제외를 명시 기록한다', async ({ page }, testInfo) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const headers = { 'X-KDOG-Request': '1' }, event = `CM02-${Date.now()}`;
  const answers = Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, 3]));
  const created = [];
  for (const [index, name] of ['참여 합성견', '참여 합성견 둘째'].entries()) {
    const response = await page.request.post('/api/cases', { headers, data: { event_id: event, participant_id: `${event}-00${index + 1}`, dog_name: name } });
    expect(response.status()).toBe(201);
    const item = await response.json();
    const survey = await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: {
      expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3',
      answers: { ...answers, s10: 1, s11: 2, s13: null }, not_applicable: [], blank_reasons: { s13: '합성 미경험' } } });
    expect(survey.ok()).toBeTruthy();
    created.push(item);
  }
  await page.reload();
  await page.getByRole('button', { name: `${event}-001 상세 열기`, exact: true }).click();
  await openMenu(page, '설문 현황');
  const panel = page.getByRole('region', { name: '누적 비교 참여' });
  await expect(panel).toContainText('아직 참여쌍에 연결되지 않았습니다');
  await expect(panel.getByRole('button', { name: '새 참여쌍 만들기' })).toBeDisabled();
  await panel.getByLabel('참여 근거·사유').fill('합성 현장 확인');
  await panel.getByRole('button', { name: '새 참여쌍 만들기' }).click();
  await expect(panel.getByRole('status')).toHaveText('새 참여쌍을 만들었습니다.');
  await expect(panel).toContainText('대표 설문 미확정');
  await panel.getByLabel('참여 근거·사유').fill('합성 최초 제출 확인');
  await panel.getByRole('button', { name: '현재 설문을 최초 제출로 기록' }).click();
  await expect(panel).toContainText('대표 설문 확정');
  await expect(panel).toContainText('대표: 최초 제출 · 입력 판본');
  await panel.getByLabel('참여 근거·사유').fill('합성 재방문');
  await panel.getByRole('button', { name: '재방문 설문으로 기록' }).click();
  await expect(panel.getByRole('status')).toHaveText('재방문을 기록했습니다.');
  await expect(panel).toContainText('대표: 최초 제출');
  await panel.getByText('제출 기록 2건').click();
  await expect(panel.getByText(/재방문 · 입력 판본/)).toBeVisible();
  const inventory = await (await page.request.get(`/api/comparisons-s1/pairs?case_id=${created[0].case_id}`)).json();
  const pair = inventory.pairs.find((item: { pair_id: string }) => item.pair_id === inventory.case_pair_id);
  const stale = await page.request.post(`/api/comparisons-s1/pairs/${pair.pair_id}/state`, { headers, data: { request_id: `stale-${event}`, expected_revision: pair.revision - 1, status: 'excluded', reason: '오래된 판본' } });
  expect(stale.status()).toBe(409);
  await panel.getByLabel('참여 근거·사유').fill('합성 오입력 정정');
  await panel.getByRole('button', { name: '오입력 정정으로 대표 교체' }).click();
  await expect(panel).toContainText('대표: 오입력 정정');
  await panel.getByLabel('참여 근거·사유').fill('합성 제외 사유');
  await panel.getByRole('button', { name: '누적 비교에서 제외' }).click();
  await expect(panel).toContainText('누적 비교 제외');
  await expect(panel).toContainText('제외 사유: 합성 제외 사유');
  await expect(panel.getByRole('button', { name: '재방문 설문으로 기록' })).toHaveCount(0);
  expect(await page.locator('main').innerText()).not.toContain(pair.pair_id);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('comparison-participation-390.png'), fullPage: true });
  expect(errors).toEqual([]);
});
