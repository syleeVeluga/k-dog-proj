import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { openMenu } from './menu';

async function openImporter(page: Page) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await openMenu(page, '일괄 등록 (CSV·Excel)');
  return page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
}
const csvFile = (name: string, text: string) => ({ name, mimeType: 'text/csv', buffer: Buffer.from(text) });
const caseOf = async (page: Page, event: string, participant: string) =>
  (await (await page.request.get('/api/cases')).json()).find((c: { event_id: string; participant_id: string }) => c.event_id === event && c.participant_id === participant);

test('표준 양식을 내려받아 채워 올리면 열 연결을 하나도 고치지 않고 등록된다', async ({ page }) => {
  const form = await openImporter(page);
  await expect(form.getByRole('link', { name: /내려받기$/ })).toHaveCount(4);
  const downloading = page.waitForEvent('download');
  await form.getByRole('link', { name: '명단 + 설문 28문항 CSV 내려받기', exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe('kdog-roster-survey.csv');
  const header = (await readFile(await download.path(), 'utf8')).replace(/^﻿/, '').trim();
  expect(header.split(',').slice(0, 3)).toEqual(['참가자 ID', '반려견 이름', '보호자 이름']);
  const row = ['0101', '양식견', '양식보호자', '', '101', '예', '확인', '미확인', '믹스', '수', '3', '소형', '2년', '입양', ...Array(28).fill('3')].join(',');
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-TEMPLATE');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('kdog-roster-survey.csv', `${header}\n${row}\n`));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 42개 · 확인 필요 0개 · 연결 안 됨 0개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1개 원행의 참가자·설문 등록을 확인했습니다.' })).toBeVisible();
  const created = await caseOf(page, 'U02-TEMPLATE', '0101');
  expect(created.dog_name).toBe('양식견');
  expect(created.sequence_no).toBe(101);
  expect(created.manifest.sessions[0].survey.s28).toBe(3);
});

test('명단만 있는 파일도 등록되고 설문은 미등록으로 남는다', async ({ page }) => {
  const form = await openImporter(page);
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-ROSTER');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('roster.csv', '참가번호,강아지 이름,보호자명\n0201,명단견,명단보호자\n'));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 3개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1개 원행의 참가자·설문 등록을 확인했습니다.' })).toBeVisible();
  const created = await caseOf(page, 'U02-ROSTER', '0201');
  expect(Object.values(created.manifest.sessions[0].survey).filter(value => value !== null)).toHaveLength(0);
});

test('같은 항목에 맞는 열이 둘이면 연결하지 않고 확인 필요로 알린다', async ({ page }) => {
  const form = await openImporter(page);
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('alias.csv', '접수번호,강아지 이름,Q1,1번,나이(세),타임스탬프\n0301,별칭견,3,4,5,2026-10-11\n'));
  await expect(form.getByRole('status').filter({ hasText: '자동 연결 3개 · 확인 필요 1개 · 연결 안 됨 1개' })).toBeVisible();
  await expect(form.getByText('1번 응답에 맞는 열이 여러 개입니다(Q1, 1번)', { exact: false })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await expect(form.getByLabel('폼 열 participant_id', { exact: true })).toHaveValue('접수번호');
  await expect(form.getByLabel('폼 열 dog_age_years', { exact: true })).toHaveValue('나이(세)');
  await form.getByText('28문항과 빈칸 사유 연결', { exact: true }).click();
  await expect(form.getByLabel('폼 열 s01', { exact: true })).toHaveValue('');
});

test('미리보기 버튼이 막혀 있으면 옆에 빠진 조건을 쓴다', async ({ page }) => {
  const form = await openImporter(page);
  const button = form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true });
  await expect(button).toBeDisabled();
  await expect(form.getByText('파일을 올리세요.', { exact: true })).toBeVisible();
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('no-dog.csv', '참가자 ID,보호자 이름\n0401,보호자\n'));
  await expect(form.getByText('행사 ID를 입력하세요.', { exact: true })).toBeVisible();
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-REASON');
  await expect(form.getByText('반려견 이름 열을 연결하세요.', { exact: true })).toBeVisible();
  await expect(button).toBeDisabled();
  await form.getByLabel('폼 필수 열 dog_name', { exact: true }).selectOption('보호자 이름');
  await expect(button).toBeEnabled();
  await form.getByText('고급 설정', { exact: true }).click();
  await form.getByLabel('원자료 프로필', { exact: true }).fill('');
  await expect(form.getByText('고급 설정에서 원자료 프로필과 매핑 버전을 입력하세요.', { exact: true })).toBeVisible();
  const check = form.getByRole('checkbox', { name: '과거 판본 원자료 참고만 등록' });
  expect((await check.boundingBox())!.width).toBeLessThan(30);
});

test('같은 원라벨을 선택한 여러 문항에 한 번에 적용한다', async ({ page }) => {
  const form = await openImporter(page);
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-LABELS');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('labels.csv', '강아지,Q10,Q11,Q12\n라벨견,없음,보통,없음\n'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 0개 · 오류 1개', exact: true })).toBeVisible();
  await form.getByText('모든 연결 보기', { exact: true }).click();
  await form.getByText('선택 문항에 같은 라벨 적용', { exact: true }).first().click();
  await form.getByLabel('라벨 적용 문항', { exact: true }).fill('10-12');
  await form.getByLabel('라벨 일괄 입력', { exact: true }).fill('없음=0\n보통=2');
  await form.getByRole('button', { name: '선택 문항에 같은 라벨 적용', exact: true }).click();
  await expect(form.getByText('3개 문항에 같은 라벨을 적용했습니다.', { exact: false })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await form.getByLabel('라벨 적용 문항', { exact: true }).fill('0-99');
  await form.getByRole('button', { name: '선택 문항에 같은 라벨 적용', exact: true }).click();
  await expect(form.getByText('문항 번호는 「1-9, 15, 20-28」처럼', { exact: false })).toBeVisible();
});

test('마지막으로 쓴 행사 ID를 제안하고 저장소가 막혀도 동작한다', async ({ page }) => {
  const form = await openImporter(page);
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-REMEMBER');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('remember.csv', '강아지\n기억견\n'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
  await page.reload();
  await expect(form.getByLabel('폼 행사 ID', { exact: true })).toHaveValue('U02-REMEMBER');
  await page.addInitScript(() => { Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } }); });
  await page.reload();
  await expect(form.getByLabel('폼 행사 ID', { exact: true })).toHaveValue('');
  await form.getByLabel('폼 행사 ID', { exact: true }).fill('U02-BLOCKED');
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('blocked.csv', '강아지\n무저장견\n'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 1개 · 오류 0개', exact: true })).toBeVisible();
});
