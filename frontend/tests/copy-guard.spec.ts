import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { openMenu } from './menu';

const password = 'Browser-test-only-42';
const headers = { 'X-KDOG-Request': '1' };

// 운영자·교수 화면에 개발 진행 코드와 내부 식별자가 기본으로 노출되지 않는지 점검한다. 닫힌 「기술 정보」 접기는 보이는 텍스트가 아니므로 제외된다.
const DEV_CODES = /\bS1(?![-\w])|S1\.1|\bS16\b|\bS17\b|\bG0[1-5]\b|\bD0[1-6]\b|공급자 호출|교수 테스트|확인 대기입니다/;
const UUID = /\b(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b/;
const HASH = /\b[0-9a-f]{64}\b/;

async function login(page: Page, username: string) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}
async function offenders(page: Page, where: string) {
  const text = await page.locator('main').innerText();
  const found: string[] = [];
  for (const [name, pattern] of [['개발 코드', DEV_CODES], ['UUID', UUID], ['64자리 해시', HASH]] as const)
    for (const match of text.matchAll(new RegExp(pattern.source, 'g')))
      found.push(`${where}: ${name} 「${text.slice(Math.max(0, match.index - 25), match.index + 45).replace(/\s+/g, ' ')}」`);
  return found;
}
async function walk(page: Page, labels: string[]) {
  const found: string[] = [];
  for (const label of labels) {
    await openMenu(page, label);
    await expect(page.locator('main h1').first()).toBeVisible();
    await expect(page.getByText(/조회 중…|불러오는 중…/)).toHaveCount(0);
    await page.waitForTimeout(300);
    found.push(...await offenders(page, label));
  }
  return found;
}

test.describe('화면 문구 점검', () => {
  test.beforeAll(async ({ request }) => {
    await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
    for (const [id, sequence] of [['CG1', 1], ['CG2', 2]] as const) {
      const created = await request.post('/api/cases', { headers, data: { event_id: 'U07-GUARD', participant_id: id, dog_name: `문구견${id}`, sequence_no: sequence, consents: { analysis_feedback: 'confirmed' } } });
      expect(created.status()).toBe(201);
      const item = await created.json();
      expect((await request.put(`/api/cases/${item.case_id}/survey`, { headers, data: {
        expected_revision: item.input_revision, session_id: item.selected_session_id, survey_version: 'survey-20260929-v3',
        answers: Object.fromEntries(Array.from({ length: 28 }, (_, index) => [`s${String(index + 1).padStart(2, '0')}`, 3])),
      } })).status()).toBe(200);
    }
  });
  test.afterAll(async ({ request }) => {
    await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
    for (const item of (await (await request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'U07-GUARD'))
      await request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
  });

  test('점검 자체가 실제로 걸러 낸다(카나리: 개발 코드·UUID·해시를 심으면 모두 잡는다)', async ({ page }) => {
    await login(page, 'operator');
    await page.locator('main').evaluate(main => {
      const probe = document.createElement('p');
      probe.textContent = 'S1 판본 · G03 확인 · 3f2b8c1e-1a2b-4c3d-8e4f-5a6b7c8d9e0f · ' + 'ab12'.repeat(16);
      main.append(probe);
    });
    const found = await offenders(page, '카나리');
    expect(found.some(line => line.includes('개발 코드'))).toBe(true);
    expect(found.some(line => line.includes('UUID'))).toBe(true);
    expect(found.some(line => line.includes('64자리 해시'))).toBe(true);
  });

  test('운영자 메뉴 전체에 개발 코드·UUID·해시가 기본 노출되지 않는다', async ({ page }) => {
    await login(page, 'operator');
    const found = await walk(page, ['참가자 접수', '일괄 등록 (CSV·Excel)', '설문 현황', '영상 수신·연결', '촬영 기록 (8구간)', '전처리', '독립 채점', '리포트 발급', '비교 조건', '연구 내보내기', '검수 자료']);
    expect(found).toEqual([]);
  });

  test('교수/검토자 메뉴 전체에 개발 코드·UUID·해시가 기본 노출되지 않는다', async ({ page }) => {
    await login(page, 'reviewer');
    const found = await walk(page, ['참가자 접수', '설문 현황', '촬영 기록 (8구간)', '전처리', '독립 채점']);
    expect(found).toEqual([]);
  });

  test('관리자 전용 화면(직원 계정·백업·복구)도 같은 기준을 지킨다', async ({ page }) => {
    await login(page, 'admin');
    const found = await walk(page, ['직원 계정', '백업·복구']);
    expect(found).toEqual([]);
  });

  test('참가자를 연 상세·설문·촬영 화면도 같은 기준을 지킨다', async ({ page }) => {
    await login(page, 'operator');
    await page.getByRole('button', { name: 'CG1 상세 열기', exact: true }).click();
    const found = await offenders(page, '접수 상세');
    await openMenu(page, '설문 현황');
    await expect(page.getByText('결과 조회 중…')).toHaveCount(0);
    found.push(...await offenders(page, '설문(선택)'));
    await openMenu(page, '촬영 기록 (8구간)');
    found.push(...await offenders(page, '촬영 기록(선택)'));
    // 선택한 참가자는 메뉴를 옮겨도 유지되므로 분석 단계 화면도 그 참가자 기준으로 열린다.
    for (const label of ['전처리', '독립 채점', '리포트 발급', '연구 내보내기']) {
      await openMenu(page, label);
      await page.waitForTimeout(800);
      found.push(...await offenders(page, `${label}(선택)`));
    }
    expect(found).toEqual([]);
  });
});
