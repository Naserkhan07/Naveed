import type { Extra, Frame, Theme } from '../types';

interface Props {
  theme: Theme; speed: number; connected: boolean; sideOpen: boolean; extra: Extra | null; frame: Frame | null;
  onTheme: () => void; onSpeed: (s: number) => void; onSide: () => void; onSettings: () => void;
}
const fmtT = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function TopBar(p: Props) {
  const st = p.extra?.stats ?? {};
  const live = !!p.extra?.mode?.startsWith('LIVE');
  const wr = st.winrate as number | null | undefined;
  const R = (st.sumR ?? 0) as number;
  const K = ({ l, v, c }: { l: string; v: React.ReactNode; c?: string }) => <div className="kpi"><span>{l}</span><b className={c}>{v}</b></div>;
  return (
    <header className="topbar">
      <div className="brand"><div className="logo">S</div><b>SOUL EXTER</b><span className="sub">autonomous trading floor</span></div>
      <div className="kpis">
        <K l="Data" v={live ? 'LIVE' : 'SYNTH'} c={live ? 'live' : 'syn'} />
        <K l="Sim time" v={p.frame ? fmtT(p.frame.sim) : '—'} />
        <K l="In pipe" v={`${st.in_pipe ?? 0}/9`} />
        <K l="Entry / Exit" v={`${st.entry ?? 0} / ${st.exit ?? 0}`} />
        <K l="Paper W/L" v={`${st.wins ?? 0}/${st.losses ?? 0}`} />
        <K l="Win rate" v={wr != null ? `${(wr * 100).toFixed(0)}%` : '—'} />
        <K l="Σ R" v={`${R >= 0 ? '+' : ''}${R.toFixed(1)}`} c={R >= 0 ? 'up' : 'dn'} />
        <K l="MT5" v={p.extra?.mt5?.connected ? (p.extra.mt5.auto ? 'AUTO' : 'READY') : 'OFF'} c={p.extra?.mt5?.connected ? 'live' : ''} />
      </div>
      <div className="tb-right">
        <label className="muted small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>Speed
          <select className="sel" value={String(p.speed)} onChange={(e) => p.onSpeed(parseFloat(e.target.value))}>
            {[0.25, 0.5, 1, 2, 4, 8, 16, 32].map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
        <button className="btn" onClick={p.onTheme} title="Day / Night (N)" style={{ minWidth: 88, fontWeight: 700, letterSpacing: '.05em' }}>{p.theme === 'night' ? '☾ NIGHT' : '☀ DAY'}</button>
        <button className={'btn' + (p.sideOpen ? ' on' : '')} onClick={p.onSide} title="Toggle panel ( \ )">☰ Panel</button>
        <button className="btn ic" onClick={p.onSettings} title="Settings">⚙</button>
        <span className={'dot ' + (p.connected ? 'ok' : 'bad')} title={p.connected ? 'stream connected' : 'reconnecting…'} />
      </div>
    </header>
  );
}
