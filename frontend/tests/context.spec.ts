import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };

test('72명 목록에서 업무 맥락 유지 및 공통 업무 계정의 회차 조회·촬영 입력', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  for (let i = 0; i < 73; i++) {
    const response = await page.request.post('/api/cases', { headers, data: {
      event_id: i === 72 ? 'CTX-B' : 'CTX-A', participant_id: `C${String(i === 72 ? 71 : i).padStart(3, '0')}`,
      dog_name: i === 72 ? '다른행사견' : `맥락견${i}`, sequence_no: i === 72 ? 1 : i + 1,
    } });
    expect(response.status()).toBe(201);
    expect((await response.json()).manifest.schema_version).toBe('intake-4.0');
  }
  let item = (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string; participant_id: string }) => c.event_id === 'CTX-A' && c.participant_id === 'C071');
  const firstSession = item.selected_session_id;
  const version = (await (await page.request.get('/api/catalog/survey')).json()).version;
  item = await (await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: { expected_revision: item.input_revision, session_id: firstSession, survey_version: version, answers: Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, 3])) } })).json();
  item = await (await page.request.post(`/api/cases/${item.case_id}/sessions`, { headers, data: { expected_revision: item.input_revision, note: '두 번째 회차' } })).json();
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByLabel('계정', { exact: true }).fill('reviewer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByLabel('행사 필터').selectOption('CTX-A');
  await page.getByRole('button', { name: 'C000 상세 열기' }).click();
  const context = page.getByLabel('선택 참가자');
  await expect(context.getByRole('heading')).toBeInViewport();
  await expect(context.getByRole('heading')).toBeFocused();
  await page.getByRole('button', { name: '전체 목록으로 돌아가기' }).click();
  await page.getByLabel('검색', { exact: true }).fill('C071');
  await page.getByRole('button', { name: 'C071 상세 열기' }).click();
  await expect(context).toContainText('CTX-A / C071 / 맥락견71 / 2차 촬영');
  await expect(context.getByRole('heading')).toBeInViewport();
  await page.getByText(/^촬영 이력 \(/).click();
  await page.getByRole('button', { name: '1차 촬영 열기', exact: true }).click();
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true }).getByRole('heading')).toContainText('1차 촬영');
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '설문 확인', exact: true }).click();
  await expect(page.getByLabel('설문 확인')).toContainText('수치 응답 28/28 · 명시 빈칸 사유 0개 · 등록 완료 기준 미확정');
  await expect(context).toContainText('1차 촬영');
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '촬영 기록', exact: true }).click();
  await expect(page.getByRole('region', { name: '촬영 기록', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '실제 촬영 절차', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '업로드 시작·재시도', exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(context.getByRole('heading')).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('reviewer-context-768.png'), fullPage: true });
  const unchanged = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(unchanged.input_revision).toBe(item.input_revision + 1);
  expect(unchanged.selected_session_id).toBe(firstSession);
  await page.getByRole('button', { name: '전체 목록으로 돌아가기' }).click();
  await expect(page.getByLabel('검색', { exact: true })).toHaveValue('C071');
  await expect(page.getByLabel('행사 필터')).toHaveValue('CTX-A');

});
