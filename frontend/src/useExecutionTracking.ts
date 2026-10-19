import { useEffect, useRef, useState } from 'react';

export type ExecutionSnapshot<P, D> = { pending: P | null; selectedId: string; data: D; busy: boolean };
export type ExecutionUpdate<D> = {
  data: D; poll: boolean; selectedId?: string; clearPending?: boolean; forget?: boolean;
  verified?: boolean; checked?: boolean; error?: string; requestError?: string; recoverNow?: boolean;
};
export type ExecutionAdapter<P, D, A> = {
  restore: () => { pending: P | null; selectedId: string };
  save: (pending: P | null, selectedId: string) => void;
  remove: () => void;
  load: (snapshot: ExecutionSnapshot<P, D>, signal: AbortSignal) => Promise<ExecutionUpdate<D>>;
  accept: (value: A, snapshot: ExecutionSnapshot<P, D>) => ExecutionUpdate<D>;
  failure: (error: unknown, snapshot: ExecutionSnapshot<P, D>, phase: 'load' | 'request') => ExecutionUpdate<D>;
};

// Adapters interpret business responses; this module owns request/storage/time ordering.
export function useExecutionTracking<P, D, A>(context: string, revision: number, initial: D, adapter: ExecutionAdapter<P, D, A>) {
  const [state, setState] = useState(() => ({ ...adapter.restore(), data: initial, busy: false }));
  const [loading, setLoading] = useState(false), [verified, setVerified] = useState(false);
  const [error, setError] = useState(''), [requestError, setRequestError] = useState('');
  const [checked, setChecked] = useState(''), [control, setControl] = useState('');
  const current = useRef(state), live = useRef(false), sequence = useRef(0), generation = useRef(0);
  const inFlight = useRef(false), working = useRef(false), timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const latest = useRef(adapter), scope = useRef(context);
  const query = useRef<AbortController | null>(null), poll = useRef(false);
  latest.current = adapter;
  function change(next: ExecutionSnapshot<P, D>) { current.current = next; setState(next); }
  function schedule(again: boolean) {
    clearTimeout(timer.current); timer.current = undefined;
    if (again && live.current) timer.current = setTimeout(() => { void reload(true); }, 2000);
  }
  function apply(update: ExecutionUpdate<D>) {
    const before = current.current;
    const next = { ...before, data: update.data, pending: update.clearPending ? null : before.pending, selectedId: update.selectedId ?? before.selectedId,
      ...(update.forget ? { pending: null, selectedId: '', busy: false } : {}) };
    change(next);
    if (update.forget) {
      sequence.current++; generation.current++; query.current?.abort(); inFlight.current = false; working.current = false;
      setLoading(false); setControl(''); latest.current.remove();
    }
    else if (next.pending !== before.pending || next.selectedId !== before.selectedId) latest.current.save(next.pending, next.selectedId);
    if (update.verified !== undefined) setVerified(update.verified);
    if (update.checked) setChecked(new Date().toLocaleTimeString());
    if (update.requestError !== undefined) setRequestError(update.requestError);
    setError(update.error ?? '');
    poll.current = update.poll; schedule(update.poll || working.current);
  }
  async function reload(background = false) {
    if (!live.current || background && inFlight.current) return;
    schedule(false);
    query.current?.abort(); query.current = new AbortController();
    const ticket = ++sequence.current, handler = latest.current, snapshot = current.current;
    inFlight.current = true; if (!background) setLoading(true);
    try {
      const update = await handler.load(snapshot, query.current.signal);
      if (live.current && ticket === sequence.current) apply(update.forget || snapshot.selectedId === current.current.selectedId ? update : { ...update, selectedId: undefined });
    } catch (value) {
      if (live.current && ticket === sequence.current) apply(handler.failure(value, current.current, 'load'));
    } finally {
      if (live.current && ticket === sequence.current) { inFlight.current = false; setLoading(false); }
    }
  }
  useEffect(() => {
    live.current = true; sequence.current++; generation.current++; inFlight.current = false; working.current = false;
    if (scope.current !== context) { scope.current = context; change({ ...latest.current.restore(), data: initial, busy: false }); setChecked(''); setRequestError(''); }
    else change({ ...current.current, busy: false });
    setVerified(false); setControl(''); void reload();
    const visible = () => { if (!document.hidden) void reload(); };
    document.addEventListener('visibilitychange', visible);
    return () => { live.current = false; sequence.current++; generation.current++; query.current?.abort(); schedule(false); document.removeEventListener('visibilitychange', visible); };
  }, [context, revision]);
  function select(selectedId: string) {
    if (!live.current) return;
    change({ ...current.current, selectedId }); latest.current.save(current.current.pending, selectedId);
  }
  async function request(operation: () => Promise<A>, label: string, pending?: P, complete?: () => Promise<void>): Promise<boolean> {
    if (!live.current || working.current) return false;
    const ticket = ++generation.current, handler = latest.current;
    sequence.current++; query.current?.abort(); inFlight.current = false; working.current = true;
    change({ ...current.current, busy: true, ...(pending === undefined ? {} : { pending, selectedId: '' }) });
    setError(''); setRequestError(''); setControl(label); schedule(true);
    try {
      if (pending !== undefined) handler.save(pending, '');
      const value = await operation();
      if (!live.current || ticket !== generation.current) return false;
      sequence.current++; query.current?.abort(); inFlight.current = false;
      apply(handler.accept(value, current.current));
      await reload();
      if (live.current && ticket === generation.current) await complete?.();
      return live.current && ticket === generation.current;
    } catch (value) {
      if (live.current && ticket === generation.current) {
        const update = handler.failure(value, current.current, 'request');
        apply(update); setError(''); setRequestError(update.error ?? '');
        if (update.recoverNow) await reload(true);
      }
      return false;
    } finally {
      if (live.current && ticket === generation.current) { working.current = false; change({ ...current.current, busy: false }); setControl(''); schedule(poll.current); }
    }
  }
  return { ...state, loading, verified, error, requestError, checked, control, reload, request, select };
}
