import { useEffect, useState } from 'react';
import { getJSON, postJSON } from '../api';

export interface SettingsT { speed: number; live: boolean; llm: boolean; free_gpt: boolean; ambient: number; ceo_doctrine: boolean; theme: string; seed: number }

export function Settings({ onClose, onChanged }: { onClose: () => void; onChanged: (s: SettingsT) => void }) {
  const [s, setS] = useState<SettingsT | null>(null);
  useEffect(() => { getJSON<SettingsT>('/api/settings').then(setS).catch(() => {}); }, []);
  async function set(patch: Partial<SettingsT>) {
    if (!s) return;
    const n = { ...s, ...patch }; setS(n);
    const r = await postJSON<SettingsT>('/api/settings', patch); setS(r); onChanged(r);
  }
  const Tog = ({ k, label, hint }: { k: 'live' | 'llm' | 'free_gpt' | 'ceo_doctrine'; label: string; hint: string }) => (
    <label className="set-row"><div><b>{label}</b><div className="muted small">{hint}</div></div>
      <input type="checkbox" checked={!!s?.[k]} onChange={(e) => set({ [k]: e.target.checked })} /></label>
  );
  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ph"><b>Settings</b><span className="grow" /><button onClick={onClose}>✕</button></div>
        {!s ? <div className="pad muted">loading…</div> : (
          <div className="pad">
            <label className="set-row"><div><b>Simulation speed</b><div className="muted small">{s.speed}× (0.25 – 32)</div></div>
              <input type="range" min={0.25} max={32} step={0.25} value={s.speed} onChange={(e) => set({ speed: parseFloat(e.target.value) })} /></label>
            <label className="set-row"><div><b>Ambient people</b><div className="muted small">{s.ambient} background traders (0 – 24)</div></div>
              <input type="range" min={0} max={24} step={1} value={s.ambient} onChange={(e) => set({ ambient: parseInt(e.target.value) })} /></label>
            <Tog k="live" label="Live market data" hint="merge keyless Binance / Yahoo bars into the synthetic tape (needs network)" />
            <Tog k="llm" label="LLM judges" hint="off = every judge reasons offline from the numbers" />
            <Tog k="free_gpt" label="Free GPT (Pollinations)" hint="keyless default; then env-key providers; then offline reasoning" />
            <Tog k="ceo_doctrine" label="CEO doctrine" hint="every ~4 sim-minutes NAVEED writes a short doctrine note from the results" />
            <div className="muted small">Speed, judges and providers take effect immediately. Seed {s.seed} applies at the next server start.</div>
          </div>
        )}
      </div>
    </div>
  );
}
