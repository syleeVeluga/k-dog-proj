import { test, expect, type Page } from '@playwright/test';
import { openMenu } from './menu';

async function setup(page: Page, id: string) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  const response = await page.request.post('/api/cases', { headers: { 'X-KDOG-Request': '1' }, data: { event_id: 'NAV-1024', participant_id: id, dog_name: '위치 확인견' } });
  expect(response.status()).toBe(201);
  const item = await response.json();
  await page.reload();
  await expect(page.getByRole('button', { name: `${id} 영상 등록`, exact: true })).toBeVisible();
  return item;
}

test('위치·작업 탭은 참가자와 회차를 유지하고 원래 목록의 모든 필터로 돌아간다', async ({ page }, testInfo) => {
  const item = await setup(page, 'NAV-TABS');
  const sessionWrites: string[] = [];
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith(`/cases/${item.case_id}/sessions`)) sessionWrites.push(request.url()); });
  await page.getByLabel('검색', { exact: true }).fill('NAV-TABS');
  await page.getByLabel('행사 필터').selectOption('NAV-1024');
  await page.getByLabel('자료 상태 별 조회').selectOption('video_missing');
  await page.getByRole('button', { name: 'NAV-TABS 영상 등록', exact: true }).click();
  const trail = page.getByRole('navigation', { name: '현재 위치' });
  const tabs = page.getByRole('navigation', { name: '참가자 작업' });
  await expect(trail).toContainText('현장 운영');
  await expect(trail).toContainText('참가자 접수 목록');
  await expect(trail).toContainText('NAV-TABS · 위치 확인견');
  await expect(trail.locator('[aria-current="page"]')).toHaveText('영상 등록');
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true }).getByRole('heading')).toContainText('1차 촬영');
  await expect(tabs.getByRole('button')).toHaveText(['설문 확인', '영상 등록', '촬영 기록', '전처리']);
  for (const name of ['설문 확인', '촬영 기록', '전처리', '영상 등록']) {
    await tabs.getByRole('button', { name, exact: true }).click();
    await expect(tabs.getByRole('button', { name, exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(trail.locator('[aria-current="page"]')).toHaveText(name);
    await expect(page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '참가자 접수', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByRole('region', { name: '선택 참가자', exact: true }).getByRole('heading')).toContainText('1차 촬영');
    await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('NAV-TABS');
  }
  expect(sessionWrites).toEqual([]);
  const unchanged = await (await page.request.get(`/api/cases/${item.case_id}`)).json();
  expect(unchanged.selected_session_id).toBe(item.selected_session_id);
  expect(unchanged.input_revision).toBe(item.input_revision);
  await tabs.getByRole('button', { name: '촬영 기록', exact: true }).click();
  await tabs.getByRole('button', { name: '전처리', exact: true }).click();
  await page.goBack();
  await expect(tabs.locator('[aria-current="page"]')).toHaveText('촬영 기록');
  await page.goForward();
  await expect(tabs.locator('[aria-current="page"]')).toHaveText('전처리');
  await expect(trail.getByRole('button')).toHaveText('참가자 접수 목록');
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('NAV-TABS');
  await page.screenshot({ path: testInfo.outputPath('participant-navigation-desktop.png'), animations: 'disabled' });
  await page.getByRole('button', { name: '전체 목록으로 돌아가기', exact: true }).click();
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(page.getByLabel('검색', { exact: true })).toHaveValue('NAV-TABS');
  await expect(page.getByLabel('행사 필터')).toHaveValue('NAV-1024');
  await expect(page.getByLabel('자료 상태 별 조회')).toHaveValue('video_missing');
  await expect(tabs).toHaveCount(0);
  await page.getByRole('button', { name: 'NAV-TABS 영상 등록', exact: true }).click();
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('NAV-TABS');
  await openMenu(page, '설문 확인');
  await expect(trail.getByRole('button')).toHaveText('설문 확인 목록');
  await expect(page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '설문 확인', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('독립 전처리 메뉴와 전체 대상 화면 없이 참가자 탭에서 처리한다', async ({ page }) => {
  await setup(page, 'NAV-ANALYSIS');
  await expect(page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '전처리', exact: true })).toHaveCount(0);
  await page.evaluate(() => { window.location.hash = '#/preprocess'; });
  await expect(page.getByRole('button', { name: '참가자 접수로 이동', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: '분석 대상 목록' })).toHaveCount(0);
  await page.getByRole('button', { name: '참가자 접수로 이동', exact: true }).click();
  await page.getByRole('button', { name: 'NAV-ANALYSIS 영상 등록', exact: true }).click();
  await expect(page.getByRole('navigation', { name: '참가자 작업' })).toBeVisible();
  await openMenu(page, '전처리');
  await expect(page.getByRole('button', { name: '전처리 실행', exact: true })).toHaveCount(0);
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '촬영 기록', exact: true }).click();
  const trail = page.getByRole('navigation', { name: '현재 위치' });
  await expect(trail.getByRole('button')).toHaveText('참가자 접수 목록');
  await page.getByRole('region', { name: '촬영 기록', exact: true }).getByRole('button', { name: '닫기', exact: true }).click();
  await expect(page).toHaveURL(/#\/intake$/);
});

test('모바일 촬영·전처리 탭과 목록 복귀는 미저장 파일 및 참가자 맥락을 보호한다', async ({ page }, testInfo) => {
  await setup(page, 'NAV-GUARD');
  await page.getByRole('button', { name: 'NAV-GUARD 영상 등록', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  const trail = page.getByRole('navigation', { name: '현재 위치' });
  const tabs = page.getByRole('navigation', { name: '참가자 작업' });
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles({ name: 'unsent.mp4', mimeType: 'video/mp4', buffer: Buffer.from('synthetic unsent') });
  for (const button of [tabs.getByRole('button', { name: '촬영 기록', exact: true }), tabs.getByRole('button', { name: '전처리', exact: true }), trail.getByRole('button'), page.getByRole('button', { name: '전체 목록으로 돌아가기', exact: true })]) {
    page.once('dialog', dialog => dialog.dismiss());
    await button.click();
    await expect(page).toHaveURL(/#\/recording\/inbox$/);
    await expect(page.locator('.upload-queue')).toContainText('unsent.mp4');
  }
  await expect(page.getByRole('button', { name: '전체 목록으로 돌아가기', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('participant-navigation-mobile.png'), animations: 'disabled' });
  page.once('dialog', dialog => dialog.accept());
  await tabs.getByRole('button', { name: '전처리', exact: true }).click();
  await expect(trail).toContainText('현장 운영');
  await expect(trail).toContainText('참가자 접수 목록');
  await expect(trail.locator('[aria-current="page"]')).toHaveText('전처리');
  await expect(tabs.getByRole('button', { name: '전처리', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('button', { name: '촬영 기록으로 이동', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '선행 조건', exact: true })).toContainText('위의 촬영 기록 탭에서 확정합니다.');
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('preprocess-tab-mobile.png'), animations: 'disabled' });
  await tabs.getByRole('button', { name: '촬영 기록', exact: true }).click();
  await expect(page.getByRole('button', { name: '분석 준비 확인', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('NAV-GUARD');
  await trail.getByRole('button').click();
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toHaveCount(0);
});

test('촬영 메뉴는 숨기고 공용 보관함은 접수에서 열며 새로고침 뒤에도 위치가 맞는다', async ({ page }) => {
  await setup(page, 'NAV-SHARED');
  const menu = page.getByRole('navigation', { name: '주 메뉴' });
  await expect(menu.getByRole('button', { name: /영상 파일 업로드|촬영 기록/ })).toHaveCount(0);
  await expect(menu.getByRole('group', { name: '촬영', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '공용 업로드 보관함', exact: true }).click();
  await expect(page).toHaveURL(/#\/recording\/shared$/);
  await expect(page.getByRole('navigation', { name: '현재 위치' }).locator('[aria-current="page"]')).toHaveText('공용 업로드 보관함');
  await expect(page.getByLabel('영상 파일', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('영상 파일', { exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: '현재 위치' }).getByRole('button').click();
  await expect(page).toHaveURL(/#\/intake$/);
});
