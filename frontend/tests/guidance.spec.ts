import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
test.afterEach(async ({ page }) => {
  for (const item of (await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'GUIDE')) {
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  }
});

test('신규 접수 입력은 이동 취소와 저장 오류 뒤에도 유지된다', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  await page.getByLabel('행사 ID', { exact: true }).fill('GUIDE');
  await page.getByLabel('참가자 ID', { exact: true }).fill('new');
  await page.getByLabel('반려견 이름', { exact: true }).fill('입력보호견');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByLabel('반려견 이름', { exact: true })).toHaveValue('입력보호견');
  await page.route('**/api/cases', async route => {
    if (route.request().method() === 'POST') await route.fulfill({ status: 409, json: { detail: '이미 등록된 참가자 ID입니다.' } });
    else await route.continue();
  });
  await page.getByRole('button', { name: '참가자 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('이미 등록된');
  await expect(page.getByLabel('반려견 이름', { exact: true })).toHaveValue('입력보호견');
  await page.unroute('**/api/cases');
  await page.getByRole('button', { name: '참가자 저장', exact: true }).click();
  await expect(page.getByRole('heading', { name: '입력보호견', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByRole('heading', { name: '설문', exact: true })).toBeVisible();
});

test('NA 3개와 빈칸 3개의 설문 등록 상태를 구별한다', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  const version = (await (await page.request.get('/api/catalog/survey')).json()).version;
  for (const id of ['na', 'blank']) {
    const item = await (await page.request.post('/api/cases', { headers, data: { event_id: 'GUIDE', participant_id: id, dog_name: '설문안내견' } })).json();
    await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: { expected_revision: item.input_revision, session_id: item.selected_session_id,
      survey_version: version, answers: Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, i >= 6 && i <= 8 ? null : 3])), not_applicable: id === 'na' ? ['s07', 's08', 's09'] : [] } });
  }
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await page.getByRole('button', { name: 'na 설문 현황 열기' }).click();
  await expect(page.getByLabel('설문 현황')).toContainText('등록 28/28 · 응답 25 · 해당 없음 3 · 미응답 0');
  await page.screenshot({ path: testInfo.outputPath('survey-na-guidance.png'), fullPage: true });
  await page.getByRole('button', { name: '전체 목록으로 돌아가기' }).click();
  await page.getByRole('button', { name: 'blank 설문 현황 열기' }).click();
  await expect(page.getByLabel('설문 현황')).toContainText('등록 25/28 · 응답 25 · 해당 없음 0 · 미응답 3');
});
