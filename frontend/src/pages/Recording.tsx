import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { mayLeave, useUnsaved } from '../Editing';
import { SessionEditor } from '../MetadataEditors';
import { VideoUpload } from '../VideoUpload';
import { SEGMENTS, formFields, segmentState, sessionOf } from '../types';
import type { Case, Run, SegmentWindow } from '../types';

type Props = { cases: Case[]; writable: boolean; run: Run; reload: (id?: string) => Promise<void>; notify: (message: string) => void };

export function toClock(seconds: number) {
  const rounded = Math.round(seconds * 10) / 10;  // round first so 59.96 becomes 1:00.0, never 0:60.0
  const minutes = Math.floor(rounded / 60);
  return `${minutes}:${(rounded - minutes * 60).toFixed(1).padStart(4, '0')}`;
}
export function fromClock(text: string): number | null {
  const match = /^(\d+):([0-5]?\d(?:\.\d+)?)$/.exec(text.trim());
  if (match) return Number(match[1]) * 60 + Number(match[2]);
  return /^\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : null;
}

// 촬영 메뉴: 한 쌍의 영상 파일을 여러 개 등록하고, 기준 영상 위에서 8구간 시작·끝 시각을 적어 확정한다(01 §2). 카메라 구분은 없다.
export function Recording({ cases, writable, run, reload, notify }: Props) {
  const [selectedId, setSelectedId] = useState('');
  const selected = cases.find(c => c.case_id === selectedId) ?? null;
  const sorted = [...cases].sort((a, b) => (a.sequence_no ?? 1e9) - (b.sequence_no ?? 1e9) || a.participant_id.localeCompare(b.participant_id));
  const confirmed = cases.filter(c => segmentState(sessionOf(c)) === 'confirmed').length;
  return <>
    <section className="page-heading"><div><p className="eyebrow">RECORDING</p><h1>촬영</h1><p className="muted">영상 파일을 등록하고 8구간의 시작·끝 시각을 기록합니다. 구간 경계는 마이크 음성과 진행자 신호로 잡습니다. 확정 전에는 채점을 시작하지 않습니다.</p></div>
      <div className="count"><strong>{confirmed.toString().padStart(2, '0')}</strong><span>구간 확정 / {cases.length}명</span></div></section>
    <div className="table-wrap"><table><thead><tr><th>순번</th><th>참가자</th><th>반려견 / 보호자</th><th>영상</th><th>구간</th><th>작업</th></tr></thead>
      <tbody>{sorted.map(c => { const s = sessionOf(c); const state = segmentState(s);
        return <tr key={c.case_id}><td data-label="순번"><strong className="mono">{c.sequence_no ?? '—'}</strong></td>
          <td data-label="참가자"><strong className="mono">{c.participant_id}</strong><small>{c.event_id}</small></td>
          <td data-label="반려견 / 보호자">{c.dog_name}<small>{c.guardian_name ? `${c.guardian_name} 님` : '보호자명 없음'}</small></td>
          <td data-label="영상">{s.videos.length}개</td>
          <td data-label="구간"><span className={state === 'confirmed' ? 'tag green' : 'tag'}>{({ none: '없음', draft: '초안', confirmed: '확정' })[state]}</span></td>
          <td data-label="작업"><button aria-label={`${c.participant_id} 촬영 열기`} aria-current={c.case_id === selectedId ? 'true' : undefined} onClick={() => { if (mayLeave()) setSelectedId(c.case_id); }}>열기 ↗</button></td></tr>;
      })}</tbody></table>{!cases.length && <div className="empty"><h2>등록된 참가자가 없습니다.</h2><p>접수 메뉴에서 참가자를 먼저 등록하세요.</p></div>}</div>
    {selected && <RecordingPanel key={selected.case_id} item={selected} writable={writable} run={run} notify={notify}
      refresh={async message => { await reload(); if (message) notify(message); }} close={() => { if (mayLeave()) setSelectedId(''); }} />}
  </>;
}

function RecordingPanel({ item, writable, run, refresh, notify, close }: { item: Case; writable: boolean; run: Run; refresh: (message?: string) => Promise<void>; notify: (message: string) => void; close: () => void }) {
  const session = sessionOf(item);
  const stored = session.segments;
  const [videoId, setVideoId] = useState(stored?.video_id ?? session.videos[0]?.video_id ?? '');
  const [editing, setEditing] = useState(!stored?.confirmed);
  const [clocks, setClocks] = useState<string[]>(() => SEGMENTS.map((_, i) => stored ? toClock(stored.windows[i].start_sec) : ''));
  const [ends, setEnds] = useState<string[]>(() => SEGMENTS.map((_, i) => stored ? toClock(stored.windows[i].end_sec) : ''));
  const [dirty, setDirty] = useState(false);
  const player = useRef<HTMLVideoElement>(null);
  useUnsaved(dirty);
  useEffect(() => { if (!session.videos.some(v => v.video_id === videoId)) setVideoId(session.videos[0]?.video_id ?? ''); }, [session.videos.length]);
  const now = () => player.current ? toClock(Math.round(player.current.currentTime * 10) / 10) : '';
  function windows(): SegmentWindow[] | string {
    const result: SegmentWindow[] = [];
    for (let i = 0; i < SEGMENTS.length; i++) {
      const start = fromClock(clocks[i]); const end = fromClock(ends[i]);
      if (start === null || end === null) return `${SEGMENTS[i][1]} 구간의 시각을 m:ss 형식으로 입력하세요.`;
      result.push({ segment: SEGMENTS[i][0], start_sec: start, end_sec: end });
    }
    return result;
  }
  function save(confirm: boolean) {
    const value = windows();
    if (typeof value === 'string') { notify(value); return; }
    void run(async () => {
      await api(`/cases/${item.case_id}/sessions/${session.session_id}/segments`, 'PUT', { expected_revision: item.input_revision, video_id: videoId, windows: value, confirm });
      setClocks(value.map(w => toClock(w.start_sec))); setEnds(value.map(w => toClock(w.end_sec)));
      setDirty(false); setEditing(!confirm); await refresh(confirm ? '8구간 시각을 확정했습니다.' : '8구간 시각을 초안으로 저장했습니다.');
    });
  }
  return <section className="panel" aria-label="촬영 자료">
    <div className="section-title"><h2>{item.dog_name} · {item.participant_id}{item.sequence_no !== null && ` · 순번 ${item.sequence_no}`}</h2><button onClick={close}>닫기</button></div>
    <p className="fine">{item.manifest.sessions.findIndex(s => s.session_id === session.session_id) + 1}차 촬영 · 입력 버전 {item.input_revision} · {session.note || '촬영 메모 없음'}</p>
    {writable && <SessionEditor key={session.session_id} item={item} session={session} run={run} refresh={refresh} />}
    {writable && <details><summary>재촬영 세션 추가</summary><form onSubmit={e => { e.preventDefault(); if (!mayLeave()) return; const value = formFields(e.currentTarget); void run(async () => {
      await api(`/cases/${item.case_id}/sessions`, 'POST', { ...value, expected_revision: item.input_revision }); await refresh('새 촬영 세션을 시작했습니다.');
    }); }}><label>촬영 메모<textarea name="note" maxLength={2000} /></label><p className="fine">이전 촬영의 영상·구간은 보존됩니다.</p><button>새 촬영 시작</button></form></details>}
    <div className="section-title"><h3 id="videos">영상 파일</h3><span className="mono">{session.videos.length} FILES</span></div>
    {session.videos.length === 0 && <p className="muted">등록된 영상이 없습니다. 파일을 여러 개 선택해 한 번에 등록할 수 있습니다.</p>}
    {session.videos.map(v => <div className="video-row" key={v.video_id}><div><strong>{v.original_name}</strong><small>{(v.size_bytes / 1048576).toFixed(2)} MiB · 원본 등록됨</small></div>
      <label className="check"><input type="radio" name="reference-video" value={v.video_id} checked={videoId === v.video_id} disabled={!editing || !writable} onChange={() => { setVideoId(v.video_id); setDirty(true); }} />구간 기준 영상</label></div>)}
    {writable && <VideoUpload key={session.session_id} item={item} session={session} refresh={refresh} />}
    <div className="section-title"><h3 id="segments">8구간 시각</h3>{stored && <span className={stored.confirmed ? 'tag green' : 'tag'}>{stored.confirmed ? '확정' : '초안'}</span>}</div>
    {videoId && <video ref={player} src={`/api/cases/${item.case_id}/videos/${videoId}`} controls preload="metadata" />}
    {!session.videos.length && <p className="fine">영상을 먼저 등록하면 재생 위치로 시각을 넣을 수 있습니다.</p>}
    <fieldset disabled={!writable || !editing}><div className="table-wrap"><table><thead><tr><th>구간</th><th>시작 (m:ss)</th><th>끝 (m:ss)</th></tr></thead>
      <tbody>{SEGMENTS.map(([id, label], i) => <tr key={id}><td>{i + 1} {label}</td>
        <td><span className="toolbar"><input aria-label={`${label} 시작`} value={clocks[i]} placeholder="0:00" onChange={e => { setClocks(clocks.map((c, j) => j === i ? e.target.value : c)); setDirty(true); }} />
          <button type="button" disabled={!videoId} onClick={() => { setClocks(clocks.map((c, j) => j === i ? now() : c)); setDirty(true); }}>지금 시각</button></span></td>
        <td><span className="toolbar"><input aria-label={`${label} 끝`} value={ends[i]} placeholder="0:15" onChange={e => { setEnds(ends.map((c, j) => j === i ? e.target.value : c)); setDirty(true); }} />
          <button type="button" disabled={!videoId} onClick={() => { setEnds(ends.map((c, j) => j === i ? now() : c)); setDirty(true); }}>지금 시각</button></span></td></tr>)}
      </tbody></table></div></fieldset>
    {writable && <div className="toolbar">
      {editing ? <><button type="button" disabled={!videoId} onClick={() => save(false)}>초안 저장</button><button type="button" className="primary" disabled={!videoId} onClick={() => save(true)}>8구간 확정</button></>
        : <button type="button" onClick={() => { if (mayLeave()) setEditing(true); }}>확정 해제 후 수정</button>}
      {dirty && <p role="status">구간 시각 · 저장 전</p>}
    </div>}
    <p className="fine">확정하면 채점 단계가 이 시각을 사용합니다. 수정하면 새 입력 버전으로 저장되며 이전 값은 보존됩니다.</p>
  </section>;
}
