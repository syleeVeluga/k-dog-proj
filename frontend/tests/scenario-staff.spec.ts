import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { openMenu } from './menu';

const password = 'Browser-test-only-42';
const headers = { 'X-KDOG-Request': '1' };
const EVENT = 'U07-FIELD';
const csvFile = (name: string, text: string) => ({ name, mimeType: 'text/csv', buffer: Buffer.from(text) });

// 합성 현장 리허설: 행사 스태프의 하루 흐름. 합성 바이트 파일만 쓰고 이 앱 서버 밖으로는 요청하지 않는다.
test('행사 스태프: 명단 양식 → 10명 일괄 등록 → 현장 1명 접수 → 설문 파일(갱신 확인·오류 1행 제외) → 원본1~3 연결 → 촬영 기록', async ({ page, baseURL }) => {
  test.setTimeout(120000);
  const outside: string[] = [];
  const origin = new URL(baseURL!).origin + '/';
  page.on('request', value => { if (!value.url().startsWith(origin) && !value.url().startsWith('data:') && !value.url().startsWith('blob:')) outside.push(value.url()); });
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();

  // 1) 표준 양식(명단만 CSV)을 내려받아 10명을 채워 올린다. 열 연결은 하나도 고치지 않는다.
  await openMenu(page, '일괄 등록 (CSV·Excel)');
  const form = page.getByRole('region', { name: 'Forms 참가자와 설문 등록', exact: true });
  const downloading = page.waitForEvent('download');
  await form.getByRole('link', { name: '명단만 CSV 내려받기', exact: true }).click();
  const header = (await readFile(await (await downloading).path(), 'utf8')).replace(/^﻿/, '').trim();
  const columns = header.split(',');
  const rows = Array.from({ length: 10 }, (_, index) => {
    const row = columns.map(() => '');
    row[columns.indexOf('참가자 ID')] = `F${String(index + 1).padStart(2, '0')}`;
    row[columns.indexOf('반려견 이름')] = `현장견${index + 1}`;
    row[columns.indexOf('순번')] = String(index + 1);
    return row.join(',');
  });
  await form.getByLabel('폼 행사 ID', { exact: true }).fill(EVENT);
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('roster-10.csv', `${header}\n${rows.join('\n')}\n`));
  await expect(form.getByRole('status').filter({ hasText: '확인 필요 0개 · 연결 안 됨 0개' })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 10개 · 오류 0개', exact: true })).toBeVisible();
  await form.getByRole('button', { name: 'Forms 전체 확정', exact: true }).click();
  await expect(form.getByText('등록 결과: 정상 10행 등록', { exact: true })).toBeVisible();

  // 2) 현장에서 명단에 없던 1명을 단건 접수한다(순번은 다음 번호가 제안된다).
  await openMenu(page, '참가자 접수');
  await expect(page.getByRole('button', { name: 'F10 상세 열기', exact: true })).toBeVisible();
  const details = page.locator('details').filter({ has: page.getByText('참가자 등록', { exact: true }) });
  if (await details.getAttribute('open') === null) await details.getByText('참가자 등록', { exact: true }).click();
  await expect(details).toHaveAttribute('open', '');
  const register = page.locator('form').filter({ has: page.getByLabel('행사 ID', { exact: true }) });
  await register.getByLabel('행사 ID', { exact: true }).fill(EVENT);
  await expect(register.getByLabel('순번', { exact: true })).toHaveValue('11');
  await register.getByLabel('참가자 ID', { exact: true }).fill('F11');
  await register.getByLabel('반려견 이름', { exact: true }).fill('현장견11');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'F11 현장견11 등록됨' })).toBeVisible();

  // 3) 설문 응답 파일: 기존 참가자 갱신 확인 후 오류 1행은 제외하고 등록한다.
  await openMenu(page, '일괄 등록 (CSV·Excel)');
  await form.getByLabel('폼 행사 ID', { exact: true }).fill(EVENT);
  await form.getByLabel('Forms 파일', { exact: true }).setInputFiles(csvFile('survey.csv', '참가자 ID,Q1,Q2\nF01,3,4\nF02,maybe,4\nF11,5,5\n'));
  await form.getByRole('button', { name: 'Forms 등록 미리보기', exact: true }).click();
  await expect(form.getByRole('heading', { name: '원행 2개 · 오류 1개', exact: true })).toBeVisible();
  await form.getByRole('checkbox', { name: '기존 참가자 갱신 확인' }).check();
  await form.getByRole('button', { name: '정상 2행 등록 · 오류 1행 제외', exact: true }).click();
  await expect(form.getByText('등록 결과: 정상 2행 등록 · 오류 1행 제외', { exact: true })).toBeVisible();

  // 4) 영상 3개(원본1~3)를 받아 카메라를 고치지 않고 한 참가자에 연결한다.
  await openMenu(page, '영상 수신·연결');
  await page.getByLabel('수신 파일', { exact: true }).setInputFiles(['원본1.mp4', '원본2.mp4', '원본3.mp4'].map((name, index) => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(`u07 rehearsal ${name} ${index}`) })));
  await page.getByRole('button', { name: '파일 수신 시작·재시도', exact: true }).click();
  for (const name of ['원본1.mp4', '원본2.mp4', '원본3.mp4']) {
    const card = page.getByRole('article', { name: `수신물 ${name}`, exact: true });
    await expect(card.getByText('수신 완료', { exact: true })).toBeVisible();
    await card.getByLabel('참가자 찾기', { exact: true }).fill('현장견11');
    await card.getByLabel('연결 참가자', { exact: true }).selectOption({ index: 1 });
    await card.getByRole('button', { name: '연결', exact: true }).click();
    await expect(card).toHaveCount(0);
  }

  // 5) 촬영 기록 화면: 연결한 영상이 한눈에 보인다.
  await openMenu(page, '촬영 기록 (8구간)');
  await page.getByRole('button', { name: 'F11 촬영 열기', exact: true }).click();
  const panel = page.getByRole('region', { name: 'S1 촬영 기록', exact: true });
  await expect(panel.getByText('1차 촬영 · 연결된 영상 3개 · 사용 가능 0 · 영상 읽기 확인 대기 3', { exact: true })).toBeVisible();
  const videos = (await (await page.request.get('/api/cases')).json()).find((c: { participant_id: string; event_id: string }) => c.event_id === EVENT && c.participant_id === 'F11').manifest.sessions[0].videos;
  expect(Object.fromEntries(videos.map((video: { original_name: string; camera_id: string }) => [video.original_name, video.camera_id]))).toEqual({ '원본1.mp4': 'CAM1', '원본2.mp4': 'CAM3', '원본3.mp4': 'CAM2' });
  const cases = (await (await page.request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === EVENT);
  expect(cases).toHaveLength(11);
  expect(cases.find((c: { participant_id: string }) => c.participant_id === 'F01').manifest.sessions[0].survey.s01).toBe(3);
  expect(cases.find((c: { participant_id: string }) => c.participant_id === 'F02').manifest.sessions[0].survey.s01).toBeNull();
  expect(outside).toEqual([]);
});

test.afterAll(async ({ request }) => {
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  for (const item of (await (await request.get('/api/cases')).json()).filter((c: { event_id: string }) => c.event_id === EVENT))
    await request.post(`/api/cases/${item.case_id}/deletion`, { headers, data: { expected_revision: item.input_revision } });
});
