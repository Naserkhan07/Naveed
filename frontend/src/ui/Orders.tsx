import { useState } from 'react';
import type { Layout, OrderCard } from '../types';
import { Pill, fmtPx, seatColor } from './common';

const VERDICT_COL: Record<string, string> = { ENTRY: '#22c55e', EXIT: '#ef4444' };

export function Orders({ orders, layout, selected, onSelect, onAsk }: { orders: OrderCard[]; layout: Layout | null; selected: string | null; onSelect: (id: string) => void; onAsk: (id: string, seat: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="panel orders">
      <div className="ph"><b>Order flow</b><span className="muted">{orders.length} tickets</span></div>
      <div className="list">
        {orders.length === 0 && <div className="muted pad">The hunter has not sent a trade yet — the fly is still roaming.</div>}
        {orders.map((o) => {
          const isOpen = open === o.id;
          const vc = VERDICT_COL[o.verdict];
          return (
            <div key={o.id} className={'card' + (selected === o.id ? ' sel' : '')} onClick={() => { onSelect(o.id); setOpen(isOpen ? null : o.id); }}>
              <div className="ct">
                <b className={o.dir === 'LONG' ? 'up' : 'dn'}>{o.dir}</b><b>{o.sym.replace('_', ' ')}</b>
                <span className="muted">{o.cls} · {o.emitter}</span>
                <span className="grow" />
                {o.verdict ? <Pill color={vc} solid>{o.verdict}{o.path ? ` · ${o.path}` : ''}</Pill> : <Pill>{o.status.replace('_', ' ')}</Pill>}
              </div>
              <div className="cm muted">conv {o.conviction.toFixed(2)} · R:R {o.rr.toFixed(2)} · desk {String(o.desk + 1).padStart(2, '0')} · {o.regime}</div>
              <div className="votes">
                {Array.from({ length: 5 }, (_, i) => {
                  const v = o.votes[i];
                  const seat = layout?.cabins[i]?.seat ?? '';
                  const col = seatColor(layout, seat);
                  return <span key={i} className={'vote ' + (v ? v.vote : 'wait')} style={{ '--c': col } as React.CSSProperties} title={v ? `${seat}: ${v.reason}` : `${seat}: waiting`}>{seat.slice(0, 3)}{v ? (v.vote === 'approve' ? ' ✓' : ' ✗') : ' …'}</span>;
                })}
                {o.ceo && <span className={'vote ceo ' + o.ceo.vote} style={{ '--c': seatColor(layout, 'NAVEED') } as React.CSSProperties} title={o.ceo.reason}>CEO {o.ceo.vote === 'approve' ? '✓' : '✗'}</span>}
              </div>
              {o.r != null && <div className="cr"><b className={o.r >= 0 ? 'up' : 'dn'}>{o.r >= 0 ? '+' : ''}{o.r.toFixed(2)}R</b><span className="muted">paper {o.paper}</span></div>}
              {o.r == null && o.paper && o.paper !== 'pending' && <div className="cr muted">paper {o.paper}</div>}
              {isOpen && (
                <div className="detail" onClick={(e) => e.stopPropagation()}>
                  <div className="lv"><span>entry {fmtPx(o.entry)}</span><span className="dn">SL {fmtPx(o.sl)}</span><span className="up">TP {fmtPx(o.tp)}</span></div>
                  {o.votes.map((v) => (
                    <div key={v.seat} className="vr"><b style={{ color: seatColor(layout, v.seat) }}>{v.seat}</b> <span className={v.vote === 'approve' ? 'up' : 'dn'}>{v.vote}</span> <span className="muted">{v.label}</span><div>{v.reason}</div></div>
                  ))}
                  {o.ceo && <div className="vr"><b style={{ color: seatColor(layout, 'NAVEED') }}>NAVEED</b> <span className={o.ceo.vote === 'approve' ? 'up' : 'dn'}>{o.ceo.vote}</span> <span className="muted">{o.ceo.label}</span><div>{o.ceo.reason}</div></div>}
                  <div className="ask">Ask about this trade:
                    {['DROSOPHILA', ...(layout?.cabins.map((c) => c.seat) ?? []), 'NAVEED'].map((s) => (
                      <button key={s} style={{ '--c': seatColor(layout, s) } as React.CSSProperties} onClick={() => onAsk(o.id, s)}>{s.slice(0, 4)}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
