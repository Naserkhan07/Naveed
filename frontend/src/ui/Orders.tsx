import { useMemo, useState } from 'react';
import type { Layout, OrderCard } from '../types';
import { postJSON } from '../api';
import { Pill, fmtPx, seatColor } from './common';

const VERDICT_COL: Record<string, string> = { ENTRY: '#2fc68a', EXIT: '#f0616d' };
type F = 'all' | 'active' | 'entry' | 'exit';

export function Orders({ orders, layout, selected, onSelect, onAsk, onDossier }: { orders: OrderCard[]; layout: Layout | null; selected: string | null; onSelect: (id: string) => void; onAsk: (id: string, seat: string) => void; onDossier: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState<F>('all');
  const [busy, setBusy] = useState<string | null>(null);
  const shown = useMemo(() => orders.filter((o) => f === 'all' || (f === 'active' ? !o.verdict : f === 'entry' ? o.verdict === 'ENTRY' : o.verdict === 'EXIT')), [orders, f]);
  const seats = layout?.cabins.map((c) => c.seat) ?? [];
  async function place(id: string) {
    setBusy(id);
    try { await postJSON(`/api/trades/${id}/mt5`, {}); } catch { /* status shows on the card */ } finally { setBusy(null); }
  }
  return (
    <div className="pane">
      <div className="filters">
        {(['all', 'active', 'entry', 'exit'] as F[]).map((k) => <button key={k} className={f === k ? 'on' : ''} onClick={() => setF(k)}>{k[0].toUpperCase() + k.slice(1)}</button>)}
        <span className="grow" /><span className="muted small" style={{ alignSelf: 'center' }}>{orders.length} tickets</span>
      </div>
      <div className="list">
        {shown.length === 0 && <div className="empty muted">{orders.length ? 'No tickets match this filter.' : 'The fly-brain has not emitted a trade yet. It scans every second — the first ticket walks in through the welcome door.'}</div>}
        {shown.map((o) => {
          const isOpen = open === o.id;
          const vcol = VERDICT_COL[o.verdict] ?? (o.verdict ? '#8492a8' : '#4c9aff');
          const stageCab = o.stage.startsWith('hearing_') ? (o.stage === 'hearing_exec' ? 6 : +o.stage.split('_')[1]) : 0;
          return (
            <div key={o.id} className={'card' + (selected === o.id ? ' sel' : '')} style={{ '--c': vcol } as React.CSSProperties}
              onClick={() => { onSelect(o.id); setOpen(isOpen ? null : o.id); }} onDoubleClick={() => onDossier(o.id)}>
              <div className="ct">
                <span className="sym">{o.sym.replace('_', ' ')}</span><span className={'dirb ' + o.dir}>{o.dir}</span>
                <span className="muted small">{o.cls}</span>
                <span className="grow" />
                {o.verdict ? <Pill color={vcol} solid>{o.verdict}</Pill> : <Pill color="#4c9aff" solid>{o.status.replace(/_/g, ' ')}</Pill>}
              </div>
              <div className="cm muted"><span>conv <b className="mono">{o.conviction.toFixed(2)}</b></span><span>R:R <b className="mono">{o.rr.toFixed(2)}</b></span><span>desk <b className="mono">{String(o.desk + 1).padStart(2, '0')}</b></span><span>{o.emitter}</span><span>{o.regime}</span></div>
              <div className="steps">
                {Array.from({ length: 5 }, (_, i) => {
                  const v = o.votes[i]; const seat = seats[i] ?? '';
                  return <div key={i} className={'step ' + (v ? v.vote : stageCab === i + 1 ? 'now' : 'wait')} title={v ? `${seat}: ${v.thesis || v.reason}` : seat}>
                    {seat.slice(0, 3)} {v ? (v.vote === 'approve' ? '✓' : '✗') : '·'}<small>{v?.confidence != null ? `${v.confidence}%` : '—'}</small></div>;
                })}
                <div className={'step ' + (o.ceo ? o.ceo.vote : stageCab === 6 ? 'now' : 'wait')} title={o.ceo?.thesis || o.ceo?.reason || 'CEO NAVEED (only on a 3–4 split)'}>CEO {o.ceo ? (o.ceo.vote === 'approve' ? '✓' : '✗') : '·'}<small>{o.ceo?.confidence != null ? `${o.ceo.confidence}%` : '—'}</small></div>
              </div>
              <div className="cr">
                {o.r != null ? <b className={'mono ' + (o.r >= 0 ? 'up' : 'dn')}>{o.r >= 0 ? '+' : ''}{o.r.toFixed(2)}R</b> : null}
                <span className="muted small">paper {o.paper}{o.path ? ` · ${o.path}` : ''}</span>
                <span className="grow" />
                <button className="linkbtn" onClick={(e) => { e.stopPropagation(); onDossier(o.id); }}>Full details ▸</button>
                {o.mt5?.status && <Pill color={o.mt5.status === 'filled' ? '#2fc68a' : o.mt5.status === 'error' ? '#f0616d' : '#f5b73b'}>MT5 {o.mt5.status}</Pill>}
              </div>
              {isOpen && (
                <div className="detail" onClick={(e) => e.stopPropagation()}>
                  <div className="lv"><div><span>Entry</span>{fmtPx(o.entry)}</div><div><span>Stop</span><b className="dn">{fmtPx(o.sl)}</b></div><div><span>Target</span><b className="up">{fmtPx(o.tp)}</b></div><div><span>R:R</span>{o.rr.toFixed(2)}</div></div>
                  {o.votes.map((v) => (
                    <div key={v.seat} className="vr" style={{ '--c': seatColor(layout, v.seat) } as React.CSSProperties}>
                      <div className="vh"><b style={{ color: seatColor(layout, v.seat) }}>{v.seat}</b><span className={v.vote === 'approve' ? 'up' : 'dn'}>{v.vote.toUpperCase()}</span>
                        <div className="conf"><i style={{ width: `${v.confidence ?? 50}%`, background: v.vote === 'approve' ? 'var(--up)' : 'var(--dn)' }} /></div><span className="mono small">{v.confidence ?? '—'}%</span></div>
                      <div className="th">{v.thesis || v.reason}</div>
                      {v.risk && <div className="rk"><b>Risk · </b>{v.risk}</div>}
                      <div className="dim small mono">{v.label}</div>
                    </div>
                  ))}
                  {o.ceo && (
                    <div className="vr" style={{ '--c': seatColor(layout, 'NAVEED') } as React.CSSProperties}>
                      <div className="vh"><b style={{ color: seatColor(layout, 'NAVEED') }}>NAVEED · CEO</b><span className={o.ceo.vote === 'approve' ? 'up' : 'dn'}>{o.ceo.vote.toUpperCase()}</span>
                        <div className="conf"><i style={{ width: `${o.ceo.confidence ?? 50}%`, background: o.ceo.vote === 'approve' ? 'var(--up)' : 'var(--dn)' }} /></div><span className="mono small">{o.ceo.confidence ?? '—'}%</span></div>
                      <div className="th">{o.ceo.thesis || o.ceo.reason}</div>
                      {o.ceo.risk && <div className="rk"><b>Risk · </b>{o.ceo.risk}</div>}
                    </div>
                  )}
                  <div className="mt5box">
                    <b>MetaTrader 5</b>
                    {o.mt5?.status ? <span className="small">{o.mt5.status}{o.mt5.mt5_ticket ? ` · #${o.mt5.mt5_ticket}` : ''}{o.mt5.price ? ` @ ${o.mt5.price}` : ''}{o.mt5.msg ? ` — ${o.mt5.msg}` : ''}</span> : <span className="muted small">not sent</span>}
                    <span className="grow" />
                    <button className="btn pri sm" disabled={o.cls !== 'forex' || busy === o.id || o.mt5?.status === 'filled' || o.mt5?.status === 'queued' || o.mt5?.status === 'sent'}
                      title={o.cls !== 'forex' ? 'Only forex symbols are routed to MT5' : 'Queue a market order for the MT5 bridge'} onClick={() => place(o.id)}>Place in MT5</button>
                  </div>
                  <div className="ask">Ask about this trade:
                    {['DROSOPHILA', ...seats, 'NAVEED'].map((s) => <button key={s} style={{ '--c': seatColor(layout, s) } as React.CSSProperties} onClick={() => onAsk(o.id, s)}>{s.slice(0, 4)}</button>)}
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
