import { test, expect } from '@playwright/test';
import { csvCell, errorFileName, errorRowsCsv, hasErrorRows } from '../src/formsCsv';

test('오류 행 CSV는 BOM·따옴표·수식 방지를 지키고 원본 열 순서에 오류 사유를 붙인다', () => {
  const csv = errorRowsCsv(['참가자 ID', '+메모', 'Q1'], [
    { message: '허용 숫자가 아닙니다, 확인하세요', raw_values: { '참가자 ID': '0002', '+메모': '줄바꿈\n"인용"', Q1: 'maybe' } },
    { message: '수식 방지', raw_values: { '참가자 ID': '0003', '+메모': '=1+1', Q1: '-5' } },
    { message: '원행 없음', raw_values: null },
  ]);
  expect(csv.startsWith('﻿참가자 ID,+메모,Q1,오류 사유\r\n')).toBe(true);
  expect(csv).toContain('0002,"줄바꿈\n""인용""",maybe,"허용 숫자가 아닙니다, 확인하세요"\r\n');
  expect(csv).toContain("0003,'=1+1,-5,수식 방지\r\n");
  expect(csv).not.toContain('원행 없음');
  expect(csvCell(null)).toBe('');
  expect(csvCell('@SUM(1)')).toBe("'@SUM(1)");
  expect(csvCell('+82-10')).toBe("'+82-10");
  expect(csvCell(-3)).toBe('-3');
  expect(hasErrorRows([{ message: 'x', raw_values: null }])).toBe(false);
});

test('내려받는 파일 이름에는 행사 ID와 시각만 쓴다', () => {
  expect(errorFileName(' U03-FIELD ', new Date('2026-10-11T09:05:03Z'))).toBe('kdog-forms-errors-U03-FIELD-20261011-090503.csv');
  expect(errorFileName('')).toMatch(/^kdog-forms-errors-event-\d{8}-\d{6}\.csv$/);
});
