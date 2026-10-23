import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { openMenu } from './menu';

for (const format of ['csv', 'xlsx']) {
test(`Forms ${format} 원라벨 검증·일괄 등록·재시도·명시적 연결과 입력 충돌`, async ({ page }, testInfo) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await openMenu(page, '참가자 및 설문 일괄 등록');
  const form = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  const eventId = `FORMS-BROWSER-${format}`;
  await form.getByLabel('폼 행사 ID', { exact: true }).fill(eventId);
  const buffer = format === 'csv' ? Buffer.from('강아지,보호자,Q10,Q11\n합성 동명이견,동명이인,없음,2\n합성 동명이견,동명이인,2,4\n')
    : execFileSync('../backend/.venv/Scripts/python.exe', ['-X', 'utf8', '-c', "import io,sys; from openpyxl import Workbook; w=Workbook(); w.active.title='안내'; w.active.append(['설명']); s=w.create_sheet('실제입력'); s.append(['강아지','보호자','Q10','Q11']); s.append(['합성 동명이견','동명이인','없음',2]); s.append(['합성 동명이견','동명이인',2,4]); b=io.BytesIO(); w.save(b); sys.stdout.buffer.write(b.getvalue())"]);
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles({ name: `synthetic-forms.${format}`, mimeType: 'application/octet-stream', buffer });
  if (format === 'xlsx') {
    await expect(form.getByLabel('원본 시트', { exact: true })).toHaveValue('안내');
    await form.getByLabel('원본 시트', { exact: true }).selectOption('실제입력');
  }
  // 헤더(강아지·보호자·Q10·Q11)가 알려진 이름이라 열 연결을 손으로 고르지 않는다.
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 4개 · 확인 필요 0개 · 연결 안 됨 0개' })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await expect(form.getByLabel('폼 열 dog_name', { exact: true })).toHaveValue('강아지');
  await expect(form.getByLabel('폼 열 s10', { exact: true })).toHaveValue('Q10');
  await form.getByText('28문항과 빈칸 사유 연결', { exact: true }).click();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 1개' })).toBeVisible();
  // 오류 1행은 제외하고 정상 1행만 등록할 수 있다. 조용히 숨기지 않고 버튼에 건수를 쓴다.
  await expect(form.getByRole('button', { name: '정상 1행 등록 · 오류 1행 제외', exact: true })).toBeEnabled();
  await expect(form.getByRole('button', { name: 'Forms 전체 확정', exact: true })).toHaveCount(0);
  await form.getByLabel('폼 라벨 s10', { exact: true }).fill('없음=0');
  const previewResponse = page.waitForResponse(response => response.url().endsWith('/api/forms/preview'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  const preview = await (await previewResponse).json();
  await expect(form.getByRole('heading', { name: '원행 2개 · 오류 0개' })).toBeVisible();
  expect(preview.rows[0].participant_id).not.toBe(preview.rows[1].participant_id);
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('이미 확정한 파일입니다. 재확정해도 참가자가 추가되지 않습니다.')).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  const cases = await (await page.request.get('/api/cases')).json();
  expect(cases.filter((c: { event_id: string }) => c.event_id === eventId)).toHaveLength(2);
  const first = cases.find((c: { case_id: string }) => c.case_id === preview.rows[0].case_id);
  expect(first.manifest.sessions[0].survey.s10).toBe(0);

  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles({ name: 'synthetic-change.csv', mimeType: 'text/csv', buffer: Buffer.from('Q10,Q11\n4,2\n') });
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 2개' })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await expect(form.getByLabel('폼 열 s10', { exact: true })).toHaveValue('Q10');
  await form.getByText(/기존 참가자·회차에 명시적으로 연결/).click();
  await form.getByRole('button', { name: '기존 대상 연결 추가' }).click();
  await form.getByLabel('연결 1 참가자', { exact: true }).selectOption(first.case_id);
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개' })).toBeVisible();
  await form.getByText(/2행 · 기존 응답 변경/).click();
  await expect(form.getByRole('row', { name: 's10 0 4 — —' })).toBeVisible();
  const session = first.manifest.sessions[0];
  const changed = await page.request.put(`/api/cases/${first.case_id}/survey`, { headers: { 'X-KDOG-Request': '1' }, data: {
    expected_revision: first.input_revision, session_id: first.selected_session_id, survey_version: session.survey_version,
    answers: { ...session.survey, s10: 1 }, not_applicable: [], blank_reasons: {},
  } });
  expect(changed.ok()).toBeTruthy();
  const conflict = page.waitForResponse(response => response.url().endsWith('/api/forms/commit'));
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await form.getByRole('button', { name: '대상 최신 상태로 다시 연결' }).click();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('이미 확정한 파일입니다. 재확정해도 참가자가 추가되지 않습니다.')).toBeVisible();
  const updated = await (await page.request.get(`/api/cases/${first.case_id}`)).json();
  expect(updated.manifest.sessions[0].survey.s10).toBe(4);
  await form.getByText('고급 설정', { exact: true }).click();
  await form.getByLabel('파일 배치', { exact: true }).selectOption('transposed');
  await expect(form.getByRole('status').filter({ hasText: '자동 연결' })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await expect(form.getByText('기존 참가자·회차에 명시적으로 연결 (0)', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath(`forms-v4-${format}.png`), fullPage: true });
  expect(errors).toEqual([]);
});
}
