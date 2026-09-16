import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function login(page: Page, username = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
}

test('shell: favicon and identifier constraints are valid', async ({ page }) => {
  const patternErrors: string[] = [];
  page.on('console', message => {
    if (message.type() === 'error' && message.text().startsWith('Pattern attribute value')) patternErrors.push(message.text());
  });
  await login(page);
  const inputs = page.locator('input[pattern]');
  await expect(inputs).toHaveCount(2);
  for (const input of await inputs.all()) {
    await input.fill('invalid!');
    expect(await input.evaluate(element => (element as HTMLInputElement).checkValidity())).toBe(false);
    await input.fill('VALID_ID-1');
    expect(await input.evaluate(element => (element as HTMLInputElement).checkValidity())).toBe(true);
  }
  expect(patternErrors).toEqual([]);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon.svg');
  const favicon = await page.request.get('/favicon.svg');
  expect(favicon.status()).toBe(200);
  expect(favicon.headers()['content-type']).toContain('image/svg+xml');
});

test('desktop: registration, two video files, survey from CSV, refresh and retake', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  await page.getByLabel('행사 ID', { exact: true }).fill('BROWSER-TEST');
  await page.getByLabel('참가자 ID', { exact: true }).fill('0001');
  await page.getByLabel('반려견 이름').fill('검증용 가상견');
  await page.getByRole('button', { name: '참가자 저장' }).click();
  await expect(page.getByRole('heading', { name: '검증용 가상견' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '자료 사용 동의' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '영상 등록', exact: true })).toBeDisabled();
  await expect(page.getByText('입력 버전 1', { exact: true })).toBeVisible();
  for (const index of [1, 2]) {
    await page.getByLabel('영상 파일', { exact: true }).setInputFiles({
      name: `synthetic-file-${index}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic bytes ${index}`),
    });
    await page.getByRole('button', { name: '영상 등록', exact: true }).click();
    await expect(page.getByText(`입력 버전 ${index + 1}`, { exact: true })).toBeVisible();
  }
  await page.getByText('설문 원응답', { exact: false }).first().click();
  await expect(page.getByText('설문은 「자료 가져오기」에서 CSV·Excel로 등록합니다.', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-detail.png'), fullPage: true, animations: 'disabled' });
  // Surveys are registered from a spreadsheet, never typed item by item.
  const version = (await (await page.request.get('/api/catalog/survey')).json()).version;
  const ids = Array.from({ length: 28 }, (_, i) => `s${String(i + 1).padStart(2, '0')}`);
  const values = ids.map(id => id === 's08' ? 'NA' : id === 's23' ? '5' : '3');
  await page.getByRole('button', { name: '자료 가져오기', exact: true }).click();
  await page.getByRole('combobox', { name: '자료 종류' }).selectOption('survey');
  await page.getByLabel('입력 파일', { exact: true }).setInputFiles({ name: 'synthetic-survey.csv', mimeType: 'text/csv',
    buffer: Buffer.from(['event_id,participant_id,survey_version,' + ids.join(','), `BROWSER-TEST,0001,${version},` + values.join(',')].join('\n')) });
  await page.getByRole('button', { name: '검증 미리보기' }).click();
  await expect(page.getByText('검증 결과 · 정상 1행 / 오류 0행')).toBeVisible();
  await page.getByRole('button', { name: '정상 1행 저장' }).click();
  await expect(page.getByText('1개 정상 행을 저장했습니다.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '참가자 자료', exact: true })).toBeVisible();
  await expect(page.getByText('28/28', { exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '2개', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-list.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '0001 상세 열기' }).click();
  await expect(page.getByText('synthetic-file-2.mp4', { exact: true })).toBeVisible();
  await page.getByText('설문 원응답', { exact: false }).first().click();
  await expect(page.getByText('사회화 시기에 다양한 경험을 하도록 노력했다 · 해당 없음', { exact: false })).toBeVisible();
  await page.getByText('재촬영 세션 추가', { exact: true }).click();
  await page.getByRole('button', { name: '새 촬영 시작' }).click();
  await expect(page.getByText('입력 버전 5', { exact: true })).toBeVisible();
  await expect(page.getByText('0 FILES', { exact: true })).toBeVisible();
  await page.getByLabel('선택 세션', { exact: true }).selectOption({ index: 0 });
  await expect(page.getByText('2 FILES', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('360px: standard CSV preview, row errors, save and detail access', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  await page.getByRole('button', { name: '자료 가져오기', exact: true }).click();
  await page.getByLabel('입력 파일', { exact: true }).setInputFiles({
    name: 'synthetic-participants.csv', mimeType: 'text/csv',
    buffer: Buffer.from('event_id,participant_id,dog_name,reservation_at\nMOBILE,0002,모바일 가상견,\nMOBILE,0002,중복 가상견,\n'),
  });
  await page.getByRole('button', { name: '검증 미리보기' }).click();
  await expect(page.getByText('검증 결과 · 정상 1행 / 오류 1행')).toBeVisible();
  await page.getByRole('button', { name: '정상 1행 저장' }).click();
  await expect(page.getByText('1개 정상 행을 저장했습니다.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '참가자', exact: true }).click();
  await page.getByLabel('검색', { exact: true }).fill('0002');
  await page.getByRole('button', { name: '0002 상세 열기' }).click();
  await expect(page.getByRole('heading', { name: '모바일 가상견' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mobile-detail.png'), fullPage: true, animations: 'disabled' });
  await page.getByText('삭제 요청 접수', { exact: true }).click();
  await page.getByLabel('삭제 요청됨', { exact: true }).check();
  await page.getByRole('button', { name: '삭제 요청 저장' }).click();
  await expect(page.getByRole('heading', { name: '참가자 자료', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '0002 상세 열기' })).toHaveCount(0);
});

test('developer session cannot read participant data and reviewer cannot write', async ({ page }) => {
  await login(page, 'developer');
  await expect(page.getByRole('heading', { name: '개발 설정' })).toBeVisible();
  expect((await page.request.get('/api/cases')).status()).toBe(403);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await login(page, 'reviewer');
  await expect(page.getByRole('heading', { name: '참가자 자료', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '자료 가져오기', exact: true })).toHaveCount(0);
  expect((await page.request.post('/api/cases', { headers: { 'X-KDOG-Request': '1' }, data: {} })).status()).toBe(403);
});

test('M3: developer selects independent providers and settings survive reload', async ({ page }, testInfo) => {
  await login(page, 'developer');
  await page.getByLabel('반려견 평가 공급자', { exact: true }).selectOption('openai');
  await page.getByLabel('반려견 평가 모델', { exact: true }).fill('gpt-fixture-only');
  await page.getByLabel('보호자 평가 공급자', { exact: true }).selectOption('anthropic');
  await page.getByLabel('보호자 평가 모델', { exact: true }).fill('claude-fixture-only');
  await page.getByRole('button', { name: '새 실행에 평가 설정 적용' }).click();
  await expect(page.getByText('새 실행에 적용했습니다. 기존 실행 설정은 보존됩니다.', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('반려견 평가 공급자', { exact: true })).toHaveValue('openai');
  await expect(page.getByLabel('보호자 평가 모델', { exact: true })).toHaveValue('claude-fixture-only');
  await page.screenshot({ path: testInfo.outputPath('m3-developer-settings.png'), fullPage: true, animations: 'disabled' });
  for (const branch of ['반려견', '보호자']) {
    await page.getByLabel(`${branch} 평가 공급자`, { exact: true }).selectOption('gemini');
    await page.getByLabel(`${branch} 평가 모델`, { exact: true }).fill('gemini-test-only');
  }
  await page.getByRole('button', { name: '새 실행에 평가 설정 적용' }).click();
  await expect(page.getByText('새 실행에 적용했습니다. 기존 실행 설정은 보존됩니다.', { exact: true })).toBeVisible();
});
