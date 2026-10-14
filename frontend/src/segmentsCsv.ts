import { SEGMENTS_V3, type SegmentId } from './types';

export type SegmentsCsvResult = {
  segments: { segment: SegmentId; start_sec: number; end_sec: number | null }[];
  offsets: { camera_id: string; offset_seconds: number; spread: number }[];
  warnings: string[];
};

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
  const selected = new Map<number, { row: string[]; start: number }>();
  function seconds(row: string[], name: string) {
    const raw = row[column(name)], value = Number(raw);
    if (!raw || !Number.isFinite(value) || value < 0) throw new Error(`${name} 값은 0 이상의 영상 초여야 합니다.`);
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
    selected.set(number, { row, start: seconds(row, reference) });
  }
  if (!selected.size) throw new Error('CSV에 가져올 구간번호 1~8 행이 없습니다.');
  if (ignored.size) warnings.push(`가져오지 않은 종류: ${[...ignored].join(', ')}`);
  const ordered = [...selected.entries()].sort(([a], [b]) => a - b);
  if (ordered.some(([, value], index) => index > 0 && value.start <= ordered[index - 1][1].start)) throw new Error('구간 시작 시각은 구간번호 순서대로 증가해야 합니다.');
  for (const [index, [, label]] of SEGMENTS_V3.entries()) if (!selected.has(index + 1)) warnings.push(`${label} 구간 누락: 기존 입력을 유지합니다.`);
  const offsets: SegmentsCsvResult['offsets'] = [];
  for (const camera of new Set(linkedCameras)) {
    if (camera === referenceCamera) continue;
    const name = `${camera}_영상초`;
    if (column(name) < 0) { warnings.push(`${name} 열이 없어 오프셋을 채우지 못했습니다.`); continue; }
    const values = ordered.map(([, value]) => seconds(value.row, name) - value.start);
    const spread = Math.max(...values) - Math.min(...values);
    offsets.push({ camera_id: camera, offset_seconds: Number(values.reduce((sum, value) => sum + value / values.length, 0).toFixed(3)), spread });
    if (spread > 0.5) warnings.push(`${camera} 오프셋 편차 ${spread.toFixed(3)}초: 동기화 근거를 확인하세요.`);
  }
  return { segments: ordered.map(([number, value]) => ({ segment: SEGMENTS_V3[number - 1][0], start_sec: value.start, end_sec: selected.get(number + 1)?.start ?? null })), offsets, warnings };
}
