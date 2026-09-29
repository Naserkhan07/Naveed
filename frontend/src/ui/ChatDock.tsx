import { useEffect, useRef, useState } from 'react';
import type { ChatMsg, Extra, Layout } from '../types';
import { postJSON } from '../api';
import { SEAT_ORDER, SEAT_ROLE, seatColor } from './common';

export const ALL = '@ALL', ROOM = '@ROOM';
const SUGGEST: Record<string, string[]> = {
  ATLAS: ['What is the macro regime right now?', 'Which currency is strongest?'],
  QUANTA: ['How is the edge holding up?', 'Explain expectancy in R'],
  MERIDIAN: ['Where is the order flow leaning?', 'What is a spread ratio?'],
  VOLTA: ['How much risk is open?', 'What is ATR?'],
  VECTOR: ['Which setups are trending?', 'What is efficiency ratio?'],
  NAVEED: ['Why did you overrule the council last?', 'What is your doctrine?'],
  DROSOPHILA: ['What are you hunting?', 'How does the mushroom body learn?'],
  [ALL]: ['What is 17 × 23?', 'Should we be trading today?'],
  [ROOM]: ['Hello everyone', 'ATLAS, what do you see?'],
};

interface Props {
  layout: Layout | null; extra: Extra | null; target: string; tradeId: string | null;
  onTarget: (t: string) => void; onClearTrade: () => void;
}

export function ChatDock({ layout, extra, target, tradeId, onTarget, onClearTrade }: Props) {
  const [msgs, setMsgs] = useState<Record<string, ChatMsg[]>>({});
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const key = tradeId && !target.startsWith('@') ? `${target}@${tradeId}` : target;
  const list = msgs[key] ?? [];
  const room = extra?.chatroom ?? [];
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [list.length, room.length, busy, key]);

  const push = (k: string, ...m: ChatMsg[]) => setMsgs((s) => ({ ...s, [k]: [...(s[k] ?? []), ...m] }));
  const color = target === ALL ? '#38bdf8' : target === ROOM ? '#e2e8f0' : seatColor(layout, target);

  async function send(q?: string) {
    const question = (q ?? text).trim();
    if (!question || busy) return;
    setText(''); setBusy(true);
    const k = key;
    push(k, { role: 'user', content: question });
    try {
      if (target === ALL) {
        const r = await postJSON<{ answers: { seat: string; answer: string; label: string; ms: number; color: string }[] }>('/api/debate/ask', { question });
        push(k, ...r.answers.map((a) => ({ role: 'assistant' as const, content: a.answer, label: a.label, ms: a.ms, seat: a.seat, color: a.color })));
      } else if (target === ROOM) {
        await postJSON('/api/chatroom/say', { text: question, name: 'operator' });
      } else if (tradeId) {
        const r = await postJSON<{ seat: string; answer: string; label: string; ms: number; color: string }>(`/api/trades/${tradeId}/chat`, { question, seat_id: target });
        push(k, { role: 'assistant', content: r.answer, label: r.label, ms: r.ms, seat: r.seat, color: r.color });
      } else {
        const hist = list.slice(-12).map((m) => ({ role: m.role, content: m.content }));
        const r = await postJSON<{ seat: string; answer: string; label: string; ms: number; color: string }>('/api/chat', { seat_id: target, question, history: hist });
        push(k, { role: 'assistant', content: r.answer, label: r.label, ms: r.ms, seat: r.seat, color: r.color });
      }
    } catch (e) {
      push(k, { role: 'assistant', content: `Request failed (${(e as Error).message}). The desk could not be reached.`, label: 'error' });
    } finally { setBusy(false); }
  }

  const seatInfo = (id: string) => extra?.seats.find((s) => s.id === id);
  return (
    <div className="panel chat">
      <div className="tabs">
        {SEAT_ORDER.map((s) => {
          const info = seatInfo(s); const busyNow = info && info.state !== 'idle';
          return <button key={s} className={target === s ? 'on' : ''} style={{ '--c': seatColor(layout, s) } as React.CSSProperties} onClick={() => onTarget(s)} title={SEAT_ROLE[s]}>
            <i className={busyNow ? 'live' : ''} />{s.slice(0, 4)}</button>;
        })}
        <button className={target === ALL ? 'on' : ''} style={{ '--c': '#38bdf8' } as React.CSSProperties} onClick={() => onTarget(ALL)} title="ask every desk at once">ALL</button>
        <button className={target === ROOM ? 'on' : ''} style={{ '--c': '#e2e8f0' } as React.CSSProperties} onClick={() => onTarget(ROOM)} title="open chatroom">ROOM</button>
      </div>
      <div className="ph sm">
        <b style={{ color }}>{target === ALL ? 'All desks' : target === ROOM ? 'Chatroom' : target}</b>
        <span className="muted">{target === ALL ? 'debate table — every judge answers' : target === ROOM ? 'shared room' : SEAT_ROLE[target]}</span>
        {tradeId && !target.startsWith('@') && <button className="chip" onClick={onClearTrade} title="leave trade context">trade {tradeId} ✕</button>}
      </div>
      <div className="msgs">
        {target === ROOM ? room.map((m, i) => (
          <div key={i} className={'bub ' + (m.name === 'operator' ? 'user' : 'bot')} style={{ '--c': m.color } as React.CSSProperties}>
            {m.name !== 'operator' && <div className="who" style={{ color: m.color }}>{m.name}</div>}
            <div>{m.text}</div>{m.label && <div className="meta">{m.label}</div>}
          </div>
        )) : list.length === 0 ? (
          <div className="empty">
            <div className="muted">Ask {target === ALL ? 'the whole floor' : target} anything — market, trade, or general knowledge.</div>
            <div className="sugg">{(SUGGEST[target] ?? []).map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        ) : list.map((m, i) => (
          <div key={i} className={'bub ' + (m.role === 'user' ? 'user' : 'bot')} style={{ '--c': m.color ?? color } as React.CSSProperties}>
            {m.role === 'assistant' && (target === ALL || target.startsWith('@')) && m.seat && <div className="who" style={{ color: m.color }}>{m.seat}</div>}
            <div className="txt">{m.content}</div>
            {m.role === 'assistant' && m.label && <div className="meta">{m.label}{m.ms ? ` · ${(m.ms / 1000).toFixed(1)}s` : ''}</div>}
          </div>
        ))}
        {busy && <div className="bub bot typing" style={{ '--c': color } as React.CSSProperties}><span /><span /><span /></div>}
        <div ref={end} />
      </div>
      <form className="inp" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={target === ROOM ? 'Say something to the room…' : `Message ${target === ALL ? 'all desks' : target}…`} />
        <button disabled={busy || !text.trim()} style={{ background: color }}>↑</button>
      </form>
    </div>
  );
}
