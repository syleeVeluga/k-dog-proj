import { useEffect, useId, useRef, useState } from 'react';

const edits = new Set<string>();

export function mayLeave() {
  return !edits.size || window.confirm('저장하지 않은 입력이 있습니다. 입력을 버리고 이동하시겠습니까?');
}

export function useUnsaved(dirty: boolean) {
  const id = useId();
  useEffect(() => {
    if (dirty) edits.add(id); else edits.delete(id);
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { edits.delete(id); window.removeEventListener('beforeunload', warn); };
  }, [dirty, id]);
}

// Each editor keeps its own base version. Background results never replace typed input.
export function useEditBase<T>(latest: T) {
  const [base, setBase] = useState<T | null>(null);
  const [dirty, setDirty] = useState(false);
  const [key, setKey] = useState(0);
  const frozen = useRef<T | null>(null);
  useUnsaved(dirty);
  function capture() { if (!frozen.current) { frozen.current = latest; setBase(latest); } }
  function reset() { frozen.current = null; setBase(null); setDirty(false); setKey(k => k + 1); }
  return { view: base ?? latest, key, dirty, capture, change: () => { capture(); setDirty(true); }, reset,
    discard: () => { if (!dirty || window.confirm('이 편집기의 미저장 입력을 버리고 최신 결과를 불러오시겠습니까?')) { reset(); return true; } return false; } };
}
