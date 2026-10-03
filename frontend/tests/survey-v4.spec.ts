import { test, expect } from '@playwright/test';

test('S1 설문은 확정 결측·역채점·등록 상태와 외부 승인 대기를 분리한다', async ({ page }, testInfo) => {
  test.skip(process.env.KDOG_TEST_INTAKE_SPEC !== '20261002', 'S1 browser fixture required');
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const headers = { 'X-KDOG-Request': '1' };
  const response = await page.request.post('/api/cases', { headers, data: { event_id: 'SURVEY-S1', participant_id: 'SURVEY-S1-001', dog_name: '설문 합성견' } });
  expect(response.status()).toBe(201);
  const item = await response.json();
  const answers = Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, 3]));
  const survey = await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: {
    expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3',
    answers: { ...answers, s01: null, s10: 0, s11: null, s12: 0, s13: 1, s14: 2, s26: 1, s27: 3, s28: 5 },
    not_applicable: [], blank_reasons: { s01: '합성 미응답', s11: '본 적 없음' },
  } });
  expect(survey.ok()).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: 'SURVEY-S1-001 상세 열기', exact: true }).click();
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByText('수치 응답 26/28', { exact: false })).toContainText('등록 완료 기준 미확정');
  await expect(page.getByText(/S1 집계: 완전응답 영역만 산출/)).toContainText('D06');
  await expect(page.getByText('응답 1/2 · 확정 두려움 묶음 규칙: 하나라도 결측이면 해당 묶음 미산출', { exact: true })).toBeVisible();
  await expect(page.getByText('응답 5/6 · D05 부분 결측 산출 정책 미확정: 부분평균과 0 대체를 적용하지 않음', { exact: true })).toBeVisible();
  await expect(page.getByText('응답 3/3 · 평균 1.00 (분모 3)', { exact: true })).toBeVisible();
  await expect(page.getByText(/s26 원응답 1 → 변환 5/)).toBeVisible();
  await page.getByText('설문 원응답', { exact: false }).click();
  await expect(page.locator('.survey-values p').filter({ has: page.locator('b', { hasText: /^10$/ }) }).locator('strong')).toHaveText('0');
  await expect(page.getByText('빈칸 사유: 본 적 없음', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('survey-v4.png'), fullPage: true });
  expect(errors).toEqual([]);
});
