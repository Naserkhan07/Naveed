import type { Extra } from '../types';

export function Footer({ extra }: { extra: Extra | null }) {
  const ev = extra?.events?.[extra.events.length - 1];
  const llm = extra?.llm;
  return (
    <footer className="footer">
      <span>LLM <b>{llm ? (llm.enabled ? llm.label : 'off (offline reasoning)') : '—'}</b></span>
      {llm && <span>calls free <b>{llm.stats.free}</b> · hosted <b>{llm.stats.hosted}</b> · offline <b>{llm.stats.offline}</b></span>}
      <span className="grow" />
      {ev && <span className="ev"><span className="k">{ev.kind}</span> {ev.text}</span>}
    </footer>
  );
}
