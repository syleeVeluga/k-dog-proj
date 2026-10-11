import { adoptionOptions, sexOptions, sizeOptions } from './types';
import type { Case } from './types';
import type { FieldErrors, FieldName } from './FieldErrors';

// 04 설문지 머리 칸을 그대로 받는다. 연락처는 받지 않는다(01 §7).
// errors는 칸 아래에 표시하고, defaultSequence는 연속 등록에서 다음 순번을 제안할 때 쓴다.
export function ParticipantFields({ value, errors = {}, sequence, onSequence, prefix = 'participant' }: { value?: Case; errors?: FieldErrors; sequence?: string; onSequence?: (value: string) => void; prefix?: string }) {
  const dog = value?.dog;
  const invalid = (name: FieldName) => ({ 'aria-invalid': errors[name] ? true : undefined, 'aria-describedby': errors[name] ? `${prefix}-${name}-error` : undefined });
  const error = (name: FieldName) => errors[name] ? <small className="field-error" id={`${prefix}-${name}-error`}>{errors[name]}</small> : null;
  return <>
    <label>참가자 ID<input aria-label="참가자 ID" name="participant_id" placeholder="0001" required defaultValue={value?.participant_id} {...invalid('participant_id')} /><small>필수 · 설문 연결 번호. 예: 0001. Excel에서는 텍스트로 입력해 앞자리 0을 보존하세요.</small>{error('participant_id')}</label>
    <label>순번<input aria-label="순번" name="sequence_no" type="number" min={1} max={9999} {...(sequence === undefined ? { defaultValue: value?.sequence_no ?? '' } : { value: sequence, onChange: (event: { target: { value: string } }) => onSequence?.(event.target.value) })} {...invalid('sequence_no')} /><small>선택 · 행사 안에서 중복 없는 진행 순서(1~9999). 비우면 미지정, ID와 다릅니다.</small>{error('sequence_no')}</label>
    <label>반려견 이름<input aria-label="반려견 이름" name="dog_name" required maxLength={200} defaultValue={value?.dog_name} {...invalid('dog_name')} />{error('dog_name')}</label>
    <label>보호자명<input name="guardian_name" maxLength={100} defaultValue={value?.guardian_name} /></label>
    <label>견종<input name="breed" maxLength={100} defaultValue={dog?.breed} /></label>
    <label>성별<select name="sex" defaultValue={dog?.sex ?? '미기재'}>{sexOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>나이(세)<input aria-label="나이(세)" name="age_years" type="number" min={0} max={30} defaultValue={dog?.age_years ?? ''} {...invalid('age_years')} /><small>선택 · 정수 세 단위, 0~30. 모르면 빈칸. 개월을 자동 변환하지 않습니다.</small>{error('age_years')}</label>
    <label>크기<select name="size" defaultValue={dog?.size ?? '미기재'}>{sizeOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>함께 산 기간<input name="years_together" maxLength={50} placeholder="예: 3년, 8개월" defaultValue={dog?.years_together} /></label>
    <label>입양 경로<select name="adoption_route" defaultValue={dog?.adoption_route ?? '미기재'}>{adoptionOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>예약 시각<input aria-label="예약 시각" name="reservation_at" type="datetime-local" defaultValue={value?.reservation_at} /><small>선택 · 행사 현지 시각. 예: 2026-10-31 09:30. 비우면 미예약.</small></label>
    <p className="fine" style={{ gridColumn: '1 / -1' }}>선택 정보는 모르면 비워 두거나 미기재를 선택하세요.</p>
  </>;
}

const optional = (form: FormData, name: string) => { const raw = String(form.get(name) ?? '').trim(); return raw === '' ? null : Number(raw); };

export function participantValue(form: FormData) {
  return {
    participant_id: String(form.get('participant_id') ?? '').trim(), dog_name: form.get('dog_name'), reservation_at: form.get('reservation_at') ?? '',
    sequence_no: optional(form, 'sequence_no'), guardian_name: form.get('guardian_name') ?? '',
    dog: { breed: form.get('breed') ?? '', sex: form.get('sex'), age_years: optional(form, 'age_years'), size: form.get('size'),
      years_together: form.get('years_together') ?? '', adoption_route: form.get('adoption_route') },
  };
}
