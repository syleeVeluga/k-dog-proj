import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test.afterEach(async ({ page }) => {
  const cases = await (await page.request.get('/api/cases')).json();
  for (const item of cases.filter((c: { event_id: string }) => c.event_id.startsWith('MAP-'))) {
    await page.request.post(`/api/cases/${item.case_id}/deletion`, { headers: { 'X-KDOG-Request': '1' }, data: { expected_revision: item.input_revision } });
  }
});

for (const format of ['csv', 'xlsx']) {
  test(`${format} 참가자 필수 3열 연결과 커밋 충돌 재검증`, async ({ page }, testInfo) => {
    await page.goto('/');
    await page.getByLabel('계정', { exact: true }).fill('operator');
    await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await page.getByRole('button', { name: '자료 가져오기', exact: true }).click();
    await page.getByLabel('입력 양식').selectOption('mapped');
    const event = `MAP-${format}`;
    const buffer = format === 'csv' ? Buffer.from(`행사,번호,이름\n${event},0001,합성견\n`) : execFileSync('../backend/.venv/Scripts/python.exe', ['-c', `import io,sys; from openpyxl import Workbook; w=Workbook(); w.active.title='안내'; w.active.append(['설명']); s=w.create_sheet('실제입력'); s.append(['행사','번호','이름']); s.append(['${event}','0001','합성견']); b=io.BytesIO(); w.save(b); sys.stdout.buffer.write(b.getvalue())`]);
    await page.getByLabel('입력 파일').setInputFiles({ name: `minimal.${format}`, mimeType: 'application/octet-stream', buffer });
    await page.getByRole('button', { name: '연결할 열 불러오기' }).click();
    if (format === 'xlsx') {
      await expect(page.getByLabel('Excel 시트', { exact: true })).toHaveValue('안내');
      await page.getByLabel('Excel 시트', { exact: true }).selectOption('실제입력');
      await page.getByRole('button', { name: '연결할 열 불러오기' }).click();
    } else {
      await expect(page.getByText('Excel 시트 불러오기', { exact: true })).toHaveCount(0);
    }
    await page.getByRole('combobox', { name: '행사 ID', exact: true }).selectOption('행사');
    await page.getByRole('combobox', { name: '참가자 ID', exact: true }).selectOption('번호');
    await page.getByRole('combobox', { name: '반려견 이름', exact: true }).selectOption('이름');
    await page.getByRole('button', { name: '검증 미리보기', exact: true }).click();
    await expect(page.getByRole('heading', { name: '검증 결과 · 정상 1행 / 오류 0행' })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`minimal-${format}.png`), fullPage: true });
    await page.getByRole('button', { name: '정상 1행 저장', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '1개 정상 행을 저장했습니다.' })).toBeVisible();
    const registered = (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string }) => c.event_id === event);
    expect(registered.sequence_no).toBeNull();
    expect(registered.guardian_name).toBe('');
    // The preview is valid, then another request reserves the sequence before commit.
    await page.getByLabel('입력 양식').selectOption('standard');
    await page.getByLabel('입력 파일').setInputFiles({ name: 'race.csv', mimeType: 'text/csv', buffer: Buffer.from(`event_id,participant_id,dog_name,sequence_no\n${event},0002,둘,2\n${event},0003,셋,3\n`) });
    await page.getByRole('button', { name: '검증 미리보기', exact: true }).click();
    await expect(page.getByRole('button', { name: '정상 2행 저장', exact: true })).toBeVisible();
    await page.request.post('/api/cases', { headers: { 'X-KDOG-Request': '1' }, data: { event_id: event, participant_id: 'racer', dog_name: '합성', sequence_no: 3 } });
    await page.getByRole('button', { name: '정상 2행 저장', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('검증 미리보기를 다시 실행하세요');
    await expect(page.getByRole('button', { name: '정상 2행 저장', exact: true })).toHaveCount(0);
    const cases = await (await page.request.get('/api/cases')).json();
    expect(cases.some((c: { event_id: string; participant_id: string }) => c.event_id === event && c.participant_id === '0002')).toBe(false);
  });
}
