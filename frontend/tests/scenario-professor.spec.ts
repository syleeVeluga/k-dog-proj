import { test, expect } from '@playwright/test';
import { openMenu } from './menu';

const password = 'Browser-test-only-42';
const headers = { 'X-KDOG-Request': '1' };
const EVENT = 'U07-PROF';
const NEW_PROFESSOR = 'u07-professor';

// 합성 현장 리허설: 관리자가 교수 계정을 만들고, 교수는 자기 할 일과 선행 조건만 읽는다. 앱 서버 밖으로는 요청하지 않는다.
test('관리자가 교수 계정을 추가하면 교수는 「내가 할 일만」과 선행 조건 체크리스트를 읽기 전용으로 본다', async ({ page, browser, request }) => {
  test.setTimeout(120000);
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  for (const [id, dog, sequence] of [['P1', '교수견1', 1], ['P2', '교수견2', 2]] as const)
    expect((await request.post('/api/cases', { headers, data: { event_id: EVENT, participant_id: id, dog_name: dog, sequence_no: sequence } })).status()).toBe(201);

  const outside: string[] = [];
  page.on('request', value => { if (!value.url().startsWith('http://127.0.0.1:8765/') && !value.url().startsWith('data:') && !value.url().startsWith('blob:')) outside.push(value.url()); });
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('admin');
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();

  // 관리자: 교수 계정 추가 후 백업 화면 확인
  await openMenu(page, '직원 계정');
  await page.getByText('직원 계정 추가', { exact: true }).click();
  await page.getByLabel('새 계정', { exact: true }).fill(NEW_PROFESSOR);
  await page.getByLabel('초기 비밀번호', { exact: true }).fill(password);
  await page.getByRole('combobox', { name: '새 계정 역할' }).selectOption('reviewer');
  await page.getByRole('button', { name: '계정 생성', exact: true }).click();
  await expect(page.locator('.user-row').filter({ has: page.locator('strong', { hasText: new RegExp(`^${NEW_PROFESSOR}$`) }) })).toBeVisible();
  await openMenu(page, '백업·복구');
  await page.getByText('자료 백업·복구', { exact: true }).click();
  await expect(page.getByRole('button', { name: '자료 백업 생성 · 키 제외', exact: true })).toBeVisible();

  // 교수: 새 계정으로 로그인
  const client = await browser.newContext();
  try {
    const prof = await client.newPage();
    prof.on('request', value => { if (!value.url().startsWith('http://127.0.0.1:8765/') && !value.url().startsWith('data:') && !value.url().startsWith('blob:')) outside.push(value.url()); });
    await prof.goto('/');
    await prof.getByLabel('계정', { exact: true }).fill(NEW_PROFESSOR);
    await prof.getByLabel('비밀번호', { exact: true }).fill(password);
    await prof.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(prof.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();

    // 쓰기·관리 메뉴는 보이지 않는다.
    const nav = prof.getByRole('navigation').first();
    for (const hidden of ['일괄 등록 (CSV·Excel)', '직원 계정', '백업·복구', '연구 내보내기', '비교 조건'])
      await expect(nav.getByText(hidden, { exact: true })).toHaveCount(0);
    // U08: 리포트 발급 메뉴는 교수에게도 열려 있다.
    await expect(nav.getByText('리포트 발급', { exact: true })).toHaveCount(1);
    await expect(prof.getByText('참가자 등록', { exact: true })).toHaveCount(0);

    // 「내가 할 일만」: 배정된 시트가 없으므로 내 할 일은 없고, 전체 보기에서는 참가자가 보인다.
    await openMenu(prof, '독립 채점');
    const rows = prof.getByRole('row').filter({ hasText: EVENT });
    await expect(rows).toHaveCount(2);
    await prof.getByLabel('내가 할 일만', { exact: true }).check();
    await expect(rows).toHaveCount(0);
    await expect(prof.getByRole('heading', { name: '독립 채점', level: 1 })).toBeVisible();
    await expect(prof.getByRole('columnheader').first()).toBeVisible();
    await prof.getByLabel('내가 할 일만', { exact: true }).uncheck();
    await expect(rows).toHaveCount(2);

    // 참가자를 열면 선행 조건이 「운영자에게 요청할 일」로 안내되고, 이동 버튼 등 쓰기 동작은 없다.
    await prof.getByRole('button', { name: 'P1 독립 채점 열기', exact: true }).click();
    const check = prof.getByRole('region', { name: '선행 조건', exact: true });
    await expect(check.getByRole('heading', { name: '채점을 시작하려면 · 운영자에게 요청할 일', exact: true })).toBeVisible();
    await expect(check.getByText('운영자가 촬영 기록을 확정해야 합니다.', { exact: false })).toBeVisible();
    await expect(check.getByRole('button')).toHaveCount(0);
    await openMenu(prof, '촬영 기록 (8구간)');
    await expect(prof.getByRole('button', { name: '촬영 기록 저장', exact: true })).toHaveCount(0);
    expect((await prof.request.post('/api/cases', { headers, data: { event_id: EVENT, participant_id: 'P9', dog_name: '쓰기시도' } })).status()).toBe(403);
    // U08: 리포트 화면을 열면(선택한 P1 유지) 리포트 실행 영역이 보인다(권한 안내 대신).
    await openMenu(prof, '리포트 발급');
    await expect(prof.getByText('운영자가 접수 상세에서 분석·피드백 동의를 확인해야 합니다.', { exact: false })).toBeVisible();
    await expect(prof.getByRole('region', { name: 'S1 리포트 실행', exact: true })).toBeVisible();
    await expect(prof.getByText('리포트 운영 권한이 필요합니다.', { exact: true })).toHaveCount(0);
  } finally { await client.close(); }
  expect(outside).toEqual([]);
});

test.afterAll(async ({ request }) => {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  for (const item of (await (await request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === EVENT))
    await request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
});
