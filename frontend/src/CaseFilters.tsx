import type { Case } from './types';

export type CaseFilterProps = { search: string; eventFilter: string; setSearch: (value: string) => void; setEventFilter: (value: string) => void };

export function matchesCase(item: Case, search: string, eventFilter: string) {
  return (!eventFilter || item.event_id === eventFilter) &&
    `${item.sequence_no ?? ''} ${item.event_id} ${item.participant_id} ${item.dog_name} ${item.guardian_name}`.toLowerCase().includes(search.toLowerCase());
}

export function CaseFilters({ cases, search, eventFilter, setSearch, setEventFilter }: CaseFilterProps & { cases: Case[] }) {
  return <div className="toolbar"><label>검색<input type="search" placeholder="순번, ID, 반려견, 보호자" value={search} onChange={e => setSearch(e.target.value)} /></label>
    <label>행사 필터<select value={eventFilter} onChange={e => setEventFilter(e.target.value)}><option value="">모든 행사</option>
      {[...new Set(cases.map(c => c.event_id))].map(id => <option key={id}>{id}</option>)}</select></label></div>;
}
