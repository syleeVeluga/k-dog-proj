import { test, expect, type Page } from '@playwright/test';
import { openMenu, openPreprocessing } from './menu';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function create(page: Page, id: string) {
  const response = await page.request.post('/api/cases', { headers, data: { event_id: 'FLOW-1023', participant_id: id, dog_name: `흐름견 ${id}` } });
  expect(response.status()).toBe(201);
  return response.json();
}

test('설문은 빈칸 사유를 구분하고 같은 참가자의 영상과 촬영 기록으로 이어진다', async ({ page }, testInfo) => {
  await login(page);
  const item = await create(page, 'FLOW-SURVEY');
  const answers = Object.fromEntries(Array.from({ length: 28 }, (_, i) => [`s${String(i + 1).padStart(2, '0')}`, i < 3 ? null : i === 9 ? 0 : 3]));
  expect((await page.request.put(`/api/cases/${item.case_id}/survey`, { headers, data: {
    expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3',
    answers, not_applicable: [], blank_reasons: { s01: '관찰하지 못함', s02: '기억나지 않음' },
  } })).status()).toBe(200);
  await page.reload(); await openMenu(page, '설문 확인');
  await page.getByLabel('행사 필터').selectOption('FLOW-1023');
  const row = page.getByRole('row').filter({ hasText: 'FLOW-SURVEY' });
  await expect(row).toContainText('25/28');
  await expect(row).toContainText('사유 기록 2개');
  await expect(row).toContainText('사유 미기록 1개');
  await expect(page.getByText('자세히', { exact: true })).toHaveCount(0);
  const callout = page.locator('.registration-callout');
  const text = await callout.locator('p').boundingBox(), button = await callout.getByRole('button').boundingBox();
  expect(Math.abs(text!.y + text!.height / 2 - button!.y - button!.height / 2)).toBeLessThan(2);
  await page.screenshot({ path: testInfo.outputPath('survey-list-desktop.png'), fullPage: true, animations: 'disabled' });
  await row.getByRole('button', { name: 'FLOW-SURVEY 설문 확인 열기' }).click();
  await expect(page.locator('details#survey')).toHaveAttribute('open', '');
  const firstResponse = page.locator('details#survey').getByRole('row').filter({ has: page.getByRole('cell', { name: '1', exact: true }) });
  await expect(firstResponse.getByRole('cell', { name: '미응답', exact: true })).toBeVisible();
  await expect(firstResponse.getByRole('cell', { name: '관찰하지 못함', exact: true })).toBeVisible();
  const responses = await page.locator('details#survey').boundingBox();
  const calculations = await page.getByRole('heading', { name: '영역별 계산 결과', exact: true }).boundingBox();
  expect(responses!.y).toBeLessThan(calculations!.y);
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '영상 등록', exact: true }).click();
  await expect(page).toHaveURL(/#\/recording\/inbox$/);
  await expect(page.getByLabel('선택 참가자')).toContainText('FLOW-SURVEY');
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles({ name: 'flow_CAM1.mp4', mimeType: 'video/mp4', buffer: Buffer.from('storage-only synthetic video') });
  const received = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/uploads'));
  await page.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  expect((await received).postDataJSON()).toMatchObject({ case_id: item.case_id, session_id: item.selected_session_id });
  const card = page.getByRole('article', { name: '업로드 파일 flow_CAM1.mp4' });
  await expect(card.getByLabel('참가자', { exact: true })).toBeDisabled();
  await card.getByLabel('촬영 카메라 번호', { exact: true }).fill('1');
  await card.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
  await expect(card).toHaveCount(0);
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '촬영 기록', exact: true }).click();
  await expect(page.getByRole('region', { name: '촬영 기록', exact: true })).toBeVisible();
  await expect(page.getByLabel('선택 참가자')).toContainText('FLOW-SURVEY');
});

test('업로드 직접 진입과 접수 행 바로가기는 참가자 선택을 보존하고 미저장 파일을 보호한다', async ({ page }, testInfo) => {
  await login(page);
  await create(page, 'FLOW-PICK-A'); await create(page, 'FLOW-PICK-B');
  await page.reload();
  await page.getByRole('button', { name: 'FLOW-PICK-A 영상 등록', exact: true }).click();
  await expect(page.getByLabel('선택 참가자')).toContainText('FLOW-PICK-A');
  await page.reload();
  await expect(page.getByRole('region', { name: '영상 등록 대상' })).toBeVisible();
  await expect(page.getByLabel('영상 파일', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'FLOW-PICK-B 영상 등록 대상 선택', exact: true }).click();
  await expect(page.getByLabel('선택 참가자')).toContainText('FLOW-PICK-B');
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles({ name: 'unsent.mp4', mimeType: 'video/mp4', buffer: Buffer.from('unsent') });
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '참가자 다시 선택', exact: true }).click();
  await expect(page.getByLabel('선택 참가자')).toContainText('FLOW-PICK-B');
  await expect(page.locator('.upload-queue')).toContainText('unsent.mp4');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '참가자 다시 선택', exact: true }).click();
  await expect(page.getByRole('region', { name: '영상 등록 대상' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('upload-picker-mobile.png'), fullPage: false, animations: 'disabled' });
  await openMenu(page, '설문 확인');
  await page.getByLabel('행사 필터').selectOption('FLOW-1023');
  await expect(page.locator('.registration-callout button')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('survey-list-mobile.png'), fullPage: true, animations: 'disabled' });
});

test('참가자 전처리 탭은 준비 상태·조회 실패·입력 변경을 구분하며 자동 실행하지 않는다', async ({ page }, testInfo) => {
  await login(page);
  const ready = await create(page, 'FLOW-READY');
  const changed = await create(page, 'FLOW-CHANGED');
  const failed = await create(page, 'FLOW-ERROR');
  const retry = await create(page, 'FLOW-RETRY');
  await create(page, 'FLOW-MISSING');
  let executions = 0;
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/preprocess-s1')) executions++; });
  await page.route('**/api/cases/*/sessions/*/preprocess-s1', async route => {
    const id = route.request().url().split('/cases/')[1].split('/')[0];
    if (id === failed.case_id) return route.fulfill({ status: 503, json: { detail: '시험용 상태 조회 실패' } });
    if (![ready.case_id, changed.case_id, retry.case_id].includes(id)) return route.continue();
    const item = id === ready.case_id ? ready : id === retry.case_id ? retry : changed;
    return route.fulfill({ json: { case_id: id, session_id: item.selected_session_id, input_revision: item.input_revision + (id === changed.case_id ? 1 : 0), ready: true, status: id === retry.case_id ? 'failed' : 'ready', message: '확정된 촬영 창', outdated: false, result: null, result_pointer: null } });
  });
  await openPreprocessing(page, 'FLOW-READY');
  const panel = page.getByRole('region', { name: '다중 카메라 전처리', exact: true });
  await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toBeEnabled();
  await openPreprocessing(page, 'FLOW-MISSING');
  await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toBeDisabled();
  await openPreprocessing(page, 'FLOW-CHANGED');
  await expect(panel.getByRole('button', { name: '새 클립으로 전처리', exact: true })).toBeDisabled();
  await openPreprocessing(page, 'FLOW-ERROR');
  await expect(panel.getByRole('alert')).toContainText('시험용 상태 조회 실패');
  await openPreprocessing(page, 'FLOW-RETRY');
  await expect(panel.getByRole('status')).toContainText('실패');
  expect(executions).toBe(0);
  await panel.screenshot({ path: testInfo.outputPath('participant-preprocess.png'), animations: 'disabled' });
});

test('참가자 바로가기의 늦은 조회는 사용자가 이동한 화면을 덮어쓰지 않는다', async ({ page }) => {
  await login(page);
  const item = await create(page, 'FLOW-LATE');
  await page.reload();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/api/cases/${item.case_id}?purpose=open`, async route => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  const request = page.waitForRequest(value => value.url().includes(`${item.case_id}?purpose=open`));
  await page.getByRole('button', { name: 'FLOW-LATE 영상 등록', exact: true }).click();
  await request;
  await openMenu(page, '설문 확인');
  const response = page.waitForResponse(value => value.url().includes(`${item.case_id}?purpose=open`));
  release(); await response;
  await expect(page).toHaveURL(/#\/survey$/);
  await expect(page.getByLabel('선택 참가자')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'FLOW-LATE 설문 확인 열기', exact: true })).toBeVisible();
});

test('참가자 조회가 실패하면 이전 참가자를 전처리 대상으로 대신 열지 않는다', async ({ page }) => {
  await login(page);
  const item = await create(page, 'FLOW-OPEN-ERROR');
  await page.reload();
  await page.route(`**/api/cases/${item.case_id}?purpose=open`, route => route.fulfill({ status: 503, json: { detail: '시험용 참가자 조회 실패' } }));
  await page.getByRole('button', { name: 'FLOW-OPEN-ERROR 영상 등록', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('시험용 참가자 조회 실패');
  await expect(page.getByRole('button', { name: 'FLOW-OPEN-ERROR 영상 등록', exact: true })).toBeVisible();
  await expect(page.getByLabel('선택 참가자')).toHaveCount(0);
});

test('접수 바로가기 조회 실패 뒤에도 작성 중인 접수 입력의 이동 경고가 유지된다', async ({ page }) => {
  await login(page);
  const item = await create(page, 'FLOW-DRAFT-ERROR');
  await page.reload();
  await expect(page.getByRole('button', { name: 'FLOW-DRAFT-ERROR 영상 등록', exact: true })).toBeVisible();
  const form = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await form.getAttribute('open') === null) await form.getByText('참가자 등록', { exact: true }).click();
  await page.getByLabel('행사 ID', { exact: true }).fill('UNSAVED-FLOW');
  await page.route(`**/api/cases/${item.case_id}?purpose=open`, route => route.fulfill({ status: 503, json: { detail: '시험용 참가자 조회 실패' } }));
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'FLOW-DRAFT-ERROR 영상 등록', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('시험용 참가자 조회 실패');
  let warned = false;
  page.once('dialog', dialog => { warned = true; return dialog.dismiss(); });
  await openMenu(page, '설문 확인');
  expect(warned).toBe(true);
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(page.getByLabel('행사 ID', { exact: true })).toHaveValue('UNSAVED-FLOW');
});
