import { test, expect } from '@playwright/test';
import { autoMap, candidatesFor, parseLabelLines, parseQuestionRange } from '../src/formsAutoMap';

// 표준 양식(backend/app/forms_v4.py TEMPLATE_PARTICIPANT)의 머리글. 양식과 별칭 표가 어긋나면 이 시험이 깨진다.
const templateHeaders: [string, string][] = [
  ['참가자 ID', 'participant_id'], ['반려견 이름', 'dog_name'], ['보호자 이름', 'guardian_name'], ['예약 시각', 'reservation_at'],
  ['순번', 'sequence_no'], ['기본 동의', 'consent_confirmed'], ['분석·피드백 동의', 'consent_analysis_feedback'],
  ['낯선 사람 접촉 동의', 'consent_stranger_contact'], ['견종', 'dog_breed'], ['반려견 성별', 'dog_sex'], ['반려견 나이', 'dog_age_years'],
  ['반려견 크기', 'dog_size'], ['함께 산 기간', 'years_together'], ['입양 경로', 'adoption_route'],
];

test('표준 양식 머리글은 모두 정확히 한 항목에 자동 연결된다', () => {
  for (const [header, key] of templateHeaders) expect(candidatesFor(header), header).toEqual([key]);
  for (let n = 1; n <= 28; n++) expect(candidatesFor(`Q${String(n).padStart(2, '0')}`)).toEqual([`s${String(n).padStart(2, '0')}`]);
  const all = [...templateHeaders.map(([header]) => header), ...Array.from({ length: 28 }, (_, i) => `Q${String(i + 1).padStart(2, '0')}`)];
  const proposal = autoMap(all);
  expect(Object.keys(proposal.mapping)).toHaveLength(42);
  expect(proposal.review).toEqual([]); expect(proposal.conflicts).toEqual([]); expect(proposal.unmatched).toEqual([]);
});

test('알려진 별칭과 문항 표기는 연결하고 빈칸 사유 열은 사유 항목으로 연결한다', () => {
  expect(candidatesFor('접수번호')).toEqual(['participant_id']);
  expect(candidatesFor(' 강아지  이름 ')).toEqual(['dog_name']);
  expect(candidatesFor('보호자 이름 (필수)')).toEqual(['guardian_name']);
  expect(candidatesFor('Ｑ１')).toEqual(['s01']);
  expect(candidatesFor('1번')).toEqual(['s01']);
  expect(candidatesFor('문항 28')).toEqual(['s28']);
  expect(candidatesFor('Q01 빈칸 사유')).toEqual(['s01_reason']);
  expect(candidatesFor('Q10_reason')).toEqual(['s10_reason']);
  expect(candidatesFor('s27')).toEqual(['s27']);
});

test('잘못 연결될 수 있는 헤더는 연결하지 않는다', () => {
  for (const header of ['Q1-2', 'Q1.2', '1_2', '1.5', '1-1', '1', '2', '28', 'Q001', 'Q29', 'Q0', '0번', '나이(개월)', '나이', '연령', '성별', '크기', '크기(kg)',
    '보호자 성별', '보호자 나이', '타임스탬프', 'Timestamp', '이메일 주소', '연락처', '우리 강아지는 낯선 사람을 좋아한다', 'Q01 (빈칸 사유)'])
    expect(candidatesFor(header), header).toEqual([]);
});

test('같은 항목에 맞는 열이 둘이면 연결하지 않고 충돌로 알린다', () => {
  const proposal = autoMap(['접수번호', 'Q1', '1번', '참가자 ID']);
  expect(proposal.mapping).toEqual({});
  expect(proposal.conflicts.map(item => item.key).sort()).toEqual(['participant_id', 's01']);
});

test('문항 범위와 라벨 입력을 엄격하게 읽는다', () => {
  expect(parseQuestionRange('1-3, 5')).toEqual(['s01', 's02', 's03', 's05']);
  for (const bad of ['', '0', '29', '3-1', '1-', 'a', '1;2']) expect(parseQuestionRange(bad), bad).toBeNull();
  expect(parseLabelLines('매우 그렇다=5\n그렇다=4')).toEqual({ values: { '매우 그렇다': 5, '그렇다': 4 } });
  for (const bad of ['라벨=6', '=3', '라벨', '가=1\n가=2']) expect(parseLabelLines(bad), bad).toHaveProperty('error');
});
