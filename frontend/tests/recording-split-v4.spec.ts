import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/;

async function start(page: Page, people: [string, string, number | null][]) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill('operator');
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
  const ids: string[] = [];
  for (const [id, dog, sequence] of people) {
    const created = await page.request.post('/api/cases', { headers, data: { event_id: `U05-${people[0][0]}`, participant_id: id, dog_name: dog, sequence_no: sequence } });
    expect(created.status()).toBe(201);
    ids.push((await created.json()).case_id);
  }
  await page.reload();
  await openMenu(page, '영상 파일 업로드');
  return ids;
}
async function receive(page: Page, names: string[]) {
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles(names.map((name, index) => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(`u05 synthetic ${name} ${index}`) })));
  await page.getByRole('button', { name: '업로드 시작·재시도', exact: true }).click();
  for (const name of names) await expect(page.getByRole('article', { name: `업로드 파일 ${name}`, exact: true }).getByText('업로드 완료', { exact: true })).toBeVisible();
}
const card = (page: Page, name: string) => page.getByRole('article', { name: `업로드 파일 ${name}`, exact: true });

test('원본1~3 파일명은 카메라와 원본 번호를 안내 표대로 미리 채워 고치지 않고 연결된다', async ({ page }) => {
  const [caseId] = await start(page, [['U5A', '연결견', 1]]);
  await receive(page, ['원본1.mp4', '원본2.mp4', '원본3.mp4']);
  const expected: Record<string, [string, string]> = { '원본1.mp4': ['CAM1', '1'], '원본2.mp4': ['CAM3', '2'], '원본3.mp4': ['CAM2', '3'] };
  for (const [name, [camera, original]] of Object.entries(expected)) {
    const target = card(page, name);
    await target.getByLabel('참가자', { exact: true }).selectOption(caseId);
    await expect(target.getByLabel('촬영 카메라 번호', { exact: true })).toHaveValue(camera.replace(/^CAM/, ''));
    await expect(target.getByLabel('원본 번호', { exact: true })).toHaveValue(original);
    await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toBeEnabled();
    await target.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
    // 같은 사례의 입력 버전이 바뀌므로 다음 파일은 이 연결이 끝난 뒤에 연결한다(동시에 누르면 충돌 후 「다시 저장」).
    await expect(target).toHaveCount(0);
  }
  await page.getByText(/^정보 저장 완료한 파일/).click();
  for (const name of Object.keys(expected)) await expect(card(page, name).getByText('등록됨 · 영상 읽기 확인 대기', { exact: true }).first()).toBeVisible();
  const videos = (await (await page.request.get(`/api/cases/${caseId}`)).json()).manifest.sessions[0].videos;
  expect(Object.fromEntries(videos.map((video: { original_name: string; camera_id: string; source_original_number: string }) => [video.original_name, [video.camera_id, video.source_original_number]]))).toEqual(expected);
});

test('규칙 밖 파일명은 번호를 비워 두고 영상 정보 저장이 막힌 이유를 표시한다', async ({ page }) => {
  const [caseId] = await start(page, [['U5B', '빈칸견', 1]]);
  await receive(page, ['misc-clip.mp4']);
  const target = card(page, 'misc-clip.mp4');
  await expect(target.getByLabel('촬영 카메라 번호', { exact: true })).toHaveValue('');
  await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toBeDisabled();
  await expect(target.getByText('참가자를 고르세요.', { exact: true })).toBeVisible();
  await target.getByLabel('참가자', { exact: true }).selectOption(caseId);
  await expect(target.getByText('촬영 카메라 번호를 입력하세요.', { exact: true })).toBeVisible();
  await target.getByLabel('촬영 카메라 번호', { exact: true }).fill('CAM9');
  await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toBeEnabled();
  await expect(target.getByRole('button', { name: '다시 저장', exact: true })).toHaveCount(0);
  await expect(target.getByText(/대상 연결·충돌 재시도/)).toHaveCount(0);
});

test('같은 참가자·회차에 같은 카메라를 다시 고르면 연결 전에 칸 아래 경고를 띄운다', async ({ page }) => {
  const [caseId] = await start(page, [['U5C', '경고견', 1]]);
  await receive(page, ['원본1.mp4', '원본1-재촬영.mp4']);
  const first = card(page, '원본1.mp4');
  await first.getByLabel('참가자', { exact: true }).selectOption(caseId);
  await first.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
  await expect(first).toHaveCount(0);
  const second = card(page, '원본1-재촬영.mp4');
  await second.getByLabel('참가자', { exact: true }).selectOption(caseId);
  await expect(second.getByLabel('촬영 카메라 번호', { exact: true })).toHaveValue('1');
  await expect(second.getByText('1차 촬영에 촬영 카메라 1 번호의 영상이 이미 등록되어 있습니다(원본1.mp4)', { exact: false })).toBeVisible();
  await expect(second.getByLabel('촬영 카메라 번호', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  await second.getByLabel('촬영 카메라 번호', { exact: true }).fill('2');
  await expect(second.getByText('이미 등록되어 있습니다', { exact: false })).toHaveCount(0);
});

test('참가자를 순번·ID·이름으로 찾고, 식별자는 기술 정보 안에만 있으며, 삭제는 확인을 받는다', async ({ page }) => {
  await start(page, [['U5D1', '초코', 1], ['U5D2', '보리', 2]]);
  await receive(page, ['search-clip.mp4']);
  const target = card(page, 'search-clip.mp4');
  const options = target.getByLabel('참가자', { exact: true }).locator('option');
  await target.getByLabel('참가자 찾기', { exact: true }).fill('보리');
  await expect(options.filter({ hasText: 'U5D2' })).toHaveCount(1);
  await expect(options.filter({ hasText: '초코' })).toHaveCount(0);
  await expect(options.filter({ hasText: 'U5D2' })).toHaveText('2번 · U5D2 · 보리 · U05-U5D1');
  expect(await target.innerText()).not.toMatch(UUID);
  expect(await target.innerText()).not.toMatch(/SHA-256|[0-9a-f]{64}/);
  await target.getByText('기술 정보', { exact: true }).click();
  await expect(target.getByText(/SHA-256 [0-9a-f]{64}/)).toBeVisible();
  const prompts: string[] = [];
  page.on('dialog', dialog => { prompts.push(dialog.message()); void dialog.dismiss(); });
  await target.getByRole('button', { name: '업로드 취소', exact: true }).click();
  await expect.poll(() => prompts.length).toBe(1);
  expect(prompts[0]).toContain('search-clip.mp4');
  expect(prompts[0]).toContain('업로드를 취소할까요');
  await expect(target).toBeVisible();
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => void dialog.accept());
  await target.getByRole('button', { name: '업로드 취소', exact: true }).click();
  // 취소하면 업로드가 취소된 기록으로 남고 실제 파일은 유지보수 때 정리된다. 내부 상태 코드는 기술 정보 안에만 있다.
  await expect(target.getByText('업로드 실패·취소', { exact: true })).toBeVisible();
  await expect(target.getByText('업로드가 취소되었습니다.', { exact: false })).toBeVisible();
  expect(await target.locator('p.warning').innerText()).not.toContain('cancelled');
  await expect(target.getByRole('button', { name: '업로드 취소', exact: true })).toHaveCount(0);
  await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toHaveCount(0);
});

test('촬영 기록 화면은 선택 참가자의 연결 영상 요약과 저장이 막힌 이유를 맨 위에 보여 준다', async ({ page }) => {
  const [caseId] = await start(page, [['U5E', '요약견', 1]]);
  await receive(page, ['원본1.mp4', '원본3.mp4']);
  for (const name of ['원본1.mp4', '원본3.mp4']) {
    await card(page, name).getByLabel('참가자', { exact: true }).selectOption(caseId);
    await card(page, name).getByRole('button', { name: '영상 정보 저장', exact: true }).click();
    await expect(card(page, name).getByRole('button', { name: '영상 정보 저장', exact: true })).toHaveCount(0);
  }
  await page.getByText(/^정보 저장 완료한 파일/).click();
  await expect(card(page, '원본3.mp4').getByText('등록됨 · 영상 읽기 확인 대기', { exact: true }).first()).toBeVisible();
  await openMenu(page, '촬영 기록 (8구간)');
  await page.getByRole('button', { name: 'U5E 촬영 열기', exact: true }).click();
  const panel = page.getByRole('region', { name: '촬영 기록', exact: true });
  await expect(panel.getByText('1차 촬영 · 연결된 영상 2개 · 사용 가능 0 · 영상 읽기 확인 대기 2', { exact: true })).toBeVisible();
  // 절차 확인 근거는 선택 입력이므로 비어 있어도 저장 안내가 뜨지 않는다.
  await expect(panel.getByText('실제 촬영 절차의 확인 근거를 기록해야 저장할 수 있습니다.', { exact: true })).toHaveCount(0);
  await expect(panel.getByRole('textbox', { name: '절차 확인 근거', exact: true })).toHaveValue('');
  // 연결·출처 구역보다 기록 패널이 위에 있고 첫 화면 안에서 시작한다.
  expect(await panel.evaluate(element => element.getBoundingClientRect().top + window.scrollY)).toBeLessThan(900);
});

test('파일명으로 채운 카메라를 고치면 원본 번호는 새 카메라 기준으로 정해져 어긋난 쌍이 저장되지 않는다', async ({ page }) => {
  const [caseId] = await start(page, [['U5F', '정정견', 1]]);
  await receive(page, ['원본1.mp4']);
  const target = card(page, '원본1.mp4');
  await target.getByLabel('참가자', { exact: true }).selectOption(caseId);
  await expect(target.getByLabel('원본 번호', { exact: true })).toHaveValue('1');
  await target.getByLabel('촬영 카메라 번호', { exact: true }).fill('2');
  await expect(target.getByLabel('원본 번호', { exact: true })).toHaveValue('');
  await expect(target.getByLabel('원본 번호', { exact: true })).toHaveAttribute('placeholder', '3');
  const saved = page.waitForResponse(response => response.request().method() === 'POST' && /\/uploads\/[^/]+\/link$/.test(response.url()));
  await target.getByRole('button', { name: '영상 정보 저장', exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await page.getByText(/^정보 저장 완료한 파일/).click();
  await expect(card(page, '원본1.mp4').getByText('등록됨 · 영상 읽기 확인 대기', { exact: true }).first()).toBeVisible();
  const videos = (await (await page.request.get(`/api/cases/${caseId}`)).json()).manifest.sessions[0].videos;
  expect(videos.map((video: { camera_id: string; source_original_number: string }) => [video.camera_id, video.source_original_number])).toEqual([['CAM2', '3']]);
});

test('촬영 카메라 번호 앞뒤 공백·잘못된 문자는 연결 전에 막고, 변환 MP4에는 중복 경고를 띄우지 않는다', async ({ page }) => {
  await start(page, [['U5G', '공백견', 1]]);
  await receive(page, ['misc-space.mp4']);
  const target = card(page, 'misc-space.mp4');
  await target.getByLabel('참가자', { exact: true }).selectOption({ index: 1 });
  await target.getByLabel('촬영 카메라 번호', { exact: true }).fill('   ');
  await expect(target.getByText('촬영 카메라 번호를 입력하세요.', { exact: true })).toBeVisible();
  await target.getByLabel('촬영 카메라 번호', { exact: true }).fill('캠 1');
  await expect(target.getByText('촬영 카메라 번호는 숫자 또는 영문·숫자·밑줄·하이픈으로 입력하세요.', { exact: true })).toBeVisible();
  await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toBeDisabled();
  await target.getByLabel('촬영 카메라 번호', { exact: true }).fill(' CAM1 ');
  await expect(target.getByRole('button', { name: '영상 정보 저장', exact: true })).toBeEnabled();
});
