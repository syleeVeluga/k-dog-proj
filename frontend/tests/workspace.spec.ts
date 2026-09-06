import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const headers = { 'X-KDOG-Request': '1' };
async function login(page: Page, role = 'operator') {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(role);
  await page.getByLabel('비밀번호', { exact: true }).fill('Browser-test-only-42');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
}
async function create(page: Page, id: string) {
  return (await page.request.post('/api/cases', { headers, data: { event_id: 'UX-TEST', participant_id: id, dog_name: `합성 검토견 ${id}` } })).json();
}
async function analysis(page: Page, id: string) {
  let item = await create(page, id);
  const base = `/api/cases/${item.case_id}`;
  item = await (await page.request.post(`${base}/videos`, { headers, data: Buffer.from('synthetic-workspace'), params: {
    session_id: item.selected_session_id, camera_id: 'CAM-1', filename: 'synthetic.mp4', expected_revision: item.input_revision,
  } })).json();
  const started = await (await page.request.post(`${base}/analysis`, { headers, data: { expected_revision: item.input_revision } })).json();
  const report = `${base}/reports/${started.runs[0].run_id}`;
  await expect.poll(async () => (await (await page.request.get(report)).json()).status).toBe('ready');
  return { item, base, report };
}

test('live list, mobile entry and explicit export selection', async ({ page }, testInfo) => {
  await login(page);
  await create(page, 'UX-0101');
  await create(page, 'UX-0102');
  await expect(page.getByRole('button', { name: 'UX-0101 상세 열기' })).toBeVisible();
  await page.setViewportSize({ width: 360, height: 800 });
  await page.getByLabel('검색', { exact: true }).fill('UX-0101');
  const entry = page.getByRole('button', { name: 'UX-0101 상세 열기' });
  const box = await entry.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  await page.getByRole('button', { name: '현재 목록 1명 선택' }).click();
  await page.getByText('전체 내보내기 · 운영자·교수용', { exact: true }).click();
  await page.getByRole('button', { name: '내보낼 대상 확인' }).click();
  const preview = page.getByLabel('내보내기 대상 미리보기');
  await expect(preview).toContainText('UX-0101');
  await expect(preview).not.toContainText('UX-0102');
  await page.getByRole('button', { name: '현재 버전으로 파일 생성' }).click();
  await expect(page.getByRole('link', { name: '파일 다운로드' }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('workspace-mobile-list.png'), fullPage: true });
});

test('evidence stays in viewport and another revision cannot erase a score draft', async ({ page }, testInfo) => {
  await login(page);
  const { item: participant, base, report } = await analysis(page, 'UX-0201');
  await page.getByRole('button', { name: 'UX-0201 상세 열기' }).click();
  await expect(page.getByLabel('허용 선택지', { exact: true })).toBeVisible();
  await page.getByLabel('점수 수정 사유', { exact: true }).fill('지우면 안 되는 검토 초안');
  const view = await (await page.request.get(report)).json();
  const item = view.result.evaluations.flatMap((a: any) => a.evaluation.items).find((i: any) => i.item_id === 'BS-01');
  const edited = await page.request.put(report, { headers, data: { expected_revision: view.revision, expected_source_hash: view.source_hash,
    reason: '다른 검토자의 수정', item: { ...item, reason: '다른 검토자의 수정' } } });
  expect(edited.status()).toBe(200);
  await expect(page.getByText('새 결과가 도착했습니다. 입력은 보존되었습니다.', { exact: false })).toBeVisible();
  await expect(page.getByLabel('점수 수정 사유')).toHaveValue('지우면 안 되는 검토 초안');
  await page.getByRole('button', { name: '점수 수정 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('수정 버전이 변경되었습니다');
  await expect(page.getByLabel('점수 수정 사유')).toHaveValue('지우면 안 되는 검토 초안');
  await page.getByRole('button', { name: '수정 근거 재생' }).first().click();
  const player = page.getByRole('dialog', { name: '원본 근거' });
  await expect(player).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: testInfo.outputPath('workspace-evidence-desktop.png') });
  await page.setViewportSize({ width: 360, height: 800 });
  await expect(player).toBeInViewport({ ratio: 1 });
  await page.keyboard.press('Escape');
  await expect(player).toHaveCount(0);
  await expect(page.getByRole('button', { name: '수정 근거 재생' }).first()).toBeFocused();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '← 참가자 목록' }).click();
  await expect(page.getByLabel('점수 수정 사유')).toHaveValue('지우면 안 되는 검토 초안');
  const reviewedRun = await page.getByLabel('관찰 실행 이력').inputValue();
  const newer = await page.request.post(`${base}/analysis`, { headers, data: { expected_revision: participant.input_revision } });
  expect(newer.status()).toBe(202);
  await expect(page.getByText('이전 실행 결과입니다. 현재 입력과 다를 수 있습니다.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('관찰 실행 이력')).toHaveValue(reviewedRun);
  await expect(page.getByLabel('점수 수정 사유')).toHaveValue('지우면 안 되는 검토 초안');
});

test('partial upload retries only unsaved files and preserves survey draft', async ({ page }) => {
  await login(page);
  await create(page, 'UX-0301');
  await page.getByRole('button', { name: 'UX-0301 상세 열기' }).click();
  await page.getByText('설문 원응답', { exact: false }).first().click();
  await page.getByLabel('q01 응답', { exact: true }).selectOption('4');
  let failed = false;
  const calls: string[] = [];
  await page.route('**/api/cases/*/videos?*', async route => {
    const name = new URL(route.request().url()).searchParams.get('filename')!;
    calls.push(name);
    if (name === 'second.mp4' && !failed) { failed = true; await route.fulfill({ status: 503, json: { detail: '합성 일시 장애' } }); }
    else await route.continue();
  });
  await page.getByLabel('영상 파일', { exact: true }).setInputFiles(['first.mp4', 'second.mp4', 'third.mp4'].map(name => ({ name, mimeType: 'video/mp4', buffer: Buffer.from(name) })));
  await page.getByRole('button', { name: '영상 등록', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1개 저장 · 1개 실패 · 1개 대기' })).toBeVisible();
  await expect(page.getByLabel('q01 응답', { exact: true })).toHaveValue('4');
  await page.getByRole('button', { name: '영상 등록', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '3개 저장 · 0개 실패 · 0개 대기' })).toBeVisible();
  expect(calls).toEqual(['first.mp4', 'second.mp4', 'second.mp4', 'third.mp4']);
  await expect(page.getByLabel('q01 응답', { exact: true })).toHaveValue('4');
  await page.getByText('재촬영 세션 추가', { exact: true }).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '새 촬영 시작', exact: true }).click();
  await expect(page.getByLabel('선택 세션', { exact: true }).getByRole('option')).toHaveCount(1);
  await expect(page.getByLabel('q01 응답', { exact: true })).toHaveValue('4');
});

test('reviewer browses previous session without changing the operational selection', async ({ page }) => {
  await login(page);
  const first = await create(page, 'UX-0401');
  const next = await (await page.request.post(`/api/cases/${first.case_id}/sessions`, { headers, data: { expected_revision: first.input_revision } })).json();
  await page.getByRole('button', { name: '로그아웃' }).click();
  await login(page, 'reviewer');
  await page.getByRole('button', { name: 'UX-0401 상세 열기' }).click();
  await page.getByLabel('선택 세션', { exact: true }).selectOption(first.selected_session_id);
  expect((await (await page.request.get(`/api/cases/${first.case_id}`)).json()).selected_session_id).toBe(next.selected_session_id);
  await expect(page.getByRole('button', { name: '촬영 정보 저장' })).toHaveCount(0);
});

test('paragraph evidence saves independently and keeps a separate score draft', async ({ page }) => {
  await login(page);
  const { report } = await analysis(page, 'UX-0501');
  const before = await (await page.request.get(report)).json();
  await page.getByRole('button', { name: 'UX-0501 상세 열기' }).click();
  await page.getByLabel('점수 수정 사유', { exact: true }).fill('별도로 보존할 점수 초안');
  await page.getByText('설명 수동 수정', { exact: true }).click();
  await page.getByRole('textbox', { name: '표지 관계 요약', exact: true }).fill('합성 문단 수정: 관찰 조건을 확인하세요.');
  await page.getByText('표지 관계 요약에 연결할 근거', { exact: true }).click();
  for (const checkbox of await page.locator('.narration-part').first().getByRole('checkbox').all()) await checkbox.uncheck();
  await page.getByLabel('설명 수정 사유', { exact: true }).fill('표지 문단만 정정');
  await page.getByRole('button', { name: '설명 수정 저장', exact: true }).click();
  await expect(page.getByText('수동 설명 저장됨', { exact: true })).toBeVisible();
  const after = await (await page.request.get(report)).json();
  expect(after.report.cover.evidence_ids).toEqual([]);
  expect(after.report.domains).toEqual(before.report.domains);
  expect(after.report.cross_type).toEqual(before.report.cross_type);
  expect(after.report.tips).toEqual(before.report.tips);
  expect(after.history.at(-1).before).toEqual(before.report);
  expect(after.history.at(-1).after.cover.text).toBe('합성 문단 수정: 관찰 조건을 확인하세요.');
  await expect(page.getByLabel('점수 수정 사유', { exact: true })).toHaveValue('별도로 보존할 점수 초안');
  await page.getByText(/수정 이력 · \d+건/).click();
  await expect(page.getByText('수정 전', { exact: true })).toBeVisible();
  await expect(page.getByText('수정 후', { exact: true })).toBeVisible();
});
