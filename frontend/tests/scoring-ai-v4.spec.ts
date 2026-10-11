import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import type { AiRunV4, AiSettingsViewV4 } from '../src/aiTypesV4';
import { openMenu } from './menu';

const headers = { 'X-KDOG-Request': '1' };
const password = 'Browser-test-only-42';

async function login(page: Page, username: string) {
  await page.goto('/');
  await page.getByLabel('계정', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible();
}

async function openScoring(page: Page, participant: string) {
  await openMenu(page, '독립 채점');
  await page.getByRole('button', { name: `${participant} 독립 채점 열기`, exact: true }).click();
}


test('S1 AI settings use explicit raw scope, immutable activation, schema-only validation and conflict guards', async ({ page, request }, testInfo) => {
  test.setTimeout(120000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await login(page, 'developer');
  const panel = page.getByRole('region', { name: 'AI 설정', exact: true });
  const initial: AiSettingsViewV4 = await (await page.request.get('/api/settings-s1')).json();
  await expect(panel.getByText(new RegExp(`${Object.keys(initial.groups).length}개 항목군 · 기본 예정 공급자 호출 ${initial.planned_provider_calls}회`))).toBeVisible();
  await expect(panel.getByText(/실제 공급자 정확도·처리 시간은 S16/)).toBeVisible();
  const group = Object.keys(initial.groups).find(key => initial.groups[key].provider_call)!;
  const deferred = Object.keys(initial.groups).find(key => !initial.groups[key].provider_call)!;
  await panel.getByLabel('설정할 항목군', { exact: true }).selectOption(group);
  await panel.getByLabel('공급자 요청 FPS', { exact: true }).fill('2');
  await panel.getByRole('button', { name: '설정 초안 저장', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('AI용 클립은 최대 1 FPS');
  await panel.getByLabel('입력 클립', { exact: true }).selectOption('original');
  await panel.getByLabel('공급자 요청 FPS', { exact: true }).fill('8');
  await panel.getByLabel('영상 읽기 방식', { exact: true }).selectOption('agentic');
  await expect(panel.getByLabel('공급자 요청 FPS', { exact: true })).toHaveCount(0);
  await panel.getByLabel('영상 읽기 방식', { exact: true }).selectOption('static');
  await panel.getByLabel('입력 클립', { exact: true }).selectOption('ai');
  const prompt = initial.config.groups[group].prompt + '\n합성 UI 설정 검증 전용';
  await panel.getByLabel('항목군 프롬프트', { exact: true }).fill(prompt);
  await panel.getByLabel('관찰 원자료 적용 범위를 확인했습니다. 애착 판단의 실제 적절성은 교수 테스트 대기입니다.', { exact: true }).check();
  const saved = page.waitForResponse(value => value.url().endsWith('/api/settings-s1') && value.request().method() === 'POST');
  await panel.getByRole('button', { name: '설정 초안 저장', exact: true }).click();
  const save = await saved; expect(save.status(), await save.text()).toBe(201); const version = (await save.json()).version;
  await expect(panel.getByText('활성 설정과의 차이', { exact: true })).toBeVisible();
  const trial = page.waitForResponse(value => value.url().endsWith(`/settings-s1/${version}/validate-s1`));
  await panel.getByRole('button', { name: '합성 스키마 검증 · 외부 호출 없음', exact: true }).click();
  const trialResult = await (await trial).json(); expect(trialResult.usage).toEqual({ provider_calls: 0 }); expect(trialResult.mode).toBe('schema');
  await expect(panel.getByRole('status')).toContainText('외부 호출 0회');
  await panel.getByRole('button', { name: '선택한 설정 활성화', exact: true }).click();
  await expect(panel.getByText(`활성 설정: ${version} · 비용: 미측정`, { exact: true })).toBeVisible();
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  expect((await (await request.get('/api/scoring-ai-s1/readiness')).json()).enabled).toBe(true);
  await panel.getByLabel('설정할 항목군', { exact: true }).selectOption(deferred);
  await expect(panel.getByText(/공급자에게 호출하지 않으며 null과 보류 사유/)).toBeVisible();
  await expect(panel.getByLabel('항목군 프롬프트', { exact: true })).toBeDisabled();
  await panel.getByLabel('설정할 항목군', { exact: true }).selectOption(group);
  await panel.getByLabel('항목군 프롬프트', { exact: true }).fill(prompt + '\n미저장 원문');
  const latest: AiSettingsViewV4 = await (await page.request.get('/api/settings-s1')).json();
  const next = await (await page.request.post('/api/settings-s1', { headers, data: { expected_active: latest.active_version, config: { ...latest.config, max_ai_calls: latest.config.max_ai_calls + 1 } } })).json();
  expect((await page.request.post(`/api/settings-s1/${next.version}/activate`, { headers, data: { expected_active: latest.active_version } })).status()).toBe(200);
  await panel.getByRole('button', { name: 'AI 설정 새로고침', exact: true }).click();
  await expect(panel.getByText(/다른 활성 설정이 저장되었습니다/)).toBeVisible();
  await panel.getByRole('button', { name: '설정 초안 저장', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('활성 설정이 바뀌었습니다');
  await expect(panel.getByLabel('항목군 프롬프트', { exact: true })).toHaveValue(prompt + '\n미저장 원문');
  page.once('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '미저장 설정 버리고 최신 조회', exact: true }).click();
  await expect(panel.getByLabel('항목군 프롬프트', { exact: true })).toHaveValue(prompt);
  await page.setViewportSize({ width: 360, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.screenshot({ path: testInfo.outputPath('ai-settings-s1-360.png'), animations: 'disabled' });
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  expect((await request.get('/api/settings-s1')).status()).toBe(403);
  expect(errors).toEqual([]);
});

test('S1 common AI operations preserve partial work, unknown billing, explicit reuse and idempotent retry', async ({ page, request }, testInfo) => {
  test.setTimeout(120000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  const item = await (await request.post('/api/cases', { headers, data: { event_id: 'S1-AI-UI', participant_id: 's1airun', dog_name: 'AI 운영 합성견', consents: { analysis_feedback: 'confirmed' } } })).json();
  const path = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  let enabled = false, outdated = false, forbidden = false, loseResponse = true;
  let runs: AiRunV4[] = [];
  const starts: Record<string, unknown>[] = [], actions: { action: string; value: Record<string, unknown> }[] = [];
  const run = (id: string, status: string): AiRunV4 => ({ run_id: id, case_id: item.case_id, session_id: item.selected_session_id, kind: 's1', input_revision: item.input_revision, status,
    updated_at: '2026-10-04T01:00:00+00:00', outdated: false, failure_code: status === 'partial' ? 'provider_timeout' : null, result_available: status === 'partial', planned_provider_calls: 43, reserved_calls: 2, max_ai_calls: 100, judgement_status: 'implemented_professor_test_pending',
    steps: [{ stage: 'score_v4', key: 'group-entry', attempt: 1, status: 'succeeded', code: null, billing_uncertain: false, call_reserved: true, reused: false, remote_cleanup_pending: false, timing: { upload_seconds: 1, inference_seconds: 2, stage_seconds: 4 }, token_meters: { total_tokens: 30 }, input_tokens: 20, output_tokens: 10, total_tokens: 30, cost_usd: null },
      { stage: 'score_v4', key: 'group-walk', attempt: 2, status: 'failed', code: 'provider_timeout', billing_uncertain: true, call_reserved: true, reused: false, remote_cleanup_pending: true, timing: { cleanup_seconds: 0.2 }, token_meters: {}, input_tokens: null, output_tokens: null, total_tokens: null, cost_usd: null }] });
  await page.route('**/api/scoring-ai-s1/readiness', route => route.fulfill({ json: { active_version: 'synthetic-settings', planned_provider_calls: 43, enabled, judgement_status: 'implemented_professor_test_pending' } }));
  await page.route('**' + path + '/preprocess-s1', route => route.fulfill({ json: { status: 'partial', input_revision: item.input_revision, outdated, result_pointer: { ref: 'synthetic/batch.json', hash: 'a'.repeat(64) } } }));
  await page.route('**' + path + '/runs-s1', async route => {
    if (route.request().method() === 'GET') { await route.fulfill(forbidden ? { status: 403, json: { detail: '실행 조회 권한이 없습니다.' } } : { json: runs }); return; }
    starts.push(route.request().postDataJSON());
    if (loseResponse) { loseResponse = false; await route.abort('failed'); return; }
    runs = [run(`synthetic-run-${starts.length}`, starts.length > 2 ? 'queued' : 'partial'), ...runs];
    if (starts.at(-1)?.reuse_run_id) runs[0].steps[0].reused = true;
    await route.fulfill({ status: 201, json: runs[0] });
  });
  await page.route('**/api/runs-s1/*/*', async route => {
    const action = route.request().url().split('/').at(-1)!; actions.push({ action, value: route.request().postDataJSON() });
    runs[0] = { ...runs[0], status: action === 'stop' ? 'stopped' : 'queued', updated_at: `2026-10-04T01:00:0${actions.length}+00:00` };
    await route.fulfill({ json: runs[0] });
  });
  await login(page, 'operator'); await openScoring(page, 's1airun');
  const panel = page.getByRole('region', { name: 'AI 실행', exact: true });
  const start = panel.getByRole('button', { name: '현재 입력으로 AI 실행 생성', exact: true });
  await expect(start).toBeDisabled(); expect(starts).toHaveLength(0);
  enabled = true; outdated = true; await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click(); await expect(start).toBeDisabled();
  outdated = false; await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click(); await expect(start).toBeEnabled();
  await start.click(); await expect(panel.getByText(/응답 확인이 필요한 요청/)).toBeVisible();
  await start.click(); await expect(panel.getByRole('heading', { name: '부분 완료', exact: true })).toBeVisible();
  expect(starts[0].request_id).toBe(starts[1].request_id); expect(starts[1]).toMatchObject({ expected_revision: item.input_revision, settings_version: 'synthetic-settings', reuse_run_id: null });
  await panel.getByText('기술 정보 · 단계별 시간·호출·부분 실패', { exact: true }).click();
  await expect(panel.getByText('공급자 임시 파일 정리 미완료', { exact: true })).toBeVisible();
  await expect(panel.getByText('입력 미확인 / 출력 미확인 / 합계 미확인 토큰', { exact: true })).toBeVisible();
  await expect(panel.getByText('추론: 2초', { exact: true })).toBeVisible();
  await panel.getByLabel('성공 항목군 재사용', { exact: true }).selectOption(runs[0].run_id);
  await start.click(); await expect(panel.getByRole('heading', { name: '대기', exact: true })).toBeVisible();
  expect(starts[2].reuse_run_id).toBe('synthetic-run-2'); expect(starts[2].request_id).not.toBe(starts[1].request_id);
  const stop = panel.getByRole('button', { name: '이 AI 실행 중지', exact: true }); await expect(stop).toBeDisabled();
  await panel.getByLabel('실행 제어 사유', { exact: true }).fill('합성 호출 없이 중지·재시도 상태 확인');
  await stop.click(); await expect(panel.getByRole('heading', { name: '중지', exact: true })).toBeVisible();
  expect(actions[0]).toEqual({ action: 'stop', value: { expected_updated_at: '2026-10-04T01:00:00+00:00', reason: '합성 호출 없이 중지·재시도 상태 확인' } });
  await panel.getByRole('button', { name: '고정 입력으로 AI 재시도', exact: true }).click();
  expect(actions[1].value.expected_updated_at).toBe('2026-10-04T01:00:01+00:00');
  await expect(panel.getByRole('heading', { name: '대기', exact: true })).toBeVisible();
  runs[0] = { ...runs[0], status: 'partial' }; await panel.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true }).click();
  await page.setViewportSize({ width: 360, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.screenshot({ path: testInfo.outputPath('ai-runs-s1-360.png'), animations: 'disabled' });
  await page.getByRole('button', { name: '로그아웃', exact: true }).click(); await login(page, 'reviewer'); await openScoring(page, 's1airun');
  const shared = page.getByRole('region', { name: 'AI 실행', exact: true });
  await expect(shared.getByRole('button', { name: '현재 입력으로 AI 실행 생성', exact: true })).toBeEnabled();
  await expect(shared.getByRole('button', { name: 'AI 실행 상태 새로고침', exact: true })).toBeVisible();
  await expect(shared.getByLabel('성공 항목군 재사용', { exact: true })).toBeVisible();
  await shared.getByRole('button', { name: '현재 입력으로 AI 실행 생성', exact: true }).click();
  expect(starts).toHaveLength(4);
  expect((await page.request.get('/api/scoring-ai-s1/readiness')).status()).toBe(200);
  expect((await page.request.get('/api/settings-s1')).status()).toBe(403);
  expect(errors).toEqual([]);
});

test('Shared submitted sheets allow another business actor to correct a new revision while preserving the original', async ({ page, request }, testInfo) => {
  test.setTimeout(120000);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await request.post('/api/auth/login', { headers, data: { username: 'operator', password } });
  let item = await (await request.post('/api/cases', { headers, data: { event_id: 'S1-SHARED-SHEET', participant_id: 's1aishow', dog_name: '공유 채점 합성견' } })).json();
  const path = `/api/cases/${item.case_id}/sessions/${item.selected_session_id}`;
  const bytes = execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=2:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov', 'pipe:1']);
  const receipt = await (await request.post('/api/uploads', { headers, data: { request_id: 's1-ai-reveal-media', filename: 'synthetic-ai-reveal.mp4', expected_size: bytes.length } })).json();
  expect((await request.put(`/api/uploads/${receipt.upload_id}/content`, { headers, params: { request_id: receipt.request_id }, data: bytes })).status()).toBe(200);
  expect((await request.post(`/api/uploads/${receipt.upload_id}/link`, { headers, data: { case_id: item.case_id, session_id: item.selected_session_id, camera_id: 'CAM1', expected_revision: item.input_revision } })).status()).toBe(200);
  item = await (await request.get(`/api/cases/${item.case_id}`)).json(); const video = item.manifest.sessions[0].videos[0];
  const recording = { video_id: video.video_id, confirmed: true, procedure_edition: 's1_confirmed', procedure_note: '공유 채점 합성 fixture', segments: ['entry', 'baseline', 'alone', 'reunion', 'ignore', 'walk', 'stranger', 'exit'].map(segment => ({ segment, video_id: video.video_id, state: segment === 'entry' ? 'performed' : 'not_performed', start_sec: segment === 'entry' ? 0 : null, end_sec: segment === 'entry' ? 2 : null, reason: segment === 'entry' ? null : '합성 미실시' })) };
  const capture = await request.put(path + '/recording-s1', { headers, data: { expected_revision: item.input_revision, recording } }); expect(capture.status(), await capture.text()).toBe(200); item = await capture.json();
  const assigned = await (await request.post(path + '/sheets-s1', { headers, data: { expected_revision: item.input_revision, assigned_username: 'reviewer', rater_id: 's1-ai-viewer', rater_name: '독립 평가자' } })).json();
  await login(page, 'reviewer');
  const sheetPath = `/api/score-sheets-s1/${assigned.sheet_id}`;
  const catalog = await (await request.get('/api/catalog/behavior-s1')).json();
  const observations = catalog.items.filter((value: { usage: string; optional: boolean }) => value.usage !== 'automatic' && !value.optional).map((value: { code: string }) => ({ code: value.code, value: null, status: 'unobserved', reason: '합성 공개 시험 관찰 미실시' }));
  const saved = await (await page.request.put(sheetPath, { headers, data: { expected_revision: assigned.revision, observations, reason: '합성 독립 원자료' } })).json();
  const submitted = await (await page.request.post(sheetPath + '/submit', { headers, data: { expected_revision: saved.revision, reason: '합성 독립 제출' } })).json();
  const calculated = await page.request.post(sheetPath + '/basic-results-s1', { headers, data: { input: { sheet_id: assigned.sheet_id, revision: submitted.revision, ref: submitted.manifest_ref, hash: submitted.manifest_hash } } });
  expect(calculated.status(), await calculated.text()).toBe(201);
  const resultId = (await calculated.json()).summary.result_id;
  const original = (await (await page.request.get(sheetPath)).json()).document;
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await login(page, 'operator');
  await openScoring(page, 's1aishow');
  await page.locator('.sheet-list').getByRole('button', { name: '시트 열기', exact: true }).click();
  const editor = page.getByRole('region', { name: '채점 시트', exact: true });
  await expect(editor.getByRole('heading', { name: /독립 평가자/ })).toBeVisible();
  await editor.getByRole('combobox', { name: '기본 결과 선택', exact: true }).selectOption(resultId);
  await expect(editor.getByText('계산과 기본 판정', { exact: true })).toBeVisible();
  expect((await (await page.request.get(sheetPath)).json()).document).toEqual(original);
  await editor.getByLabel('원코드/항목 검색', { exact: true }).fill('바14');
  const row = editor.getByLabel('바14 원관찰', { exact: true });
  await row.getByLabel('바14 빈값 사유', { exact: true }).fill('다른 업무 사용자의 합성 관찰 정정');
  await editor.getByLabel('저장·정정 사유', { exact: true }).fill('원평가자 보존과 실제 작업자 기록 검증');
  await editor.getByRole('button', { name: '제출본 수정 저장', exact: true }).click();
  await expect(editor.getByText(/초안 · 저장 후 제출합니다/)).toBeVisible();
  const corrected = (await (await page.request.get(sheetPath)).json()).document;
  expect(corrected.actor).toBe('operator');
  expect(corrected.assigned_username).toBe('reviewer');
  expect(corrected.sheet.rater_id).toBe('s1-ai-viewer');
  expect(corrected.revision).toBe(original.revision + 1);
  expect((await (await page.request.get(sheetPath + '/revisions/' + original.revision)).json())).toEqual(original);
  await editor.getByLabel('보존본 조회', { exact: true }).selectOption(String(original.revision));
  await expect(editor.getByText('보존본 읽기 전용', { exact: true })).toBeVisible();
  await expect(row.getByLabel('바14 빈값 사유', { exact: true })).toBeDisabled();
  await page.setViewportSize({ width: 360, height: 800 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await editor.screenshot({ path: testInfo.outputPath('shared-sheet-s1-360.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});
