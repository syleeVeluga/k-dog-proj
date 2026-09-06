import { useEffect, useRef } from 'react';

export function EvidencePlayer({ src, title, description, close }: {
  src: string; title: string; description?: string; close: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') closeRef.current(); };
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('keydown', escape); if (trigger?.isConnected) trigger.focus({ preventScroll: true }); };
  }, []);
  return <aside className="evidence-player" role="dialog" aria-label="원본 근거" tabIndex={-1} ref={panel}>
    <div className="section-title"><h3>{title}</h3><button onClick={close}>근거 재생 닫기</button></div>
    <video key={src} controls preload="metadata" src={src} />
    {description && <p>{description}</p>}
    <p className="fine">화면을 이동해도 근거는 이 위치에서 확인할 수 있습니다. Esc로 닫습니다.</p>
  </aside>;
}
