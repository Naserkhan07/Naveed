import type { Extra } from '../types';
import type { RelayStat } from '../relay';

export function Footer({ extra, relay }: { extra: Extra | null; relay?: RelayStat }) {
  const ev = extra?.events?.[extra.events.length - 1];
  const llm = extra?.llm;
  return (
    <footer className="footer">
      <span>LLM <b>{llm ? (llm.enabled ? llm.label : 'off') : '—'}</b></span>
      {llm && <span>server calls: free <b>{llm.stats.free}</b> · own endpoint <b>{llm.stats.own}</b> · unreachable <b>{llm.stats.failed}</b></span>}
      {llm && (llm.stats.relay ?? 0) + (relay?.served ?? 0) > 0 && <span>via your browser <b>{llm.relay?.done ?? 0}</b></span>}
      {llm && llm.waiting > 0 && <span className="waitllm">⏳ {llm.waiting} verdict{llm.waiting > 1 ? 's' : ''} waiting for a language model{(relay?.last_error || llm.relay?.last_error) ? ` — ${relay?.last_error || llm.relay?.last_error}` : ' — this page relays them from your browser'}</span>}
      <span className="grow" />
      {ev && <span className="ev"><span className="k">{ev.kind}</span> {ev.text}</span>}
    </footer>
  );
}
