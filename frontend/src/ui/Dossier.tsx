import { useEffect, useState } from 'react';
import { getJSON, postJSON } from '../api';
import type { Layout, TradeDetail } from '../types';
import { Pill, SEAT_ROLE, fmtPx, seatColor } from './common';

const fmtT = (s: number | null | undefined) => (s == null ? '—' : `${Math.floor(s / 60)}m ${String(Math.floor(s % 60)).padStart(2, '0')}s`);
const STAGE: Record<string, string> = {
  spawn: 'Signal emitted by the hunter', to_desk: 'Entered through the welcome door, walking to desk', seated: 'Seated at desk', review: 'In review',
  hearing_exec: 'CEO hearing in the executive chamber', leave_entry: 'Left through the ENTRY gate', leave_exit: 'Left through the EXIT gate',
};
const stageName = (s: string) => STAGE[s] ?? (s.startsWith('hearing_') ? `Judge hearing — cabin ${s.split('_')[1]}` : s.startsWith('to_cabin') ? `Walking to cabin ${s.split('_')[2] ?? ''}` : s.replace(/_/g, ' '));

export function Dossier({ id, layout, onClose, onAsk }: { id: string; layout: Layout | null; onClose: () => void; onAsk: (id: string, seat: string) => void }) {
  const [d, setD] = useState<TradeDetail | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let dead = false;
    const go = () => getJSON<TradeDetail>(`/api/trades/${id}/detail`).then((r) => { if (!dead) setD(r); }).catch((e) => setErr(String(e)));
    go(); const t = window.setInterval(go, 2000);
    return () => { dead = true; clearInterval(t); };
  }, [id]);
  useEffect(() => { const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h); }, [onClose]);
  const c = d?.card;
  const vcol = c?.verdict === 'ENTRY' ? '#2fc68a' : c?.verdict === 'EXIT' ? '#f0616d' : '#4c9aff';
  const seats = layout?.cabins.map((x) => x.seat) ?? [];
  async function place() { setBusy(true); try { await postJSON(`/api/trades/${id}/mt5`, {}); } finally { setBusy(false); } }
  const maxS = Math.max(0.001, ...(d?.found.top_senses.map((s) => Math.abs(s.v)) ?? [1]));
  const maxM = Math.max(0.001, ...(d?.found.mbon.map((s) => Math.abs(s.v)) ?? [1]));

  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog dossier" onClick={(e) => e.stopPropagation()}>
        <div className="ph">
          {c ? <>
            <span className="sym" style={{ fontSize: 16 }}>{c.sym}</span><span className={'dirb ' + c.dir}>{c.dir}</span>
            <span className="muted small">{c.cls} · trade {c.id} · desk {String(c.desk + 1).padStart(2, '0')}</span>
            {c.verdict ? <Pill color={vcol} solid>{c.verdict}{c.path ? ` · ${c.path}` : ''}</Pill> : <Pill color="#4c9aff" solid>{c.status.replace(/_/g, ' ')}</Pill>}
            {c.r != null && <b className={'mono ' + (c.r >= 0 ? 'up' : 'dn')}>{c.r >= 0 ? '+' : ''}{c.r.toFixed(2)}R</b>}
          </> : <b>Trade dossier</b>}
          <span className="grow" /><button className="btn sm" onClick={onClose}>Close ✕</button>
        </div>
        <div className="dbody">
          {!d || !c ? <div className="pad muted">{err || 'loading the full dossier…'}</div> : <>
            <div className="verdict" style={{ '--c': vcol } as React.CSSProperties}>
              <div className="vt">{c.verdict ? `Verdict: ${c.verdict === 'ENTRY' ? 'ACCEPTED — entry gate' : 'REJECTED — exit gate'}` : 'Decision in progress'}</div>
              <div>{d.verdict_why}</div>
              {(d.approved_by.length > 0 || d.rejected_by.length > 0) && (
                <div className="who2">
                  <span><b className="up">Approved by</b> {d.approved_by.map((a) => `${a.seat} ${a.confidence}%`).join(' · ') || '—'}</span>
                  <span><b className="dn">Rejected by</b> {d.rejected_by.map((a) => `${a.seat} ${a.confidence}%`).join(' · ') || '—'}</span>
                </div>
              )}
            </div>

            <div className="lv" style={{ gridTemplateColumns: 'repeat(6,1fr)' }}>
              <div><span>Entry</span>{fmtPx(d.levels.entry)}</div>
              <div><span>Stop</span><b className="dn">{fmtPx(d.levels.sl)}</b></div>
              <div><span>Target</span><b className="up">{fmtPx(d.levels.tp)}</b></div>
              <div><span>Risk</span>{d.levels.risk_pct ?? '—'}%</div>
              <div><span>R : R</span>{d.levels.rr.toFixed(2)}</div>
              <div><span>ATR</span>{fmtPx(d.levels.atr)}</div>
            </div>

            <div className="sect" style={{ paddingLeft: 0 }}>Judges — cabin by cabin</div>
            {seats.map((seat, i) => {
              const v = c.votes[i]; const col = seatColor(layout, seat);
              return (
                <div key={seat} className="vr" style={{ '--c': col } as React.CSSProperties}>
                  <div className="vh"><span className="mono dim small">CABIN {i + 1}</span><b style={{ color: col }}>{seat}</b><span className="muted small">{SEAT_ROLE[seat]}</span><span className="grow" />
                    {v ? <><span className={v.vote === 'approve' ? 'up' : 'dn'} style={{ fontWeight: 700 }}>{v.vote === 'approve' ? 'ACCEPTED' : 'REJECTED'}</span>
                      <div className="conf" style={{ maxWidth: 90 }}><i style={{ width: `${v.confidence ?? 50}%`, background: v.vote === 'approve' ? 'var(--up)' : 'var(--dn)' }} /></div><span className="mono small">{v.confidence ?? '—'}%</span></> : <span className="muted small">not reviewed yet</span>}
                  </div>
                  {v && <>
                    <div className="th"><b>Why: </b>{v.thesis || v.reason}</div>
                    {v.reason && v.thesis && !v.thesis.toLowerCase().includes(v.reason.toLowerCase().slice(0, 24)) && <div className="rk"><b>Reasoning · </b>{v.reason}</div>}
                    {v.risk && <div className="rk"><b>Main risk · </b>{v.risk}</div>}
                    <div className="dim small mono">score {v.score.toFixed(2)} · {v.label}{v.ms ? ` · ${(v.ms / 1000).toFixed(1)}s` : ''}</div>
                  </>}
                </div>
              );
            })}
            {c.ceo ? (
              <div className="vr" style={{ '--c': seatColor(layout, 'NAVEED') } as React.CSSProperties}>
                <div className="vh"><span className="mono dim small">EXECUTIVE</span><b style={{ color: seatColor(layout, 'NAVEED') }}>NAVEED · CEO</b><span className="grow" />
                  <span className={c.ceo.vote === 'approve' ? 'up' : 'dn'} style={{ fontWeight: 700 }}>{c.ceo.vote === 'approve' ? 'ACCEPTED' : 'REJECTED'}</span>
                  <div className="conf" style={{ maxWidth: 90 }}><i style={{ width: `${c.ceo.confidence ?? 50}%`, background: c.ceo.vote === 'approve' ? 'var(--up)' : 'var(--dn)' }} /></div><span className="mono small">{c.ceo.confidence ?? '—'}%</span></div>
                <div className="th"><b>Why: </b>{c.ceo.thesis || c.ceo.reason}</div>
                {c.ceo.reason && c.ceo.thesis && !c.ceo.thesis.toLowerCase().includes(c.ceo.reason.toLowerCase().slice(0, 24)) && <div className="rk"><b>Reasoning · </b>{c.ceo.reason}</div>}
                {c.ceo.risk && <div className="rk"><b>Main risk · </b>{c.ceo.risk}</div>}
                <div className="dim small mono">{c.ceo.label}</div>
              </div>
            ) : <div className="muted small" style={{ margin: '6px 0' }}>The CEO only rules on a 3–4 approval split{c.verdict ? ' — this trade did not need him.' : '.'}</div>}

            <div className="sect" style={{ paddingLeft: 0 }}>Outcome</div>
            {d.outcome ? (
              <div className="kvgrid">
                <div><span>Paper result</span><b className={d.outcome.r == null ? '' : d.outcome.r >= 0 ? 'up' : 'dn'}>{d.outcome.r == null ? d.outcome.paper : `${d.outcome.r >= 0 ? '+' : ''}${d.outcome.r.toFixed(2)}R`}</b></div>
                <div><span>How</span>{d.outcome.how}</div>
                <div><span>Filled at</span>{fmtT(d.outcome.t_fill)}</div>
                <div><span>Resolved at</span>{fmtT(d.outcome.t_resolved)}</div>
                <div><span>Was the verdict right?</span>{d.outcome.verdict_was ? <b className={d.outcome.verdict_was === 'correct' ? 'up' : 'dn'}>{d.outcome.verdict_was}</b> : '—'}</div>
                <div><span>Fly dopamine</span>{c.dopamine != null ? c.dopamine.toFixed(2) : '—'}</div>
              </div>
            ) : <div className="muted small">Not evaluated yet — the paper fill window opens after the trade leaves through a gate.</div>}
            {d.outcome && <div className="dim small" style={{ marginTop: 4 }}>{d.outcome.note}</div>}

            <div className="sect" style={{ paddingLeft: 0 }}>Why the hunter found it</div>
            <div className="kvgrid">
              <div><span>Found by</span>{d.found.emitter === 'fly' ? 'DROSOPHILA fly-brain' : d.found.emitter}</div>
              <div><span>Conviction</span>{d.found.conviction.toFixed(2)}</div>
              <div><span>Regime</span>{d.found.regime}</div>
              <div><span>Signalled at</span>{fmtT(d.found.sim_time)} sim</div>
            </div>
            {Object.keys(d.found.info).length > 0 && <div className="muted small" style={{ margin: '6px 0' }}>{Object.entries(d.found.info).map(([k, v]) => `${k}: ${typeof v === 'number' ? +v.toFixed(3) : String(v)}`).join(' · ')}</div>}
            <div className="two">
              <div><div className="dim small" style={{ marginBottom: 3 }}>STRONGEST SENSES</div>
                {d.found.top_senses.map((s) => <div key={s.name} className="mini"><span>{s.name}</span><div className="bias"><u /><i style={{ left: `${50 + (s.v / maxS) * 48}%`, background: s.v >= 0 ? 'var(--up)' : 'var(--dn)' }} /></div><b className="mono">{s.v.toFixed(2)}</b></div>)}</div>
              <div><div className="dim small" style={{ marginBottom: 3 }}>MUSHROOM-BODY OUTPUT</div>
                {d.found.mbon.map((s) => <div key={s.name} className="mini"><span>{s.name}</span><div className="bias"><u /><i style={{ left: `${50 + (s.v / maxM) * 48}%`, background: s.v >= 0 ? 'var(--acc)' : '#64748b' }} /></div><b className="mono">{s.v.toFixed(2)}</b></div>)}</div>
            </div>

            <div className="sect" style={{ paddingLeft: 0 }}>The numbers every judge was shown</div>
            <div className="kvgrid three">{Object.entries(d.facts).map(([k, v]) => <div key={k}><span>{k.replace(/_/g, ' ')}</span>{typeof v === 'number' ? +v.toFixed(4) : String(v)}</div>)}</div>

            <div className="sect" style={{ paddingLeft: 0 }}>Timeline</div>
            <div className="tl">
              {d.timeline.map((x, i) => <div key={i}><span className="mono dim">{fmtT(x.t)}</span>{stageName(x.stage)}</div>)}
            </div>
            <details><summary>Event log ({d.events.length})</summary>
              <div className="tl">{d.events.map((e, i) => <div key={i}><span className="mono dim">{fmtT(e.t)}</span><b className="k">{e.kind}</b> {e.text}</div>)}</div>
            </details>

            <div className="sect" style={{ paddingLeft: 0 }}>MetaTrader 5</div>
            <div className="mt5box">
              {d.mt5 ? <span className="small"><b>{d.mt5.status}</b>{d.mt5.mt5_ticket ? ` · #${d.mt5.mt5_ticket}` : ''}{d.mt5.price ? ` @ ${d.mt5.price}` : ''}{d.mt5.msg ? ` — ${d.mt5.msg}` : ''}</span> : <span className="muted small">not sent</span>}
              <span className="grow" />
              <button className="btn pri sm" disabled={c.cls !== 'forex' || busy || ['queued', 'sent', 'filled'].includes(d.mt5?.status ?? '')} onClick={place}>Place in MT5</button>
            </div>

            <div className="ask" style={{ marginTop: 12 }}>Ask about this trade:
              {['DROSOPHILA', ...seats, 'NAVEED'].map((s) => <button key={s} style={{ '--c': seatColor(layout, s) } as React.CSSProperties} onClick={() => { onAsk(id, s); onClose(); }}>{s.slice(0, 4)}</button>)}
            </div>
          </>}
        </div>
      </div>
    </div>
  );
}
