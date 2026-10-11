import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
test.afterEach(async ({ page }) => {
  for (const item of (await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id.startsWith('U04-'))) {
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  }
});

type Seed = [event: string, id: string, sequence: number | null, dog: string];
async function openRegistration(page: Page, seeds: Seed[] = []) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  for (const [event, id, sequence, dog] of seeds)
    expect((await page.request.post('/api/cases', { headers, data: { event_id: event, participant_id: id, dog_name: dog, sequence_no: sequence } })).status()).toBe(201);
  if (seeds.length) await page.reload();
  await expect(page.getByRole('status').filter({ hasText: /마지막 조회 [^·\s]/ })).toBeVisible();
  const details = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await details.getAttribute('open') === null) await details.getByText('참가자 등록', { exact: true }).click();
  return page.locator('form').filter({ has: page.getByLabel('행사 ID', { exact: true }) });
}

test('저장 후 폼에 머물러 키보드만으로 세 명을 연속 등록한다', async ({ page }) => {
  const form = await openRegistration(page);
  await form.getByLabel('행사 ID', { exact: true }).fill('U04-RUN');
  const registered = [] as string[];
  for (const [index, dog] of ['초코', '콩이', '보리'].entries()) {
    const id = `R${index + 1}`;
    await form.getByLabel('참가자 ID', { exact: true }).fill(id);
    if (index === 0) await form.getByLabel('순번', { exact: true }).fill('1');
    else await expect(form.getByLabel('순번', { exact: true })).toHaveValue(String(index + 1));
    await form.getByLabel('반려견 이름', { exact: true }).fill(dog);
    await page.keyboard.press('Enter');
    await expect(page.getByRole('status').filter({ hasText: `${id} ${dog} 등록됨` })).toBeVisible();
    registered.push(id);
    // 상세로 넘어가지 않고 행사 ID는 남고 나머지 칸은 비워져 다음 참가자 ID 칸에 포커스가 있다.
    await expect(page.getByRole('heading', { name: '접수', exact: true })).toBeVisible();
    await expect(form.getByLabel('행사 ID', { exact: true })).toHaveValue('U04-RUN');
    await expect(form.getByLabel('참가자 ID', { exact: true })).toHaveValue('');
    await expect(form.getByLabel('참가자 ID', { exact: true })).toBeFocused();
    await expect(form.getByLabel('반려견 이름', { exact: true })).toHaveValue('');
  }
  await expect(form.getByLabel('순번', { exact: true })).toHaveValue('4');
  const cases = (await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'U04-RUN');
  expect(cases.map((c: { participant_id: string; sequence_no: number }) => [c.participant_id, c.sequence_no]).sort()).toEqual([['R1', 1], ['R2', 2], ['R3', 3]]);
  // 방금 등록한 참가자의 상세와 촬영으로 바로 간다.
  await page.getByRole('status').filter({ hasText: 'R3 보리 등록됨' }).getByRole('button', { name: '촬영으로', exact: true }).click();
  await expect(page).toHaveURL(/#\/recording\/record$/);
  await expect(page.getByRole('region', { name: '선택 참가자', exact: true })).toContainText('R3');
});

test('중복 순번·참가자 ID는 해당 칸 아래에 표시하고 그 칸으로 포커스를 옮긴다', async ({ page }) => {
  const form = await openRegistration(page, [['U04-DUP', 'D1', 1, '초코']]);
  await form.getByLabel('행사 ID', { exact: true }).fill('U04-DUP');
  await form.getByLabel('참가자 ID', { exact: true }).fill('D2');
  await form.getByLabel('순번', { exact: true }).fill('1');
  await form.getByLabel('반려견 이름', { exact: true }).fill('콩이');
  await form.getByRole('button', { name: '참가자 저장', exact: true }).click();
  const sequenceAlert = page.locator('#participant-sequence_no-error');
  await expect(sequenceAlert).toHaveText('순번 1은 이미 D1(초코)이 쓰고 있습니다. 다른 순번을 입력하세요.');
  await expect(form.getByLabel('순번', { exact: true })).toBeFocused();
  await expect(form.getByLabel('순번', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  await expect(form.getByLabel('반려견 이름', { exact: true })).toHaveValue('콩이');
  await expect(page.getByText('중복 ID 또는 연결 충돌입니다', { exact: false })).toHaveCount(0);
  // 고치기 시작하면 그 칸의 오류가 사라진다.
  await form.getByLabel('순번', { exact: true }).fill('2');
  await expect(sequenceAlert).toHaveCount(0);
  await form.getByLabel('참가자 ID', { exact: true }).fill('D1');
  await form.getByRole('button', { name: '참가자 저장', exact: true }).click();
  await expect(page.locator('#participant-participant_id-error')).toContainText('참가자 ID D1는 이미 초코이(가) 쓰고 있습니다');
  await expect(form.getByLabel('참가자 ID', { exact: true })).toBeFocused();
  expect((await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'U04-DUP')).toHaveLength(1);
  // 다른 행사의 같은 순번은 허용한다.
  await form.getByLabel('행사 ID', { exact: true }).fill('U04-DUP-OTHER');
  await form.getByLabel('참가자 ID', { exact: true }).fill('D2');
  await form.getByLabel('순번', { exact: true }).fill('1');
  await form.getByRole('button', { name: '참가자 저장', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'D2 콩이 등록됨' })).toBeVisible();
});

test('형식 오류는 칸을 벗어날 때 한국어 문구로 칸 아래에 표시하고 저장을 막는다', async ({ page }) => {
  const form = await openRegistration(page);
  const ids: Record<string, string> = { '행사 ID': 'event_id', '참가자 ID': 'participant_id', '나이(세)': 'age_years', '반려견 이름': 'dog_name' };
  const alertOf = (label: string) => page.locator(`#participant-${ids[label]}-error`);
  await form.getByLabel('행사 ID', { exact: true }).fill('행사 1');
  await form.getByLabel('참가자 ID', { exact: true }).focus();
  await expect(alertOf('행사 ID')).toContainText('행사 ID는 영문·숫자·밑줄·하이픈만 쓸 수 있습니다');
  await form.getByLabel('참가자 ID', { exact: true }).fill('한 글');
  await form.getByLabel('순번', { exact: true }).focus();
  await expect(alertOf('참가자 ID')).toContainText('참가자 ID는 영문·숫자·밑줄·하이픈만');
  await form.getByLabel('나이(세)', { exact: true }).fill('99');
  await form.getByLabel('반려견 이름', { exact: true }).focus();
  await expect(alertOf('나이(세)')).toContainText('0~30 사이의 정수');
  await form.getByRole('button', { name: '참가자 저장', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '저장하지 못했습니다. 표시된 칸을 고쳐 다시 저장하세요.' })).toBeVisible();
  await expect(alertOf('반려견 이름')).toHaveText('반려견 이름을 입력하세요.');
  await expect(form.getByLabel('행사 ID', { exact: true })).toBeFocused();
  expect((await (await page.request.get('/api/cases')).json()).some((c: { dog_name: string }) => c.dog_name === '')).toBe(false);
});

test('기본 정보 정정에서도 중복 순번을 칸 아래에 표시한다', async ({ page }) => {
  await openRegistration(page, [['U04-EDIT', 'E1', 1, '초코'], ['U04-EDIT', 'E2', 2, '콩이']]);
  await page.getByRole('button', { name: 'E2 상세 열기', exact: true }).click();
  await page.getByText('참가자 기본 정보 정정', { exact: true }).click();
  const editor = page.locator('form').filter({ has: page.getByRole('button', { name: '기본 정보 정정 저장' }) });
  await editor.getByLabel('순번', { exact: true }).fill('1');
  await editor.getByRole('button', { name: '기본 정보 정정 저장' }).click();
  await expect(page.locator('#edit-sequence_no-error')).toContainText('순번 1은 이미 E1(초코)이 쓰고 있습니다');
  await expect(editor.getByLabel('순번', { exact: true })).toBeFocused();
  await editor.getByLabel('순번', { exact: true }).fill('2');
  await editor.getByRole('button', { name: '기본 정보 정정 저장' }).click();
  await expect(page.getByRole('status').filter({ hasText: '기본 정보를 정정했습니다.' })).toBeVisible();
});

test('목록 행 전체를 눌러 상세를 열고 채점 전 상태는 판본 표기 없이 쓴다', async ({ page }) => {
  await openRegistration(page, [['U04-ROW', 'W1', 1, '행클릭견']]);
  const row = page.getByRole('row').filter({ hasText: 'U04-ROW' });
  await expect(row.getByRole('button', { name: 'W1 상세 열기', exact: true })).toHaveText('열기');
  await expect(row.getByText('채점 전', { exact: true })).toBeVisible();
  await expect(row).not.toContainText('S1.1');
  await expect(row).not.toContainText('재분석');
  await row.getByText('행클릭견').first().click();
  await expect(page.getByRole('heading', { name: '행클릭견', exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: '채점 전' })).toContainText('아직 채점값이 없습니다');
  await expect(page.getByText('S1.1 · 10월 2일', { exact: true })).toBeHidden();
  await page.getByText('기술 정보', { exact: true }).click();
  await expect(page.getByText('촬영 기준:', { exact: false })).toContainText('S1.1 · 10월 2일');
});

test('동의 항목 세 개는 「동의서 확인」 묶음에 모이고 설명은 자세히 안에 있다', async ({ page }) => {
  const form = await openRegistration(page);
  const group = form.getByRole('group', { name: '동의서 확인', exact: true });
  await expect(group.getByLabel('촬영 영상·설문 사용 동의 확인')).toBeVisible();
  await expect(group.getByRole('combobox', { name: '영상·설문 분석 및 피드백 동의' })).toBeVisible();
  await expect(group.getByRole('combobox', { name: '낯선 요원 접근·접촉 동의' })).toBeVisible();
  await expect(group.getByText('기존 기록에서 자동으로 확대하지 않습니다', { exact: false })).toBeHidden();
  await group.getByText('자세히', { exact: true }).click();
  await expect(group.getByText('기존 기록에서 자동으로 확대하지 않습니다', { exact: false })).toBeVisible();
});
