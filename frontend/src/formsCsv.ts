// 일괄 등록의 오류 행 CSV: 원본 값 + 오류 사유. 서버에는 저장하지 않고 화면에서 만든다.
export type CsvIssue = { message: string; raw_values: Record<string, string | number | boolean | null> | null };

// 엑셀에서 열었을 때 수식으로 읽히는 셀은 작은따옴표를 붙인다(숫자는 그대로).
export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(text) && !/^[+-]?\d+(\.\d+)?$/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function errorRowsCsv(headers: string[], errors: CsvIssue[]): string {
  const lines = [[...headers, '오류 사유'].map(csvCell).join(',')];
  for (const error of errors) if (error.raw_values) lines.push([...headers.map(header => error.raw_values?.[header]), error.message].map(csvCell).join(','));
  return `﻿${lines.join('\r\n')}\r\n`;
}

export const hasErrorRows = (errors: CsvIssue[]) => errors.some(error => error.raw_values);

// 파일명에는 행사 ID와 시각만 쓴다(참가자 정보를 넣지 않는다).
export function errorFileName(eventId: string, at = new Date()): string {
  const time = at.toISOString().replace(/[-:]/g, '').replace(/\..*/, '').replace('T', '-');
  return `kdog-forms-errors-${eventId.trim() || 'event'}-${time}.csv`;
}
