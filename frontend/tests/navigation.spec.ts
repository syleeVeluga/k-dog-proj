import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function login(page: Page, username = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
const menu = (page: Page) => page.getByRole('navigation', { name: '주 메뉴' });
const labels = async (page: Page) => (await menu(page).getByRole('button').allInnerTexts()).map(text => text.trim());

test('위치가 hash에 남고 새로고침·뒤로가기·앞으로가기 후에도 같은 화면이 열린다', async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(menu(page).getByRole('button', { name: '참가자 접수', exact: true })).toHaveAttribute('aria-current', 'page');
  await menu(page).getByRole('button', { name: '일괄 등록 (CSV·Excel)', exact: true }).click();
  await expect(page).toHaveURL(/#\/intake\/upload$/);
  await expect(page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true })).toBeVisible();
  await menu(page).getByRole('button', { name: '영상 수신·연결', exact: true }).click();
  await expect(page).toHaveURL(/#\/recording\/inbox$/);
  await expect(page.getByRole('heading', { name: '영상 수신·연결', exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/#\/recording\/inbox$/);
  await expect(page.getByRole('heading', { name: '영상 수신·연결', exact: true })).toBeVisible();
  await expect(menu(page).getByRole('button', { name: '영상 수신·연결', exact: true })).toHaveAttribute('aria-current', 'page');
  await menu(page).getByRole('button', { name: '촬영 기록 (8구간)', exact: true }).click();
  await expect(page.getByRole('heading', { name: '촬영', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: '영상 수신·연결', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#\/recording\/inbox$/);
  await menu(page).getByRole('button', { name: '비교 조건', exact: true }).click();
  await expect(page).toHaveURL(/#\/report\/comparison$/);
  await expect(page.getByRole('heading', { name: '리포트 비교 조건', exact: true })).toBeVisible();
  await menu(page).getByRole('button', { name: '리포트 발급', exact: true }).click();
  await expect(page.getByRole('heading', { name: '리포트', exact: true })).toBeVisible();
});

test('LNB 업무 메뉴는 모든 계정에 같고 개발 설정만 개발자에게 보인다', async ({ page }) => {
  await login(page);
  for (const group of ['현장 운영', '분석·평가', '자료 관리']) await expect(menu(page).getByRole('group', { name: group, exact: true })).toBeVisible();
  await expect(menu(page).getByRole('group', { name: '촬영', exact: true })).toBeVisible();
  await expect(menu(page).getByRole('group', { name: '리포트', exact: true })).toBeVisible();
  const common = ['참가자 접수', '일괄 등록 (CSV·Excel)', '설문 현황', '영상 수신·연결', '촬영 기록 (8구간)', '전처리', '독립 채점', '리포트 발급', '비교 조건', '연구 내보내기', '검수 자료', '직원 계정', '백업·복구'];
  expect(await labels(page)).toEqual(common);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'reviewer');
  expect(await labels(page)).toEqual(common);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'admin');
  expect(await labels(page)).toEqual(common);
  await menu(page).getByRole('button', { name: '백업·복구', exact: true }).click();
  await expect(page).toHaveURL(/#\/admin\/backup$/);
  await expect(page.getByRole('heading', { name: '자료 관리', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'developer');
  expect(await labels(page)).toEqual([...common, '개발 설정']);
  await menu(page).getByRole('button', { name: '개발 설정', exact: true }).click();
  await expect(page.getByRole('heading', { name: '개발 설정' })).toBeVisible();
  await menu(page).getByRole('button', { name: '직원 계정', exact: true }).click();
  await expect(page.getByRole('heading', { name: '직원 계정' })).toBeVisible();
});

test('공통 업무 hash는 직접 열고 개발 설정과 알 수 없는 hash만 첫 메뉴로 보낸다', async ({ page }) => {
  await login(page, 'reviewer');
  await page.evaluate(() => { window.location.hash = '#/admin/users'; });
  await expect(page).toHaveURL(/#\/admin\/users$/);
  await expect(page.getByRole('heading', { name: '직원 계정', exact: true })).toBeVisible();
  await page.evaluate(() => { window.location.hash = '#/recording/inbox'; });
  await expect(page).toHaveURL(/#\/recording\/inbox$/);
  await page.evaluate(() => { window.location.hash = '#/developer/settings'; });
  await expect(page).toHaveURL(/#\/intake$/);
  await page.evaluate(() => { window.location.hash = '#/없는/경로%E0'; });
  await expect(page).toHaveURL(/#\/intake$/);
  await page.evaluate(() => { window.location.hash = '#/scoring'; });
  await expect(page.getByRole('heading', { name: '독립 채점' })).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.goto('/#/admin/backup');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/#\/admin\/backup$/);
});

test('미저장 입력이 있으면 메뉴 이동과 뒤로가기를 확인하고 취소하면 hash를 되돌린다', async ({ page }) => {
  await login(page);
  await menu(page).getByRole('button', { name: '일괄 등록 (CSV·Excel)', exact: true }).click();
  await menu(page).getByRole('button', { name: '참가자 접수', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: /마지막 조회 [^·\s]/ })).toBeVisible();
  const registration = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await registration.getAttribute('open') === null) await registration.getByText('참가자 등록', { exact: true }).click();
  await page.getByLabel('행사 ID', { exact: true }).fill('NAV-GUARD');
  const prompts: string[] = [];
  page.on('dialog', dialog => { prompts.push(dialog.message()); void dialog.dismiss(); });
  await menu(page).getByRole('button', { name: '설문 현황', exact: true }).click();
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(page.getByLabel('행사 ID', { exact: true })).toHaveValue('NAV-GUARD');
  await page.goBack();
  await expect.poll(() => prompts.length).toBe(2);
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(page.getByLabel('행사 ID', { exact: true })).toHaveValue('NAV-GUARD');
  expect(prompts.every(text => text.includes('저장하지 않은 입력'))).toBe(true);
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => void dialog.accept());
  // 취소한 뒤로가기가 기록을 덮어쓰지 않는다: 허용 후 다시 뒤로 가면 이전 항목(일괄 등록)이 열린다.
  await page.goBack();
  await expect(page).toHaveURL(/#\/intake\/upload$/);
  await page.goForward();
  await expect(page).toHaveURL(/#\/intake$/);
  const again = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await again.getAttribute('open') === null) await again.getByText('참가자 등록', { exact: true }).click();
  await page.getByLabel('행사 ID', { exact: true }).fill('NAV-GUARD');
  await menu(page).getByRole('button', { name: '설문 현황', exact: true }).click();
  await expect(page).toHaveURL(/#\/survey$/);
  await expect(page.getByRole('heading', { name: '설문', exact: true })).toBeVisible();
});

test('1440px 고정 LNB와 768px 접이식 LNB', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await expect(menu(page)).toBeVisible();
  await expect(page.getByRole('button', { name: '메뉴', exact: true })).toBeHidden();
  const box = await menu(page).boundingBox();
  expect(box!.x).toBeLessThan(300); expect(box!.width).toBeLessThan(260);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 768, height: 900 });
  await expect(menu(page)).toBeVisible();
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await toggle.click();
  await expect(menu(page)).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await expect(menu(page)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const width of [360, 390]) {
  test(`${width}px 서랍: 포커스 이동·Esc·바깥 클릭·메뉴 선택 닫기·가로 넘침 0`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await login(page);
    const toggle = page.getByRole('button', { name: '메뉴', exact: true });
    await expect(menu(page)).toBeHidden();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    await expect(menu(page)).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(menu(page).getByRole('button', { name: '참가자 접수', exact: true })).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(menu(page)).toBeHidden();
    await expect(toggle).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
    await toggle.click();
    await page.mouse.click(width - 8, 400);
    await expect(menu(page)).toBeHidden();
    await toggle.click();
    await menu(page).getByRole('button', { name: '메뉴 닫기', exact: true }).click();
    await expect(menu(page)).toBeHidden();
    await toggle.click();
    await menu(page).getByRole('button', { name: '설문 현황', exact: true }).click();
    await expect(menu(page)).toBeHidden();
    await expect(page).toHaveURL(/#\/survey$/);
    await expect(page.getByRole('heading', { name: '설문', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('390px: 이동을 취소해도 서랍은 열려 있고, 세션 만료 뒤 다시 로그인하면 서랍이 닫혀 있다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await login(page);
  await expect(page.getByRole('status').filter({ hasText: /마지막 조회 [^·\s]/ })).toBeVisible();
  const registration = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await registration.getAttribute('open') === null) await registration.getByText('참가자 등록', { exact: true }).click();
  await page.getByLabel('행사 ID', { exact: true }).fill('NAV-DRAWER');
  page.on('dialog', dialog => void dialog.dismiss());
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await toggle.click();
  await menu(page).getByRole('button', { name: '설문 현황', exact: true }).click();
  await expect(page).toHaveURL(/#\/intake$/);
  await expect(menu(page)).toBeVisible();
  page.removeAllListeners('dialog');
  await page.evaluate(() => window.dispatchEvent(new Event('kdog-session-expired')));
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(toggle).toBeVisible();
  await expect(menu(page)).toBeHidden();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
  await expect(page.locator('main')).not.toHaveAttribute('inert');
  expect(await page.evaluate(() => !!document.getElementById('lnb'))).toBe(true);
});
