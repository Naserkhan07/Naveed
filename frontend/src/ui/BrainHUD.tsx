import { useEffect, useRef } from 'react';
import { FlyBrainView, Wiring } from '../scene/FlyBrainView';
import type { FlySnap } from '../types';
import { getJSON } from '../api';
import { Pill } from './common';

const STATE_COL: Record<string, string> = { STRIKE: '#f43f5e', WAIT_FOR_SETUP: '#f59e0b', ROAM: '#38bdf8' };
const STAGE_NAMES: Record<string, string> = { cooldown: 'cooldown', conviction: 'conviction', cost: 'cost', trend: 'trend', rr: 'R:R', corr_risk: 'corr-risk', pipe_cap: 'pipe cap' };

export function BrainHUD({ fly, color, seatName }: { fly: FlySnap | null; color: string; seatName: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<FlyBrainView | null>(null);
  const names = fly?.mbon_names;

  useEffect(() => {
    if (!host.current || !names || view.current) return;
    let dead = false;
    getJSON<Wiring>('/api/fly/wiring').catch(() => null).then((w) => {
      if (dead || !host.current) return;
      view.current = new FlyBrainView(host.current, names, w);
    });
    return () => { dead = true; view.current?.dispose(); view.current = null; };
  }, [!!names]); // eslint-disable-line
  useEffect(() => { view.current?.setColor(color); }, [color, fly]);
  useEffect(() => { if (fly) view.current?.setFocus(fly.focus); }, [fly]);

  const f = fly;
  const maxMb = f ? Math.max(0.001, ...f.focus.mb.map(Math.abs)) : 1;
  const funnel = f?.funnel;
  return (
    <div className="panel brain">
      <div className="ph"><b>DROSOPHILA</b><span className="muted">fly-brain market hunter</span>
        {f && <Pill color={STATE_COL[f.state] ?? '#94a3b8'} solid>{f.state.replace(/_/g, ' ')}</Pill>}</div>
      <div className="conn" ref={host}>
        <div className="lay l1">AL · 29</div><div className="lay l2">PN · 26</div><div className="lay l3">KC · 140</div><div className="lay l4">MBON · 8</div>
        <div className="thinking"><i style={{ background: color }} />{seatName}</div>
      </div>
      {f ? (
        <div className="hud-body">
          <div className="row"><span>focus</span><b>{f.focus.s.replace('_', ' ')}</b><span className="muted">hunger {f.focus.hunger.toFixed(2)} · thr {f.threshold.toFixed(2)}</span></div>
          <div className="bar"><div className="fill" style={{ width: `${Math.min(100, f.focus.hunger * 100)}%`, background: f.focus.hunger > f.threshold ? '#f43f5e' : '#38bdf8' }} /><div className="mark" style={{ left: `${Math.min(100, f.threshold * 100)}%` }} /></div>
          <div className="row"><span>dopamine</span><b style={{ color: f.dopamine >= 0 ? '#34d399' : '#f87171' }}>{f.dopamine.toFixed(2)}</b>
            <span className="muted">baseline {f.baseline.toFixed(2)} · {f.updates} updates · fatigue {f.fatigue.toFixed(2)}</span></div>
          <div className="dop"><div className="mid" /><div className="dv" style={{ left: `${50 + (Math.max(-1.5, Math.min(1.5, f.dopamine)) / 1.5) * 50}%`, background: f.dopamine >= 0 ? '#34d399' : '#f87171' }} /></div>
          <div className="mbs">
            {f.mbon_names.map((n, i) => (
              <div key={n} className="mb"><div className="mbb"><div style={{ height: `${Math.max(3, (Math.abs(f.focus.mb[i]) / maxMb) * 100)}%`, background: f.focus.mb[i] >= 0 ? color : '#64748b' }} /></div><span>{n.slice(0, 4)}</span></div>
            ))}
          </div>
          <details open>
            <summary>scan funnel · {funnel?.scans} scans</summary>
            <table className="funnel"><tbody>
              {funnel && Object.entries(funnel.stages).map(([k, v]) => (
                <tr key={k}><td>{STAGE_NAMES[k] ?? k}</td><td className="n">{v.in}</td>
                  <td><div className="bar sm"><div className="fill" style={{ width: `${v.in ? (v.out / v.in) * 100 : 0}%`, background: '#38bdf8' }} /></div></td><td className="n">{v.out}</td></tr>
              ))}
            </tbody></table>
            <div className="muted small">emitted {Object.entries(funnel?.emitted ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}</div>
          </details>
          <div className="muted small">
            corr table {f.correlation.fresh ? 'fresh' : 'STALE'} ({f.correlation.age_s.toFixed(0)}s) · {f.correlation.n_strong} pairs |ρ|≥0.90 · blocked band {funnel?.corr_band_blocked ?? 0} / stale {funnel?.corr_stale_blocked ?? 0}<br />
            depth feed {f.microstructure.reachable ? 'reachable' : 'unreachable → trade-only estimators'} ({f.microstructure.polls} polls)
          </div>
        </div>
      ) : <div className="hud-body muted">waiting for the brain…</div>}
    </div>
  );
}
