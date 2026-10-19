import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { applySegmentsCsvDraft, parseSegmentsCsv } from '../src/segmentsCsv';
import { SEGMENTS_V3 } from '../src/types';
import type { RecordingV4 } from '../src/recordingTypesV4';

const sample = readFileSync(new URL('./fixtures/segments-sample.csv', import.meta.url), 'utf-8');
const cameras = ['CAM1', 'CAM2', 'CAM3', 'CAM4'];
const lines = sample.replace(/^\uFEFF/, '').trim().split(/\r?\n/);

test('샘플 CSV에서 8구간과 7개 끝, 평균 오프셋을 읽는다', () => {
  const result = parseSegmentsCsv(sample, 'CAM1', cameras);
  expect(result.segments).toHaveLength(8);
  expect(result.segments[0]).toEqual({ segment: 'entry', start_sec: 10.356, end_sec: 51.146 });
  expect(result.segments[6]).toEqual({ segment: 'stranger', start_sec: 250.732, end_sec: 299.898 });
  expect(result.segments[7]).toEqual({ segment: 'exit', start_sec: 299.898, end_sec: null });
  expect(result.offsets.map(value => [value.camera_id, value.offset_seconds])).toEqual([['CAM2', 0.069], ['CAM3', -0.118], ['CAM4', -0.016]]);
  expect(result.offsets.every(value => value.spread <= 0.01)).toBe(true);
  expect(result.warnings).toEqual([]);
  expect(parseSegmentsCsv(sample.replace(/^\uFEFF/, ''), 'CAM1', cameras)).toEqual(result);
});

test('기준 CAM3와 뒤집힌 열 순서·추가 열에도 카메라 열 이름으로 읽는다', () => {
  const reordered = lines.map(line => [...line.split(',').reverse(), '추가'].join(',')).join('\n');
  const result = parseSegmentsCsv(reordered, 'CAM3', cameras);
  expect(result.segments[0].start_sec).toBe(10.238);
  expect(result.offsets.find(value => value.camera_id === 'CAM1')?.offset_seconds).toBe(0.118);
});

test('누락 구간은 경고하고 다음 번호가 없으면 끝을 추정하지 않는다', () => {
  const result = parseSegmentsCsv(lines.filter((_, index) => index !== 3).join('\n'), 'CAM1', cameras);
  expect(result.segments).toHaveLength(7);
  expect(result.segments[1].end_sec).toBeNull();
  expect(result.warnings.join(' ')).toContain('혼자 구간 누락');
});

test('중단 행은 무시하고 이름·카메라 열 없음·편차는 경고한다', () => {
  const changed = [...lines, lines[1].replace('구간,1,입장', '중단,1,입장')].join('\n').replace(',기준,', ',다른 이름,').replace('CAM4_영상초', '별도열');
  const result = parseSegmentsCsv(changed, 'CAM1', cameras);
  expect(result.segments).toHaveLength(8);
  expect(result.warnings.join(' ')).toContain('중단');
  expect(result.warnings.join(' ')).toContain('구간 이름');
  expect(result.warnings.join(' ')).toContain('CAM4_영상초 열이 없어');
  const spread = parseSegmentsCsv(sample.replace('10.425', '11.425'), 'CAM1', cameras);
  expect(spread.offsets[0].offset_seconds).toBe(0.194);
  expect(spread.warnings.join(' ')).toContain('오프셋 편차');
});

test('따옴표·쉼표·개행·escaped quote가 든 셀을 처리한다', () => {
  const quoted = sample.replace('1,구간,1,입장,,,,', '1,구간,1,"입장","","메모, 줄\n두 번째 ""인용""",,');
  expect(parseSegmentsCsv(quoted, 'CAM1', cameras).segments).toEqual(parseSegmentsCsv(sample, 'CAM1', cameras).segments);
});

test('중복 번호·기준 열 없음·숫자 오류·역순·잘못된 CSV는 거절한다', () => {
  for (const [input, message] of [
    [[...lines, lines[1]].join('\n'), '중복'], [sample.replace('CAM1_영상초', '없는열'), '기준 영상 카메라'],
    [sample.replace('10.356', ''), '영상 초'], [sample.replace('10.356', 'NaN'), '영상 초'],
    [sample.replace('51.146', '9.146'), '증가'], [sample + '\n1,구간', '열 개수'],
    [sample.replace('입장', '"입장'), '따옴표'], ['종류,종류\n구간,구간', '머리글'], ['', '머리글'],
  ]) expect(() => parseSegmentsCsv(input, 'CAM1', cameras)).toThrow(message);
});

function recording(): RecordingV4 {
  return { procedure_edition: 's1_confirmed', procedure_note: '수동 절차 근거', video_id: 'reference', confirmed: true,
    segments: SEGMENTS_V3.map(([segment]) => ({ segment, video_id: 'reference', state: segment === 'reunion' ? 'not_performed' : 'performed', start_sec: 90, end_sec: 99, reason: '수동 근거' })),
    walk_phases: [{ phase: 'move_1', video_id: 'reference', state: 'performed', start_sec: 12, end_sec: 13, reason: null, proximity_exception: 'none', proximity_note: '수동 걷기' }],
    events: [], coverage: [], tail_selections: [], linked_memos: [{ code: '개59', memo_id: 'manual', text: '수동 메모', item_codes: ['개12'], event_ids: [] }], safe_base_sequence: null,
    video_offsets: ['cam2', 'unlinked', 'reference'].map(video_id => ({ video_id, offset_seconds: 9, confirmed: false, note: '수동 offset' })) };
}

const videos = [{ video_id: 'reference', camera_id: 'CAM1' }, { video_id: 'cam2', camera_id: 'CAM2' }, { video_id: 'cam2-copy', camera_id: 'CAM2' }, { video_id: 'same-camera', camera_id: 'CAM1' }];

test('초안은 미실시·누락·수동 사실과 기존 offset 순서를 보존하고 입력을 변경하지 않는다', () => {
  const input = recording(), before = structuredClone(input);
  const csv = lines.filter((_, index) => index !== 3).join('\n');
  const result = applySegmentsCsvDraft(input, videos, csv, 'sample.csv', 'hash-1')!;
  expect(input).toEqual(before);
  expect(result.record).toEqual({ ...before, confirmed: false,
    segments: before.segments.map(segment => {
      const parsed = parseSegmentsCsv(csv, 'CAM1', ['CAM2']).segments.find(value => value.segment === segment.segment);
      return !parsed || segment.state === 'not_performed' ? segment : { ...segment, start_sec: parsed.start_sec, end_sec: parsed.end_sec };
    }),
    video_offsets: [before.video_offsets[1], before.video_offsets[2], ...['cam2', 'cam2-copy'].map(video_id => ({ video_id, offset_seconds: 0.069, confirmed: true,
      note: 'segments.csv sample.csv SHA-256 hash-1 · CAM2_영상초−CAM1_영상초 평균, 편차 0.001초' }))],
    procedure_note: '수동 절차 근거\nsegments.csv sample.csv SHA-256 hash-1' });
  expect(result.summary.ends).toBe(4);
  expect(result.summary.offsets).toEqual(['CAM2']);
  expect(result.summary.warnings).toEqual(['혼자 구간 누락: 기존 입력을 유지합니다.', '재회 구간은 미실시로 기록되어 기존 입력을 유지합니다.']);
});

test('초안 출처는 hash로 중복을 막고 기준 영상·카메라 없는 연결을 임의로 채우지 않는다', () => {
  const first = applySegmentsCsvDraft(recording(), videos, sample, 'first.csv', 'same-hash')!;
  const repeated = applySegmentsCsvDraft(first.record, videos, sample, 'renamed.csv', 'same-hash')!;
  expect(repeated.record.procedure_note).toBe(first.record.procedure_note);
  expect(repeated.record.video_offsets.find(value => value.video_id === 'reference')).toEqual(recording().video_offsets[2]);
  expect(repeated.record.video_offsets.some(value => value.video_id === 'same-camera')).toBe(false);
  const changed = applySegmentsCsvDraft(repeated.record, videos, sample, 'changed.csv', 'new-hash')!;
  expect(changed.record.procedure_note).toBe(first.record.procedure_note + '\nsegments.csv changed.csv SHA-256 new-hash');
  expect(applySegmentsCsvDraft(recording(), [{ video_id: 'reference' }], sample, 'sample.csv', 'hash')).toBeNull();
  expect(applySegmentsCsvDraft({ ...recording(), video_id: 'absent' }, videos, sample, 'sample.csv', 'hash')).toBeNull();
  const before = recording();
  expect(() => applySegmentsCsvDraft(before, videos, 'invalid', 'bad.csv', 'hash')).toThrow();
  expect(before).toEqual(recording());
});
