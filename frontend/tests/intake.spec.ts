import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };


async function login(page: Page, username = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
}

async function openRegistrationWithExistingCase(page: Page, participantId: string) {
  const existing = await page.request.post('/api/cases', { headers,
    data: { event_id: 'BROWSER-TEST', participant_id: participantId, dog_name: '기존 접수 합성견' } });
  expect(existing.status()).toBe(201);
  await page.reload();
  await expect(page.getByRole('button', { name: `${participantId} 상세 열기`, exact: true })).toBeVisible();
  await page.getByText('참가자 등록', { exact: true }).click();
}

test('shell: favicon and identifier constraints are valid', async ({ page }) => {
  const patternErrors: string[] = [];
  page.on('console', message => {
    if (message.type() === 'error' && message.text().startsWith('Pattern attribute value')) patternErrors.push(message.text());
  });
  await login(page);
  await openRegistrationWithExistingCase(page, 'shell-existing');
  // 행사 ID·참가자 ID는 영문·숫자·밑줄·하이픈만 허용하고, 어긋나면 칸 아래에 한국어로 알린다.
  for (const [label, name] of [['행사 ID', 'event_id'], ['참가자 ID', 'participant_id']] as const) {
    const input = page.getByLabel(label, { exact: true });
    await input.fill('invalid!');
    await page.getByLabel('반려견 이름', { exact: true }).focus();
    await expect(page.locator(`#participant-${name}-error`)).toContainText('영문·숫자·밑줄·하이픈만 쓸 수 있습니다');
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await input.fill('VALID_ID-1');
    await expect(page.locator(`#participant-${name}-error`)).toHaveCount(0);
  }
  expect(patternErrors).toEqual([]);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon.svg');
  const favicon = await page.request.get('/favicon.svg');
  expect(favicon.status()).toBe(200);
  expect(favicon.headers()['content-type']).toContain('image/svg+xml');
});

test('desktop: S1 registration, two explicit media links, Forms survey, refresh and retake', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  await openRegistrationWithExistingCase(page, 'desktop-existing');
  await page.getByLabel('행사 ID', { exact: true }).fill('BROWSER-TEST');
  await page.getByLabel('참가자 ID', { exact: true }).fill('0001');
  await page.getByLabel('순번', { exact: true }).fill('1');
  await page.getByLabel('반려견 이름').fill('검증용 가상견');
  await page.getByLabel('보호자명', { exact: true }).fill('가상 보호자');
  await page.getByLabel('견종', { exact: true }).fill('보더콜리');
  await page.getByRole('combobox', { name: '성별' }).selectOption('암');
  await page.getByLabel('나이(세)', { exact: true }).fill('4');
  await page.getByRole('button', { name: '저장하고 상세 열기' }).click();
  await expect(page.getByRole('heading', { name: '검증용 가상견', exact: true })).toBeVisible();
  await expect(page.getByText('가상 보호자 님 · 보더콜리 · 암 · 4세', { exact: true })).toBeVisible();
  await expect(page.getByText('동의 확인', { exact: true })).toHaveCount(0);
  await expect(page.getByText('분석·피드백 동의:', { exact: false })).toHaveCount(0);
  await page.getByText('기술 정보', { exact: true }).click();
  await expect(page.getByText('촬영 기준:', { exact: false })).toContainText('S1.1 · 10월 2일');
  await expect(page.getByText('입력 버전 1', { exact: true })).toBeVisible();
  await expect(page.getByText('영상 등록·8구간 시각·촬영 메모·재촬영은 「촬영」 메뉴에서', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-detail.png'), fullPage: true, animations: 'disabled' });
  await openMenu(page, '영상 파일 업로드');

  await expect(page.getByRole('button', { name: '업로드 시작·재시도', exact: true })).toBeDisabled();
  // Storage-only synthetic bytes exercise receipt/linking, not media decoding or AI quality.
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles([1, 2].map(index => ({ name: `synthetic-file-${index}.mp4`, mimeType: 'video/mp4', buffer: Buffer.from(`synthetic bytes ${index}`) })));
  await page.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  for (const index of [1, 2]) {
    const receipt = page.getByRole('article', { name: `업로드 파일 synthetic-file-${index}.mp4`, exact: true });
    await expect(receipt.getByText('업로드 완료', { exact: true })).toBeVisible();
    await receipt.getByLabel('촬영 카메라 번호', { exact: true }).fill(`${index}`);
    await receipt.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
    const linkedSection = page.locator('details').filter({ has: page.getByText(/^정보 저장 완료한 파일/) }).last();
    if (await linkedSection.getAttribute('open') === null) await linkedSection.getByText(/^정보 저장 완료한 파일/).click();
    await expect(receipt.getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
  }
  await openMenu(page, '촬영 기록 (8구간)');
  await expect(page.getByRole('combobox', { name: '기준 영상', exact: true }).locator('option')).toHaveCount(3);
  const item = (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string; participant_id: string }) => c.event_id === 'BROWSER-TEST' && c.participant_id === '0001');
  const firstSession = item.selected_session_id;
  expect(item.manifest.schema_version).toBe('intake-4.0');
  expect(item.manifest.sessions[0].videos.map((video: { camera_id: string }) => video.camera_id)).toEqual(['CAM1', 'CAM2']);
  // Register source columns and the intended existing session through the actual S1 Forms UI.
  const ids = Array.from({ length: 28 }, (_, i) => `s${String(i + 1).padStart(2, '0')}`);
  const values = ids.map(id => id === 's10' ? '0' : id === 's23' ? '5' : '3');
  await openMenu(page, '일괄 등록 (CSV·Excel)');
  const form = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('BROWSER-TEST');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles({ name: 'synthetic-survey.csv', mimeType: 'text/csv', buffer: Buffer.from([ids.join(','), values.join(',')].join('\n')) });
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 28개' })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await form.getByText(/기존 참가자·회차에 명시적으로 연결/).click();
  await form.getByRole('button', { name: '기존 대상 연결 추가', exact: true }).click();
  await form.getByLabel('연결 1 참가자', { exact: true }).selectOption(item.case_id);
  await expect(form.getByLabel('연결 1 회차', { exact: true })).toHaveValue(firstSession);
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  const committed = page.waitForResponse(response => response.url().endsWith('/api/forms/commit'));
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  expect((await committed).status()).toBe(200);
  await expect(page.getByRole('status').filter({ hasText: '1개 원행의 참가자·설문 등록을 확인했습니다.' })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/#\/intake\/upload$/);
  await openMenu(page, '참가자 접수');
  await expect(page.getByRole('heading', { name: '접수', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: '행사 필터', exact: true }).selectOption('BROWSER-TEST');
  const savedRow = page.getByRole('row').filter({ has: page.getByRole('button', { name: '0001 상세 열기', exact: true }) });
  await expect(savedRow.getByText('28/28', { exact: true })).toBeVisible();
  await expect(savedRow.getByRole('cell', { name: '1', exact: true })).toBeVisible();
  await expect(savedRow.getByRole('cell', { name: '2개 · 사용 가능 0 · 확인 대기 2', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('desktop-list.png'), fullPage: true, animations: 'disabled' });
  await openMenu(page, '촬영 기록 (8구간)');
  await page.getByRole('button', { name: '0001 촬영 열기' }).click();
  await expect(page.getByText('재촬영 세션 추가', { exact: true })).toBeVisible();
  await openMenu(page, '영상 파일 업로드');
  await page.getByText(/^정보 저장 완료한 파일/).click();
  await expect(page.getByRole('article', { name: '업로드 파일 synthetic-file-2.mp4', exact: true }).getByText('등록됨 · 영상 읽기 확인 대기', { exact: true })).toBeVisible();
  await openMenu(page, '촬영 기록 (8구간)');
  await page.getByText('재촬영 세션 추가', { exact: true }).click();
  await page.getByRole('button', { name: '새 촬영 시작' }).click();
  await expect(page.getByRole('combobox', { name: '기준 영상', exact: true }).locator('option')).toHaveCount(1);
  await openMenu(page, '참가자 접수');

  await expect(page.getByText('입력 버전 5', { exact: true })).toBeVisible();
  await page.getByLabel('선택 세션', { exact: true }).selectOption(firstSession);
  await expect(page.getByText('영상 2개 · 구간 없음', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
});

test('360px: Forms duplicate row errors, corrected atomic save and detail access', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  await openMenu(page, '일괄 등록 (CSV·Excel)');
  const form = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('MOBILE');
  for (const duplicate of [true, false]) {
    await form.getByLabel('Forms 파일', { exact: true }).setInputFiles({ name: 'synthetic-participants.csv', mimeType: 'text/csv',
      buffer: Buffer.from(`participant_id,dog_name\n0002,모바일 가상견\n${duplicate ? '0002,중복 가상견\n' : ''}`) });
    await expect(form.getByRole('status').filter({ hasText: '자동 연결 2개' })).toBeVisible();
    await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
    if (duplicate) {
      await expect(form.getByRole('heading', { name: '원행 1개 · 오류 1개', exact: true })).toBeVisible();
      await expect(form.getByRole('button', { name: '정상 1행 등록 · 오류 1행 제외', exact: true })).toBeEnabled();
      expect((await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'MOBILE')).toHaveLength(0);
    }
  }
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('이미 확정한 파일입니다. 재확정해도 참가자가 추가되지 않습니다.')).toBeVisible();
  await openMenu(page, '참가자 접수');
  await page.getByLabel('검색', { exact: true }).fill('0002');
  await page.getByRole('button', { name: '0002 상세 열기' }).click();
  await expect(page.getByRole('heading', { name: '모바일 가상견', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mobile-detail.png'), fullPage: true, animations: 'disabled' });
  await expect(page.getByText('삭제 요청 접수', { exact: true })).toHaveCount(0);
  expect((await page.request.get('/api/cases')).ok()).toBe(true);
});

test('developer and reviewer perform common work while settings remain protected', async ({ page }) => {
  await login(page, 'developer');
  await expect(page).toHaveURL(/#\/developer\/settings$/);
  expect((await page.request.get('/api/cases')).status()).toBe(200);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await login(page, 'reviewer');
  await expect(page.getByRole('heading', { name: '접수', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '일괄 등록 (CSV·Excel)', exact: true })).toHaveCount(1);
  await expect(page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true })).toHaveCount(0);
  expect((await page.request.post('/api/cases', { headers, data: { event_id: 'COMMON-INTAKE', participant_id: 'reviewer-new', dog_name: '검토자 접수' } })).status()).toBe(201);
  expect((await page.request.get('/api/developer/settings')).status()).toBe(403);
});
