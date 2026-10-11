// 일괄 등록 열 자동 연결 제안. 헤더 문자열만 보며 셀 값으로 열의 뜻을 추정하지 않는다.
// 서버에는 사용자가 확인한 columns만 보낸다 (서버 계약은 그대로).

export const profileFields: [string, string][] = [
  ['event_id', '행사 ID'], ['participant_id', '참가자 ID'], ['dog_name', '반려견 이름'], ['guardian_name', '보호자 이름'],
  ['reservation_at', '예약 시각'], ['sequence_no', '순번'], ['consent_confirmed', '기본 동의'],
  ['consent_analysis_feedback', '분석·피드백 동의'], ['consent_stranger_contact', '낯선 사람 접촉 동의'],
  ['dog_breed', '견종'], ['dog_sex', '성별'], ['dog_age_years', '나이'], ['dog_size', '크기'], ['years_together', '함께 산 기간'], ['adoption_route', '입양 경로'],
];
export const questionKeys = Array.from({ length: 28 }, (_, i) => `s${String(i + 1).padStart(2, '0')}`);
export const requiredKeys = ['dog_name'];

// 표준 이름과 알려진 별칭. 비교는 normalizeHeader 결과로 한다.
const aliases: Record<string, string[]> = {
  event_id: ['행사 ID', '행사', '행사 코드', 'event_id'],
  participant_id: ['참가자 ID', '참가번호', '접수번호', '참가자 번호', 'participant_id'],
  dog_name: ['반려견 이름', '강아지 이름', '강아지', '반려견', '반려견명', '견명', 'dog_name'],
  guardian_name: ['보호자 이름', '보호자명', '보호자', '성함', 'guardian_name'],
  reservation_at: ['예약 시각', '예약 일시', '예약 시간', 'reservation_at'],
  sequence_no: ['순번', '참가 순번', 'sequence_no'],
  consent_confirmed: ['기본 동의', '동의 확인', '동의', 'consent_confirmed'],
  consent_analysis_feedback: ['분석·피드백 동의', '분석 피드백 동의', 'consent_analysis_feedback'],
  consent_stranger_contact: ['낯선 사람 접촉 동의', '낯선 요원 접근·접촉 동의', 'consent_stranger_contact'],
  dog_breed: ['견종', '품종', 'dog_breed'],
  dog_sex: ['성별', '반려견 성별', 'dog_sex'],
  dog_age_years: ['나이', '연령', '반려견 나이', 'dog_age_years'],
  dog_size: ['크기', '체급', '견 크기', 'dog_size'],
  years_together: ['함께 산 기간', '함께한 기간', 'years_together'],
  adoption_route: ['입양 경로', '분양 경로', 'adoption_route'],
};

// 앞뒤 공백·전각/반각·대소문자·괄호 안 보조 설명을 걷어내고 구분 기호를 없앤 비교용 문자열.
export function normalizeHeader(header: string): string {
  return header.normalize('NFKC').toLowerCase()
    .replace(/\([^)]*\)|\[[^\]]*\]/g, '')
    .replace(/[\s_\-.:·*?]/g, '');
}

const aliasIndex = new Map<string, string[]>();
for (const [key, names] of Object.entries(aliases)) for (const name of names) {
  const normal = normalizeHeader(name);
  aliasIndex.set(normal, [...new Set([...(aliasIndex.get(normal) ?? []), key])]);
}

const questionPattern = /^(?:q|s|문항|질문)?0*(\d{1,2})(?:번)?(?:원응답)?(빈칸사유|빈칸이유|사유|reason)?$/;

// 헤더 하나가 맞는 표준 항목 후보들. 비어 있으면 연결 안 됨, 둘 이상이면 확인 필요다.
export function candidatesFor(header: string): string[] {
  const normal = normalizeHeader(header);
  const found = [...(aliasIndex.get(normal) ?? [])];
  const question = questionPattern.exec(normal);
  if (question) {
    const number = Number(question[1]);
    if (number >= 1 && number <= 28) {
      const key = `s${String(number).padStart(2, '0')}`;
      found.push(question[2] ? `${key}_reason` : key);
    }
  }
  return [...new Set(found)];
}

export type AutoMap = {
  mapping: Record<string, string>;               // 자동 연결된 표준 항목 → 원본 열
  review: { column: string; keys: string[] }[];  // 한 열이 여러 항목 후보
  conflicts: { key: string; columns: string[] }[]; // 한 항목에 여러 열이 맞음
  unmatched: string[];                           // 어느 항목과도 맞지 않는 열
};

export function autoMap(columns: string[]): AutoMap {
  const byKey = new Map<string, string[]>();
  const review: AutoMap['review'] = [], unmatched: string[] = [];
  for (const column of columns) {
    const keys = candidatesFor(column);
    if (!keys.length) unmatched.push(column);
    else if (keys.length > 1) review.push({ column, keys });
    else byKey.set(keys[0], [...(byKey.get(keys[0]) ?? []), column]);
  }
  const mapping: Record<string, string> = {}, conflicts: AutoMap['conflicts'] = [];
  for (const [key, found] of byKey) {
    if (found.length === 1) mapping[key] = found[0]; else conflicts.push({ key, columns: found });
  }
  return { mapping, review, conflicts, unmatched };
}

export const itemLabel = (key: string) => {
  const profile = profileFields.find(([name]) => name === key);
  if (profile) return profile[1];
  const number = Number(key.slice(1, 3));
  return key.endsWith('_reason') ? `${number}번 빈칸 사유` : `${number}번 응답`;
};

// 「1-9, 15, 20-28」 형식의 문항 번호 범위를 s01 키 목록으로 바꾼다. 잘못된 입력은 null이다.
export function parseQuestionRange(text: string): string[] | null {
  const keys = new Set<string>();
  for (const part of text.split(',').map(value => value.trim()).filter(Boolean)) {
    const match = /^(\d{1,2})(?:\s*-\s*(\d{1,2}))?$/.exec(part);
    if (!match) return null;
    const low = Number(match[1]), high = Number(match[2] ?? match[1]);
    if (low < 1 || high > 28 || low > high) return null;
    for (let n = low; n <= high; n++) keys.add(`s${String(n).padStart(2, '0')}`);
  }
  return keys.size ? [...keys] : null;
}

// 「매우 그렇다=5」처럼 줄마다 원라벨=숫자로 쓴 텍스트를 읽는다. 잘못되면 오류 문구를 돌려준다.
export function parseLabelLines(lines: string): { values: Record<string, number> } | { error: string } {
  const values: Record<string, number> = {};
  for (const line of lines.split('\n').filter(l => l.trim())) {
    const split = line.lastIndexOf('=');
    const label = line.slice(0, split).trim(), raw = line.slice(split + 1).trim();
    if (split < 1 || !/^[0-5]$/.test(raw) || label in values) return { error: '원라벨=숫자 형식과 중복을 확인하세요.' };
    values[label] = Number(raw);
  }
  return { values };
}
