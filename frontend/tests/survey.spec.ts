import { test, expect } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
const ids = Array.from({ length: 28 }, (_, i) => `s${String(i + 1).padStart(2, '0')}`);

test('설문 menu: import a CSV with 해당 없음, see counts and the separation type, never a total', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  await page.request.post('/api/cases', { headers, data: { event_id: 'SURVEY-TEST', participant_id: '0011', dog_name: '설문 검증견', sequence_no: 11, guardian_name: '설문 보호자' } });
  const version = (await (await page.request.get('/api/catalog/survey')).json()).version;
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByRole('heading', { name: '설문', exact: true })).toBeVisible();
  const row = page.getByRole('row', { name: /0011/ });
  await expect(row.getByRole('cell', { name: '0/28', exact: true })).toBeVisible();
  const values = ids.map(id => id === 's08' ? 'NA' : ['s22', 's23'].includes(id) ? '4' : id === 's24' ? '5' : id === 's26' ? '1' : '3');
  await page.getByLabel('입력 파일', { exact: true }).setInputFiles({ name: 'survey.csv', mimeType: 'text/csv',
    buffer: Buffer.from(['event_id,participant_id,survey_version,' + ids.join(','), `SURVEY-TEST,0011,${version},` + values.join(','),
      `SURVEY-TEST,0011,${version},` + values.map(v => v === '3' ? '7' : v).join(',')].join('\n')) });
  await page.getByRole('button', { name: '검증 미리보기' }).click();
  await expect(page.getByText('검증 결과 · 정상 1행 / 오류 1행')).toBeVisible();
  await expect(page.getByText(/3행: 파일 안에 중복 참가자 ID가 있습니다/)).toBeVisible();
  await page.getByRole('button', { name: '정상 1행 저장' }).click();
  await expect(page.getByText('1개 정상 행을 저장했습니다.', { exact: true })).toBeVisible();
  await expect(row.getByRole('cell', { name: '28/28', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '0011 설문 현황 열기' }).click();
  const panel = page.getByLabel('설문 현황');
  await expect(panel.getByText('응답 8/9 · 미응답·해당 없음 1', { exact: true })).toBeVisible();
  await expect(panel.getByText('분리 유형: 안정', { exact: true })).toBeVisible();
  await expect(panel.getByText('총점은 만들지 않습니다.', { exact: false }).first()).toBeVisible();
  await expect(panel.getByText(/총점 \d/)).toHaveCount(0);
  await panel.getByText('설문 원응답', { exact: false }).click();
  await expect(panel.getByText('사회화 시기에 다양한 경험을 하도록 노력했다 · 해당 없음', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('survey-menu.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await page.getByLabel('계정', { exact: true }).fill('reviewer');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '설문', exact: true }).click();
  await expect(page.getByText('설문 파일 가져오기', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('row', { name: /0011/ }).getByRole('cell', { name: '28/28', exact: true })).toBeVisible();
});
