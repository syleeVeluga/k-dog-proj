import { test, expect } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
const password = 'Browser-test-only-42';
const DEV_CODES = /S16|G0[1-5]|D0[1-6]|공급자 호출|교수 테스트|S1\.1/;

async function login(page: Page, username = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true }).first()).toBeVisible();
}
// 시드 요청은 브라우저와 쿠키를 공유하지 않는 별도 요청 컨텍스트로 보낸다(그렇지 않으면 화면이 이미 로그인된 상태가 된다).
async function seed(request: APIRequestContext, event: string, people: [string, string, number][]) {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  for (const [id, dog, sequence] of people)
    expect((await request.post('/api/cases', { headers, data: { event_id: event, participant_id: id, dog_name: dog, sequence_no: sequence } })).status()).toBe(201);
}

test('전처리·채점·리포트 목록은 같은 진행 단계와 다음 할 일을 보이고 선행 조건에서 이동한다', async ({ page, request }) => {
  await seed(request, 'U06-STAFF', [['L1', '초코', 1], ['L2', '콩이', 2]]);
  await login(page);
  for (const [menu, label] of [['독립 채점', '독립 채점'], ['리포트 발급', '리포트']] as const) {
    await openMenu(page, menu);
    const row = page.getByRole('row').filter({ hasText: 'U06-STAFF' }).filter({ hasText: 'L1' });
    await expect(row.getByText('영상을 연결하고 촬영 기록을 확정하세요', { exact: true })).toBeVisible();
    await expect(row.getByText('시트 없음', { exact: true })).toBeVisible();
    const steps = row.getByRole('list', { name: 'L1 진행 단계' }).getByRole('listitem');
    await expect(steps).toHaveText(['촬영 확정 진행 중', '전처리 대기', '채점 대기', '최종 결과 대기', '리포트 대기']);
    await expect(steps.first()).toHaveAttribute('aria-current', 'step');
    await expect(row.getByRole('button', { name: new RegExp(`L1 ${label}.* 열기`) })).toBeVisible();
  }
  await openMenu(page, '독립 채점');
  const filter = page.getByLabel('진행 단계 필터', { exact: true });
  await filter.selectOption('preprocess');
  await expect(page.getByRole('row').filter({ hasText: 'U06-STAFF' })).toHaveCount(0);
  await filter.selectOption('recording');
  await expect(page.getByRole('row').filter({ hasText: 'U06-STAFF' })).toHaveCount(2);
  await filter.selectOption('complete');
  await expect(page.getByRole('row').filter({ hasText: 'U06-STAFF' })).toHaveCount(0);
  await filter.selectOption('');
  await page.getByLabel('미완료만', { exact: true }).check();
  await expect(page.getByRole('row').filter({ hasText: 'U06-STAFF' })).toHaveCount(2);
  // 선행 조건 체크리스트: 빠진 것과 이동 버튼
  await openMenu(page, '전처리');
  await expect(page.getByLabel('전처리 상태')).toBeVisible();
  await expect(page.getByLabel('진행 단계 필터', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await page.getByRole('button', { name: 'L1 전처리 열기', exact: true }).click();
  const check = page.getByRole('region', { name: '선행 조건', exact: true });
  await expect(check.getByRole('heading', { name: '전처리를 실행하려면', exact: true })).toBeVisible();
  await expect(check.getByText('촬영 기록 확정', { exact: true })).toBeVisible();
  await expect(check.getByText('촬영 기록 화면에서 확정합니다.', { exact: false })).toBeVisible();
  await openMenu(page, '독립 채점');
  const scoring = page.getByRole('region', { name: '선행 조건', exact: true });
  await expect(scoring.getByRole('heading', { name: '채점을 시작하려면', exact: true })).toBeVisible();
  await expect(scoring.locator('li.missing')).toHaveCount(3);
  await expect(scoring.getByText('채점 시트', { exact: true })).toBeVisible();
  await scoring.getByRole('button', { name: '전처리로 이동', exact: true }).click();
  await expect(page).toHaveURL(/#\/preprocess$/);
  await page.getByRole('region', { name: '선행 조건', exact: true }).getByRole('button', { name: '촬영 기록으로 이동', exact: true }).click();
  await expect(page).toHaveURL(/#\/recording\/record$/);
  await openMenu(page, '리포트 발급');
  await expect(page.getByRole('region', { name: '선행 조건', exact: true }).getByText('최종 결과 확정', { exact: true })).toBeVisible();
});

test('검토자도 공통 진행과 작업을 사용하고 기술 상세는 접어서 본다', async ({ page, request }) => {
  await seed(request, 'U06-REVIEW', [['V1', '교수견', 1]]);
  await login(page, 'reviewer');
  await openMenu(page, '독립 채점');
  const row = page.getByRole('row').filter({ hasText: 'V1' });
  await expect(row.getByRole('list', { name: 'V1 진행 단계' }).getByRole('listitem')).toHaveText(['촬영 확정 진행 중', '전처리 대기', '채점 대기', '최종 결과 대기', '리포트 대기']);
  await expect(row.getByText('영상을 연결하고 촬영 기록을 확정하세요', { exact: true })).toBeVisible();
  await expect(row.getByText('시트 없음', { exact: true })).toBeVisible();
  const options = await page.getByLabel('진행 단계 필터', { exact: true }).locator('option').allInnerTexts();
  expect(options).toContain('최종 결과 전');
  expect(options).toContain('리포트 전');
  await page.getByRole('button', { name: 'V1 독립 채점 열기', exact: true }).click();
  await expect(page.getByRole('heading', { name: '채점을 시작하려면', exact: true })).toBeVisible();
  await expect(page.getByText('촬영 기록 화면에서 확정합니다.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: '촬영 기록으로 이동', exact: true })).toBeVisible();
  await expect(page.getByText('AI 초안: 준비 안 됨', { exact: true })).toBeVisible();
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(DEV_CODES);
  expect(text).toContain('Excel 가져오기는 준비 중');
  expect(text).not.toContain('연구 내보내기');
  await page.getByRole('button', { name: '닫기', exact: true }).click();
  await openMenu(page, '전처리');
  await page.getByRole('button', { name: '전처리 실행', exact: true }).first().click();
  await page.getByRole('button', { name: 'V1 전처리 열기', exact: true }).click();
  expect(await page.locator('main').innerText()).not.toMatch(DEV_CODES);
  // U08: 리포트 발급 화면은 교수에게도 열리고, 비교 조건·연구 내보내기는 운영자 전용으로 남는다.
  await page.evaluate(() => { window.location.hash = '#/report'; });
  await expect(page).toHaveURL(/#\/report$/);
  for (const hash of ['#/report/export', '#/report/comparison']) {
    await page.evaluate(value => { window.location.hash = value; }, hash);
    await expect(page).toHaveURL(new RegExp(hash.replace('#', '#')));
  }
});

test('연구 내보내기는 리포트 하위 메뉴로 옮겨지고 독립 채점 화면에는 없다', async ({ page, request }) => {
  await seed(request, 'U06-EXPORT', [['X1', '내보내기견', 1]]);
  await login(page);
  await openMenu(page, '독립 채점');
  await page.getByRole('button', { name: 'X1 독립 채점 열기', exact: true }).click();
  await expect(page.locator('main').getByText('연구 내보내기', { exact: true })).toHaveCount(0);
  await openMenu(page, '연구 내보내기');
  await expect(page).toHaveURL(/#\/report\/export$/);
  await expect(page.getByRole('heading', { name: '연구 내보내기', exact: true, level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: '연구 내보내기', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '← 참가자 목록', exact: true }).click();
  await page.getByRole('button', { name: 'X1 연구 내보내기 열기', exact: true }).click();
  await expect(page.getByRole('region', { name: '연구 내보내기', exact: true })).toBeVisible();
});

test('목록·맥락 바의 영상 수는 사용 가능과 확인 대기로 나눠 쓴다', async ({ page, request }) => {
  await seed(request, 'U06-VIDEO', [['M1', '영상견', 1]]);
  await login(page);
  const row = page.getByRole('row').filter({ hasText: 'M1' });
  await expect(row.getByRole('cell', { name: '0개 · 사용 가능 0 · 확인 대기 0', exact: true })).toBeVisible();
});
