import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
async function openImporter(page: Page) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await openMenu(page, '참가자 및 설문 일괄 등록');
  return page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
}
const csvFile = (name: string, text: string) => ({ name, mimeType: 'text/csv', buffer: Buffer.from(text) });
async function register(page: Page, event: string, ids: string[]) {
  for (const id of ids) {
    const created = await page.request.post('/api/cases', { headers, data: { event_id: event, participant_id: id, dog_name: `접수견${id}` } });
    expect(created.status()).toBe(201);
  }
}
const caseOf = async (page: Page, event: string, participant: string) =>
  (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string; participant_id: string }) => c.event_id === event && c.participant_id === participant);

test('접수 후 설문 파일: 기존 참가자 갱신 확인, 오류 행 제외 등록, 오류 행 CSV를 고쳐 다시 올리기', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  await register(page, 'U03-FIELD', ['F301', 'F302', 'F303']);
  await openMenu(page, '참가자 및 설문 일괄 등록');
  const form = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U03-FIELD');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('survey.csv', '참가자 ID,Q1,Q2\nF301,3,4\nF302,maybe,4\nF303,5,5\n'));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 3개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 2개 · 오류 1개', exact: true })).toBeVisible();
  await expect(form.getByText(/2행 · 기존 참가자 갱신 · F301 접수견F301 · 1차 촬영/)).toBeVisible();
  const confirm = form.getByRole('checkbox', { name: '기존 참가자 갱신 확인' });
  await expect(form.getByText('기존 참가자 2명 갱신 확인', { exact: true })).toBeVisible();
  const commit = form.getByRole('button', { name: '정상 2행 등록 · 오류 1행 제외', exact: true });
  await expect(commit).toBeDisabled();
  await expect(form.getByText('「기존 참가자 갱신 확인」을 체크하세요.', { exact: true })).toBeVisible();
  await form.getByText(/2행 · 기존 참가자 갱신/).click();
  await expect(form.getByRole('row', { name: 's01 3 3 — —' }).or(form.getByRole('row', { name: 's01 빈칸 3 — —' }))).toBeVisible();
  const downloading = page.waitForEvent('download');
  await form.getByRole('button', { name: '오류 행 CSV 내려받기', exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^kdog-forms-errors-U03-FIELD-\d{8}-\d{6}\.csv$/);
  const errorCsv = await readFile(await download.path(), 'utf8');
  expect(errorCsv.startsWith('﻿참가자 ID,Q1,Q2,오류 사유')).toBe(true);
  expect(errorCsv).toContain('F302,maybe,4,');
  expect(errorCsv).not.toContain('F301,3,4');
  await expect(form.getByText('현장 PC에만 보관하고 작업 후 삭제하세요.')).toBeVisible();
  await confirm.check();
  await expect(commit).toBeEnabled();
  expect((await caseOf(page, 'U03-FIELD', 'F301')).manifest.sessions[0].survey.s01).toBeNull();
  await commit.click();
  await expect(form.getByText('등록 결과: 정상 2행 등록 · 오류 1행 제외', { exact: true })).toBeVisible();
  expect((await caseOf(page, 'U03-FIELD', 'F301')).manifest.sessions[0].survey).toMatchObject({ s01: 3, s02: 4 });
  expect((await caseOf(page, 'U03-FIELD', 'F303')).manifest.sessions[0].survey).toMatchObject({ s01: 5, s02: 5 });
  expect((await caseOf(page, 'U03-FIELD', 'F302')).manifest.sessions[0].survey.s01).toBeNull();
  expect((await caseOf(page, 'U03-FIELD', 'F301')).dog_name).toBe('접수견F301');
  // 내려받은 CSV의 오류 값을 고쳐 다시 올린다. 「오류 사유」 열은 연결 대상이 아니라 무시된다.
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('fixed.csv', errorCsv.replace('maybe', '4')));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 3개 · 확인 필요 0개 · 연결 안 됨 1개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await expect(form.getByText(/2행 · 기존 참가자 갱신 · F302 접수견F302/)).toBeVisible();
  await form.getByRole('checkbox', { name: '기존 참가자 갱신 확인' }).check();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('등록 결과: 정상 1행 등록', { exact: true })).toBeVisible();
  expect((await caseOf(page, 'U03-FIELD', 'F302')).manifest.sessions[0].survey).toMatchObject({ s01: 4, s02: 4 });
});

test('이름이 같고 ID가 다르면 신규로 등록하고 갱신 확인이 필요 없다', async ({ page }) => {
  const form = await openImporter(page);
  await register(page, 'U03-NAME', ['N301']);
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U03-NAME');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('same-name.csv', '참가자 ID,반려견 이름,Q1\nN302,접수견N301,3\n'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await expect(form.getByText(/2행 · 신규/)).toBeVisible();
  await expect(form.getByRole('checkbox', { name: '기존 참가자 갱신 확인' })).toHaveCount(0);
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('등록 결과: 정상 1행 등록', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === 'U03-NAME')).toHaveLength(2);
});

test('열 연결 설정을 저장하고 다른 파일에서 불러온다', async ({ page }) => {
  const form = await openImporter(page);
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U03-PRESET');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('first.csv', '번호,강아지,응답1,메모\nP501,설정견,3,무시\n'));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 1개' })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await form.getByLabel('폼 열 participant_id', { exact: true }).selectOption('번호');
  await form.getByText('28문항과 빈칸 사유 연결', { exact: true }).click();
  await form.getByLabel('폼 열 s01', { exact: true }).selectOption('응답1');
  await form.getByText(/열 연결 설정 저장·불러오기/).click();
  const save = form.getByRole('button', { name: '현재 연결 저장', exact: true });
  await expect(save).toBeDisabled();
  await expect(form.getByText('저장할 설정 이름을 입력하세요.', { exact: true })).toBeVisible();
  await form.getByLabel('열 연결 설정 이름', { exact: true }).fill('2026 가을 신청폼');
  await save.click();
  await expect(form.getByText('‘2026 가을 신청폼’ 설정을 저장했습니다.', { exact: true })).toBeVisible();
  await form.getByLabel('열 연결 설정 이름', { exact: true }).fill('2026 가을 신청폼');
  await save.click();
  await expect(page.getByText('같은 이름의 열 연결 설정이 있습니다', { exact: false })).toBeVisible();
  await page.reload();
  const again = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  await again.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('second.csv', '번호,강아지,응답1,다른열\nP502,설정견2,4,무시\n'));
  await expect(again.getByRole('status').filter({ hasText: '자동 연결 1개' })).toBeVisible();
  await again.getByText(/열 연결 설정 저장·불러오기 \(1\)/).click();
  await again.getByLabel('저장된 열 연결 설정', { exact: true }).selectOption({ label: '2026 가을 신청폼 · operator' });
  await again.getByRole('button', { name: '선택한 설정 불러오기', exact: true }).click();
  await expect(again.getByText('‘2026 가을 신청폼’ 연결을 적용했습니다.', { exact: false })).toBeVisible();
  await expect(again.getByText(/참가자 ID ← 번호/)).toBeVisible();
  await expect(again.getByText(/설문 응답 1문항/)).toBeVisible();
  // 파일에 없는 헤더는 연결 안 됨으로 알린다.
  await again.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('third.csv', '번호,강아지\nP503,설정견3\n'));
  await again.getByText(/열 연결 설정 저장·불러오기 \(1\)/).click();
  await again.getByLabel('저장된 열 연결 설정', { exact: true }).selectOption({ label: '2026 가을 신청폼 · operator' });
  await again.getByRole('button', { name: '선택한 설정 불러오기', exact: true }).click();
  await expect(again.getByText('파일에 없는 열 1개는 연결 안 됨: 1번 응답(응답1)', { exact: false })).toBeVisible();
  page.once('dialog', dialog => void dialog.accept());
  await again.getByRole('button', { name: '선택한 설정 삭제', exact: true }).click();
  await expect(again.getByText('삭제했습니다.', { exact: true })).toBeVisible();
  await expect(again.getByText(/열 연결 설정 저장·불러오기 \(0\)/)).toBeVisible();
});
