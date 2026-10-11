import { useRef, useState } from 'react';
import type { FocusEvent, FormEvent } from 'react';

// 입력 칸 단위 오류. 전역 알림은 요약만 두고, 무엇이 왜 틀렸는지는 해당 칸 아래에 쓴다.
export type FieldName = 'event_id' | 'participant_id' | 'sequence_no' | 'dog_name' | 'age_years';
export type FieldErrors = Partial<Record<FieldName, string>>;

const ORDER: FieldName[] = ['event_id', 'participant_id', 'sequence_no', 'dog_name', 'age_years'];
const KEY = /^[A-Za-z0-9_-]+$/;
const KEY_MAX = 100;
const integerIn = (text: string, low: number, high: number) => /^\d+$/.test(text) && Number(text) >= low && Number(text) <= high;

export function validateField(name: string, raw: string): string {
  const text = raw.trim();
  switch (name) {
    case 'event_id':
      return !text ? '행사 ID를 입력하세요.' : text.length > KEY_MAX ? '행사 ID는 100자 이하로 입력하세요.' : KEY.test(text) ? '' : '행사 ID는 영문·숫자·밑줄·하이픈만 쓸 수 있습니다. 예: KDOG-2026';
    case 'participant_id':
      return !text ? '참가자 ID를 입력하세요.' : text.length > KEY_MAX ? '참가자 ID는 100자 이하로 입력하세요.' : KEY.test(text) ? '' : '참가자 ID는 영문·숫자·밑줄·하이픈만 쓸 수 있습니다(공백·한글 불가). 예: 0001';
    case 'dog_name':
      return text ? '' : '반려견 이름을 입력하세요.';
    case 'sequence_no':
      return !text || integerIn(text, 1, 9999) ? '' : '순번은 1~9999 사이의 정수로 입력하세요. 비워 두면 미지정입니다.';
    case 'age_years':
      return !text || integerIn(text, 0, 30) ? '' : '나이는 0~30 사이의 정수(세)로 입력하세요. 모르면 비우세요. 개월은 자동 변환하지 않습니다.';
    default:
      return '';
  }
}

export function validateForm(form: HTMLFormElement, names: FieldName[] = ORDER): FieldErrors {
  const data = new FormData(form), errors: FieldErrors = {};
  for (const name of names) if (data.has(name)) { const message = validateField(name, String(data.get(name) ?? '')); if (message) errors[name] = message; }
  return errors;
}

export function focusFirstError(form: HTMLFormElement, errors: FieldErrors) {
  const first = ORDER.find(name => errors[name]);
  if (first) form.querySelector<HTMLElement>(`[name="${first}"]`)?.focus();
}

// 저장 요청 중에는 작업 영역이 잠겨 있어 포커스를 옮길 수 없다. 잠금이 풀린 뒤에 옮긴다.
export function focusSoon(form: HTMLFormElement | null, errors: FieldErrors, attempt = 0) {
  window.setTimeout(() => {
    if (!form?.isConnected) return;
    focusFirstError(form, errors);
    const first = ORDER.find(name => errors[name]);
    if (first && attempt < 8 && form.querySelector(`[name="${first}"]`) !== document.activeElement) focusSoon(form, errors, attempt + 1);
  }, 60);
}

export function useFieldErrors() {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [summary, setSummary] = useState('');
  const server = useRef(new Set<string>());
  return {
    errors, summary,
    set(next: FieldErrors, message = '저장하지 못했습니다. 표시된 칸을 고쳐 다시 저장하세요.') { setErrors(next); setSummary(Object.keys(next).length ? message : ''); },
    // 서버가 알려 준 칸 오류(중복 ID·순번)는 값을 고치기 전에는 칸을 벗어나도 남긴다.
    setServer(next: FieldErrors) { server.current = new Set(Object.keys(next)); setErrors(next); setSummary('저장하지 못했습니다. 표시된 칸을 고쳐 다시 저장하세요.'); },
    clear() { server.current.clear(); setErrors({}); setSummary(''); },
    // 칸을 벗어날 때 그 칸만 검사하고, 고치는 중에는 그 칸의 이전 오류를 지운다.
    bind: {
      onBlurCapture(event: FocusEvent<HTMLFormElement>) {
        const target = event.target as unknown as HTMLInputElement;
        if (!ORDER.includes(target.name as FieldName) || server.current.has(target.name)) return;
        const message = validateField(target.name, target.value);
        setErrors(current => { const next = { ...current }; if (message) next[target.name as FieldName] = message; else delete next[target.name as FieldName]; return next; });
      },
      onInputCapture(event: FormEvent<HTMLFormElement>) {
        const name = (event.target as unknown as HTMLInputElement).name as FieldName;
        server.current.delete(name);
        setErrors(current => { if (!current[name]) return current; const next = { ...current }; delete next[name]; return next; });
      },
    },
  };
}
