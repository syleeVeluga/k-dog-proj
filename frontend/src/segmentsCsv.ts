import { SEGMENTS_V3, type SegmentId, type Video } from './types';
import type { RecordingV4 } from './recordingTypesV4';

export type SegmentsCsvResult = {
  segments: { segment: SegmentId; start_sec: number; end_sec: number | null }[];
  offsets: { camera_id: string; offset_seconds: number; spread: number }[];
  warnings: string[];
};

export type SegmentsCsvSummary = { ends: number; offsets: string[]; warnings: string[] };

export function inspectSegmentsCsv(text: string): string[] {
  const [headers] = csvRows(text.replace(/^\uFEFF/, ''));
  const cameras = (headers ?? []).filter(name => /^[A-Za-z0-9_-]+_영상초$/.test(name)).map(name => name.slice(0, -4));
  if (!cameras.length) throw new Error('CSV에 CAM1_영상초와 같은 카메라 영상초 열이 필요합니다.');
  for (const camera of cameras) parseSegmentsCsv(text, camera, []);
  return cameras;
}

export function applySegmentsCsvDraft(record: RecordingV4, videos: Pick<Video, 'video_id' | 'camera_id'>[], text: string, filename: string, hash: string): { record: RecordingV4; summary: SegmentsCsvSummary } | null {
  const reference = videos.find(video => video.video_id === record.video_id);
  if (!reference?.camera_id) return null;
  const result = parseSegmentsCsv(text, reference.camera_id, videos.flatMap(video => video.camera_id ? [video.camera_id] : []));
  const source = `segments.csv ${filename} SHA-256 ${hash}`, warnings = [...result.warnings];
  const filled = result.segments.filter(value => {
    const segment = record.segments.find(segment => segment.segment === value.segment)!;
    if (segment.state !== 'not_performed') return true;
    warnings.push(`${SEGMENTS_V3.find(([id]) => id === value.segment)![1]} 구간은 미실시로 기록되어 기존 입력을 유지합니다.`); return false;
  });
  const offsets = videos.flatMap(video => {
    const value = result.offsets.find(value => value.camera_id === video.camera_id);
    return video.video_id === reference.video_id || !value ? [] : [{ video_id: video.video_id, offset_seconds: value.offset_seconds, confirmed: true,
      note: `${source} · ${video.camera_id}_영상초−${reference.camera_id}_영상초 평균, 편차 ${value.spread.toFixed(3)}초` }];
  });
  return { record: { ...record, confirmed: false, segments: record.segments.map(segment => {
    const value = filled.find(value => value.segment === segment.segment); return value ? { ...segment, start_sec: value.start_sec, end_sec: value.end_sec } : segment;
  }), video_offsets: [...record.video_offsets.filter(value => !offsets.some(offset => offset.video_id === value.video_id)), ...offsets],
    procedure_note: record.procedure_note.split('\n').some(line => line.includes(`SHA-256 ${hash}`)) ? record.procedure_note : [record.procedure_note, source].filter(Boolean).join('\n') },
    summary: { ends: filled.filter(value => value.end_sec !== null).length, offsets: result.offsets.map(value => value.camera_id), warnings } };
}

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = '', quoted = false, closed = false;
  function field() { row.push(cell.trim()); cell = ''; closed = false; }
  function line() { field(); if (row.some(Boolean)) rows.push(row); row = []; }
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { cell += '"'; index++; }
      else if (quoted) { quoted = false; closed = true; }
      else if (cell.trim() || closed) throw new Error('CSV 따옴표 형식을 확인하세요.');
      else quoted = true;
    } else if (quoted) cell += char;
    else if (char === ',') field();
    else if (char === '\n' || char === '\r') { line(); if (char === '\r' && text[index + 1] === '\n') index++; }
    else if (closed && char.trim()) throw new Error('CSV 따옴표 뒤의 형식을 확인하세요.');
    else cell += char;
  }
  if (quoted) throw new Error('CSV 따옴표가 닫히지 않았습니다.');
  if (cell || row.length) line();
  return rows;
}

export function parseSegmentsCsv(text: string, referenceCamera: string, linkedCameras: string[]): SegmentsCsvResult {
  const [headers, ...rows] = csvRows(text.replace(/^\uFEFF/, ''));
  if (!headers || new Set(headers).size !== headers.length) throw new Error('CSV 머리글이 없거나 중복됩니다.');
  const column = (name: string) => headers.indexOf(name);
  for (const name of ['종류', '구간번호']) if (column(name) < 0) throw new Error(`CSV에 ${name} 열이 없습니다.`);
  const reference = `${referenceCamera}_영상초`;
  if (column(reference) < 0) throw new Error(`기준 영상 카메라 ${referenceCamera} 열이 CSV에 없습니다.`);
  const warnings: string[] = [], ignored = new Set<string>();
  if (column('구간이름') < 0) warnings.push('구간이름 열이 없어 이름을 교차 확인하지 못했습니다.');
  const selected = new Map<number, { row: string[]; start: number | null }>();
  function seconds(row: string[], name: string) {
    const raw = row[column(name)];
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) throw new Error(`${name} 값은 0 이상의 영상 초여야 합니다.`);
    return value;
  }
  for (const row of rows) {
    if (row.length !== headers.length) throw new Error('CSV 행의 열 개수가 머리글과 다릅니다.');
    if (row[column('종류')] !== '구간') { ignored.add(row[column('종류')] || '(빈 종류)'); continue; }
    const number = Number(row[column('구간번호')]);
    if (!Number.isInteger(number) || number < 1 || number > 8) continue;
    if (selected.has(number)) throw new Error(`구간번호 ${number}이 중복됩니다.`);
    const label = SEGMENTS_V3[number - 1][1];
    if (column('구간이름') >= 0 && !row[column('구간이름')].startsWith(label.slice(0, 2))) warnings.push(`${number}번 구간 이름을 확인하세요: ${row[column('구간이름')]} (예상 ${label})`);
    const start = seconds(row, reference);
    if (start === null) warnings.push(`${label} 구간의 ${reference}가 비어 있어 기존 입력을 유지합니다. 미입력 시각은 확정 전에 영상에서 확인하세요.`);
    selected.set(number, { row, start });
  }
  if (!selected.size) throw new Error('CSV에 가져올 구간번호 1~8 행이 없습니다.');
  if (ignored.size) warnings.push(`가져오지 않은 종류: ${[...ignored].join(', ')}`);
  const ordered = [...selected.entries()].filter((entry): entry is [number, { row: string[]; start: number }] => entry[1].start !== null).sort(([a], [b]) => a - b);
  if (ordered.some(([, value], index) => index > 0 && value.start <= ordered[index - 1][1].start)) throw new Error('구간 시작 시각은 구간번호 순서대로 증가해야 합니다.');
  for (const [index, [, label]] of SEGMENTS_V3.entries()) if (!selected.has(index + 1)) warnings.push(`${label} 구간 누락: 기존 입력을 유지합니다.`);
  const offsets: SegmentsCsvResult['offsets'] = [];
  for (const camera of new Set(linkedCameras)) {
    if (camera === referenceCamera) continue;
    const name = `${camera}_영상초`;
    if (column(name) < 0) { warnings.push(`${name} 열이 없어 오프셋을 채우지 못했습니다.`); continue; }
    const values = ordered.flatMap(([, value]) => {
      const time = seconds(value.row, name);
      return time === null ? [] : [time - value.start];
    });
    if (!values.length) { warnings.push(`${camera} 공통 영상 시각이 없어 기존 오프셋을 유지합니다.`); continue; }
    if (values.length < selected.size) warnings.push(`${camera} 오프셋은 시각이 있는 공통 ${values.length}개 행으로 계산했습니다. 빈 시각은 제외했습니다.`);
    const spread = Math.max(...values) - Math.min(...values);
    offsets.push({ camera_id: camera, offset_seconds: Number(values.reduce((sum, value) => sum + value / values.length, 0).toFixed(3)), spread });
    if (spread > 0.5) warnings.push(`${camera} 오프셋 편차 ${spread.toFixed(3)}초: 동기화 근거를 확인하세요.`);
  }
  return { segments: ordered.map(([number, value]) => ({ segment: SEGMENTS_V3[number - 1][0], start_sec: value.start, end_sec: selected.get(number + 1)?.start ?? null })), offsets, warnings };
}
