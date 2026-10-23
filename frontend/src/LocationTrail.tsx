import { participantTasks, routeGroup, routeLabel } from './navigation';
import type { Route } from './navigation';
import type { Case } from './types';

export function LocationTrail({ route, selected, listRoute, back }: {
  route: Route; selected: Case | null; listRoute: Route; back: () => void;
}) {
  const preparation = participantTasks.includes(route);
  const parent = preparation && selected ? listRoute : route.startsWith('recording/') ? 'intake' : route;
  return <nav className="location-trail" aria-label="현재 위치"><ol>
    <li>{routeGroup(parent)}</li>
    {selected ? <>
      <li><button className="plain" onClick={back}>{routeLabel(parent)} 목록</button></li>
      <li aria-current={preparation ? undefined : 'page'}>{selected.participant_id} · {selected.dog_name}</li>
      {preparation && <li aria-current="page">{routeLabel(route)}</li>}
    </> : <>
      {route.startsWith('recording/') && <li><button className="plain" onClick={back}>참가자 목록</button></li>}
      <li aria-current="page">{routeLabel(route)}</li>
    </>}
  </ol></nav>;
}

export function ParticipantTasks({ route, go }: { route: Route; go: (route: Route) => void }) {
  return <nav className="participant-tabs" aria-label="참가자 작업">
    {participantTasks.map(task => <button key={task} aria-current={route === task ? 'page' : undefined} onClick={() => go(task)}>{routeLabel(task)}</button>)}
  </nav>;
}
