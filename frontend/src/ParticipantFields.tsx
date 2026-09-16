import { adoptionOptions, sexOptions, sizeOptions } from './types';
import type { Case } from './types';

// 04 설문지 머리 칸을 그대로 받는다. 연락처는 받지 않는다(01 §7).
export function ParticipantFields({ value }: { value?: Case }) {
  const dog = value?.dog;
  return <>
    <label>참가자 ID<input name="participant_id" placeholder="0001" pattern="[A-Za-z0-9_\-]+" required defaultValue={value?.participant_id} /></label>
    <label>순번<input name="sequence_no" type="number" min={1} max={9999} defaultValue={value?.sequence_no ?? ''} /></label>
    <label>반려견 이름<input name="dog_name" required maxLength={200} defaultValue={value?.dog_name} /></label>
    <label>보호자명<input name="guardian_name" maxLength={100} defaultValue={value?.guardian_name} /></label>
    <label>견종<input name="breed" maxLength={100} defaultValue={dog?.breed} /></label>
    <label>성별<select name="sex" defaultValue={dog?.sex ?? '미기재'}>{sexOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>나이(세)<input name="age_years" type="number" min={0} max={30} defaultValue={dog?.age_years ?? ''} /></label>
    <label>크기<select name="size" defaultValue={dog?.size ?? '미기재'}>{sizeOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>함께 산 기간<input name="years_together" maxLength={50} placeholder="예: 3년" defaultValue={dog?.years_together} /></label>
    <label>입양 경로<select name="adoption_route" defaultValue={dog?.adoption_route ?? '미기재'}>{adoptionOptions.map(o => <option key={o}>{o}</option>)}</select></label>
    <label>예약 시각<input name="reservation_at" type="datetime-local" defaultValue={value?.reservation_at} /></label>
    <label className="check"><input name="consent_confirmed" type="checkbox" defaultChecked={value?.consent_confirmed} />촬영 영상·설문 사용 동의 확인</label>
  </>;
}

const optional = (form: FormData, name: string) => { const raw = String(form.get(name) ?? '').trim(); return raw === '' ? null : Number(raw); };

export function participantValue(form: FormData) {
  return {
    participant_id: form.get('participant_id'), dog_name: form.get('dog_name'), reservation_at: form.get('reservation_at') ?? '',
    sequence_no: optional(form, 'sequence_no'), consent_confirmed: form.get('consent_confirmed') === 'on', guardian_name: form.get('guardian_name') ?? '',
    dog: { breed: form.get('breed') ?? '', sex: form.get('sex'), age_years: optional(form, 'age_years'), size: form.get('size'),
      years_together: form.get('years_together') ?? '', adoption_route: form.get('adoption_route') },
  };
}
