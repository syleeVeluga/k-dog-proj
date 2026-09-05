import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function login(page: Page, username = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
}

test('desktop: registration, consent, two cameras, survey, refresh and retake', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  await page.getByLabel('행사 ID', { exact: true }).fill('BROWSER-TEST');
  await page.getByLabel('참가자 ID', { exact: true }).fill('0001');
  await page.getByLabel('반려견 이름').fill('검증용 가상견');
  await page.getByRole('button', { name: '참가자 저장' }).click();
  await expect(page.getByRole('heading', { name: '검증용 가상견' })).toBeVisible();
  await page.getByLabel('영상·음성 분석', { exact: true }).check();
  await page.getByLabel('동의 문구 버전').fill('synthetic-consent-v1');
  await page.getByLabel('동의 기록 시각').fill('2026-09-06T10:00');
  await page.getByRole('button', { name: '동의 상태 저장' }).click();
  await expect(page.getByText('입력 버전 2', { exact: true })).toBeVisible();
  for (const camera of [1, 2]) {
    await page.getByLabel('카메라 ID').fill(`CAM-${camera}`);
    await page.getByLabel('영상 파일', { exact: true }).setInputFiles({
      name: `synthetic-camera-${camera}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic bytes ${camera}`),
    });
    await page.getByRole('button', { name: '영상 등록', exact: true }).click();
    await expect(page.getByText(`입력 버전 ${camera + 2}`, { exact: true })).toBeVisible();
  }
  await page.getByText('설문 원응답', { exact: false }).first().click();
  for (let i = 1; i <= 30; i++) await page.getByLabel(`q${String(i).padStart(2, '0')} 응답`, { exact: true }).selectOption(i === 23 ? '5' : '3');
  await page.getByRole('button', { name: '설문 저장', exact: true }).click();
  await expect(page.getByText('입력 버전 5', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-detail.png'), fullPage: true, animations: 'disabled' });
  await page.reload();
  await expect(page.getByRole('heading', { name: '참가자 자료', exact: true })).toBeVisible();
  await expect(page.getByText('30/30', { exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '2개', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-list.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '0001 상세 열기' }).click();
  await expect(page.getByText('synthetic-camera-2.mp4', { exact: true })).toBeVisible();
  await page.getByText('재촬영 세션 추가', { exact: true }).click();
  await page.getByRole('button', { name: '새 촬영 시작' }).click();
  await expect(page.getByText('입력 버전 6', { exact: true })).toBeVisible();
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

test('M2: synthetic observation worker, persisted evidence, replay links and 360px', async ({ page }, testInfo) => {
  await login(page);
  const request = page.request;
  const headers = { 'X-KDOG-Request': '1' };
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'M2-BROWSER', participant_id: '0099', dog_name: '관찰 검증용 가상견' } })).json();
  const base = `/api/cases/${item.case_id}`;
  await request.put(`${base}/access`, { headers, data: { expected_revision: item.input_revision, deletion_requested: false,
    consent: { video_analysis: true, external_ai: true, result_provision: true, text_version: 'synthetic-test-only', recorded_at: '2026-09-06T00:00:00+00:00' } } });
  item = await (await request.get(base)).json();
  for (const camera of [1, 2]) {
    const params = new URLSearchParams({ expected_revision: String(item.input_revision), session_id: item.selected_session_id, camera_id: `CAM-${camera}`, filename: 'synthetic.mp4' });
    item = await (await request.post(`${base}/videos?${params}`, { headers, data: Buffer.from(`synthetic fixture ${camera}`) })).json();
  }
  await page.reload();
  await page.getByRole('button', { name: '0099 상세 열기' }).click();
  await page.getByRole('button', { name: '관찰 시작', exact: true }).click();
  await expect(page.getByText('관찰 근거 2개', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('가상 관찰: 입장 시 이동', { exact: true })).toHaveCount(2);
  await page.getByRole('button', { name: '원본 근거 재생' }).first().click();
  await expect(page.locator('section[aria-label="영상 관찰"] video')).toHaveAttribute('src', /#t=1,2$/);
  await page.getByRole('button', { name: '근거 재생 닫기' }).click();
  await page.screenshot({ path: testInfo.outputPath('m2-observations-desktop.png'), fullPage: true, animations: 'disabled' });
  await page.reload();
  await page.getByRole('button', { name: '0099 상세 열기' }).click();
  await expect(page.getByText('관찰 근거 2개', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('m2-observations-mobile.png'), fullPage: true, animations: 'disabled' });
  await page.getByLabel('외부 AI 전송', { exact: true }).uncheck();
  await page.getByRole('button', { name: '동의 상태 저장' }).click();
  await expect(page.getByRole('button', { name: '관찰 시작', exact: true })).toBeDisabled();
  await expect(page.getByText('가상 관찰: 입장 시 이동', { exact: true })).toHaveCount(0);
});
