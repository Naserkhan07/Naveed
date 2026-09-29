import type { Extra, Layout } from '../types';
import { SEAT_ORDER, seatColor } from './common';

export function Council({ extra, layout, onChat }: { extra: Extra | null; layout: Layout | null; onChat: (seat: string) => void }) {
  const seats = extra?.seats ?? [];
  const room = extra?.chatroom ?? [];
  return (
    <div className="pane" style={{ overflow: 'auto' }}>
      <div className="sect">The six judges · live calibration</div>
      {extra?.record && <div className="pad muted small" style={{ paddingTop: 0 }}>Floor record fed to every judge: {extra.record}</div>}
      {SEAT_ORDER.filter((s) => s !== 'DROSOPHILA').map((id) => {
        const s = seats.find((x) => x.id === id); if (!s) return null;
        const col = seatColor(layout, id);
        const b = s.bias;
        return (
          <div key={id} className="seatcard" style={{ '--c': col } as React.CSSProperties}>
            <div className="h"><b style={{ color: col }}>{id}</b><span className="muted small">{s.role}</span><span className="grow" />
              <span className={'pill' + (s.state !== 'idle' ? ' solid' : '')} style={{ '--c': s.state !== 'idle' ? col : '#5d6b82' } as React.CSSProperties}>{s.state}</span>
              <button className="btn sm" onClick={() => onChat(id)}>Ask</button></div>
            <div className="bio">{s.bio}</div>
            <div className="kv"><span>Model</span><span className="mono small">{s.model}</span></div>
            <div className="kv"><span>Bias</span><div className="bias"><u /><i style={{ left: `${50 + Math.max(-1, Math.min(1, b / 0.3)) * 50}%`, background: b >= 0 ? 'var(--up)' : 'var(--dn)' }} /></div><span className="mono small">{b >= 0 ? '+' : ''}{b.toFixed(2)}</span></div>
            {s.notes.length > 0 && <div style={{ marginTop: 4 }}>{s.notes.slice().reverse().map((n, i) => <div key={i} className="note">{n}</div>)}</div>}
          </div>
        );
      })}
      <div className="sect" style={{ marginTop: 10 }}>Debate room · they argue, then write a rule</div>
      <div className="transcript">
        {room.length === 0 && <div className="muted small pad">The floor opens its first debate after about 25 sim-seconds.</div>}
        {room.slice(-14).map((m, i) => (
          <div key={i} className="tmsg">
            <div className="av" style={{ background: m.color }}>{m.name.slice(0, 2)}</div>
            <div className="tb"><div className="who" style={{ color: m.color }}>{m.name}{m.label ? <span className="dim"> · {m.label}</span> : null}</div>{m.text}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
