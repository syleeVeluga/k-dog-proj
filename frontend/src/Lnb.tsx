import { useEffect, useRef, useState } from 'react';
import { visibleMenu } from './navigation';
import type { MenuItem, Route } from './navigation';
import type { Role } from './types';

export function useMatch(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    list.addEventListener('change', update); update();
    return () => list.removeEventListener('change', update);
  }, [query]);
  return matches;
}

function chunks(items: MenuItem[]) {
  const result: { parent?: string; items: MenuItem[] }[] = [];
  for (const item of items) {
    const last = result[result.length - 1];
    if (last && last.parent === item.parent) last.items.push(item); else result.push({ parent: item.parent, items: [item] });
  }
  return result;
}

type Props = { role: Role; current: Route; go: (route: Route) => void; visible: boolean; drawer: boolean; close: () => void };

// 좌측 메뉴. 767px 이하에서는 서랍으로 열리며 포커스 이동·Esc·바깥 클릭·스크롤 잠금을 처리한다.
export function Lnb({ role, current, go, visible, drawer, close }: Props) {
  const root = useRef<HTMLElement>(null);
  const modal = drawer && visible;
  useEffect(() => {
    if (!modal) return;
    root.current?.querySelector<HTMLButtonElement>('button.lnb-item')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
      if (event.key !== 'Tab') return;
      const buttons = root.current?.querySelectorAll<HTMLButtonElement>('button');
      if (!buttons?.length) return;
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); document.body.style.overflow = overflow; };
  }, [modal]);
  return <>
    {modal && <div className="lnb-backdrop" onClick={close} aria-hidden="true" />}
    <nav ref={root} id="lnb" className={`lnb${drawer ? ' drawer' : ''}`} aria-label="주 메뉴" hidden={!visible}>
      {drawer && <button className="lnb-close" onClick={close}>메뉴 닫기</button>}
      {visibleMenu(role).map(group => <div key={group.id} role="group" aria-labelledby={`lnb-${group.id}`} className="lnb-group">
        <p id={`lnb-${group.id}`} className="lnb-title">{group.label}</p>
        {chunks(group.items).map((part, index) => part.parent
          ? <div key={index} role="group" aria-labelledby={`lnb-${group.id}-${index}`} className="lnb-sub">
            <p id={`lnb-${group.id}-${index}`} className="lnb-parent">{part.parent}</p>
            <ul>{part.items.map(item => <Entry key={item.route} item={item} current={current} go={go} />)}</ul></div>
          : <ul key={index}>{part.items.map(item => <Entry key={item.route} item={item} current={current} go={go} />)}</ul>)}
      </div>)}
    </nav>
  </>;
}

function Entry({ item, current, go }: { item: MenuItem; current: Route; go: (route: Route) => void }) {
  return <li><button className="lnb-item" aria-current={current === item.route ? 'page' : undefined} onClick={() => go(item.route)}>{item.label}</button></li>;
}
