import type { Extra, Frame } from '../types';

export function Footer({ extra, frame }: { extra: Extra | null; frame: Frame | null }) {
  const st = extra?.stats ?? {};
  const ev = extra?.events?.[0];
  const live = extra?.mode?.startsWith('LIVE');
  return (
    <footer className="footer">
      <span className={'mode ' + (live ? 'live' : '')}>● {extra?.mode ?? 'connecting…'}</span>
      <span>sim {frame ? fmtT(frame.sim) : '—'}</span>
      {Object.entries({ tickets: st.tickets, entry: st.entry, exit: st.exit, 'CEO rulings': st.ceo_rulings, unanimous: st.unanimous, 'in pipe': st.in_pipe }).filter(([, v]) => v != null).map(([k, v]) => <span key={k}>{k} <b>{v}</b></span>)}
      {st.wins != null && <span>paper W/L <b>{st.wins}/{st.losses}</b> · ΣR <b>{(st.sumR ?? 0).toFixed(1)}</b></span>}
      <span className="grow" />
      {ev && <span className="ev">▸ {ev.text}</span>}
    </footer>
  );
}
const fmtT = (s: number) => `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m ${String(Math.floor(s % 60)).padStart(2, '0')}s`;
