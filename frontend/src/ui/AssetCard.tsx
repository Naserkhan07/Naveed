import { useEffect } from 'react';
import type { Extra } from '../types';
import { Pill, fmtPx } from './common';

/** click on an ambient trader → what they are watching: live price, regime, fly-brain hunger, and any tickets on that asset */
export function AssetCard({ sym, extra, onClose, onOpenTrade }: { sym: string; extra: Extra | null; onClose: () => void; onOpenTrade: (id: string) => void }) {
  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h); }, [onClose]);
  const row = extra?.tape.find((t) => t.s === sym);
  const watch = extra?.fly.watch.find((w) => w.s === sym);
  const focus = extra?.fly.focus.s === sym ? extra.fly : null;
  const trades = (extra?.orders ?? []).filter((o) => o.sym === sym);
  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog" style={{ width: 520, height: 'auto', maxHeight: '86vh' }} onClick={(e) => e.stopPropagation()}>
        <div className="ph"><span className="sym" style={{ fontSize: 16 }}>{sym}</span>{row && <span className="muted small">{row.c}</span>}<span className="grow" /><button className="btn sm" onClick={onClose}>Close ✕</button></div>
        <div className="dbody">
          <div className="note-box" style={{ borderColor: 'var(--line2)', background: 'var(--s2)' }}>This trader is an ambient desk-mate watching <b>{sym}</b> — one of the assets the fly-brain is currently hungriest for. They carry no trade yet. When the hunter emits a ticket, a new trader walks in through the welcome door carrying it.</div>
          {row ? (
            <div className="kvgrid">
              <div><span>Price</span>{fmtPx(row.p)}</div>
              <div><span>Change</span><b className={row.ch >= 0 ? 'up' : 'dn'}>{row.ch >= 0 ? '+' : ''}{row.ch.toFixed(2)}%</b></div>
              <div><span>Regime</span>{row.r}</div>
            </div>
          ) : <div className="muted">No tape row for this symbol.</div>}
          <div className="sect" style={{ paddingLeft: 0 }}>Fly-brain view</div>
          {watch ? <div className="kvgrid"><div><span>Hunger</span>{watch.h.toFixed(2)}</div><div><span>Threshold</span>{extra?.fly.threshold.toFixed(2)}</div><div><span>Missing senses</span>{watch.missing.length ? watch.missing.join(', ') : 'none'}</div></div>
            : focus ? <div className="kvgrid"><div><span>Hunger (focus)</span>{focus.focus.hunger.toFixed(2)}</div><div><span>Direction</span>{focus.focus.dir > 0 ? 'long' : 'short'}</div><div><span>State</span>{focus.state}</div></div>
              : <div className="muted small">Not on the fly-brain's watch-list at this moment.</div>}
          <div className="sect" style={{ paddingLeft: 0 }}>Tickets on {sym}</div>
          {trades.length === 0 ? <div className="muted small">No ticket has been emitted for this asset recently.</div> : trades.map((o) => (
            <div key={o.id} className="set-row" style={{ cursor: 'pointer' }} onClick={() => onOpenTrade(o.id)}>
              <div><b>{o.id}</b> <span className={'dirb ' + o.dir}>{o.dir}</span> <span className="muted small">conv {o.conviction.toFixed(2)} · R:R {o.rr.toFixed(2)}</span></div>
              {o.verdict ? <Pill color={o.verdict === 'ENTRY' ? '#2fc68a' : '#f0616d'} solid>{o.verdict}</Pill> : <Pill color="#4c9aff" solid>{o.status.replace(/_/g, ' ')}</Pill>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
