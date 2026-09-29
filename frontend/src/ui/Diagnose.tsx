import { useState } from 'react';
import { postJSON } from '../api';
import { askBrowser } from '../llm';

interface Diag { providers: { name: string; ok: boolean; ms: number; error?: string }[]; internet: boolean; verdict: string }

/** One-click check of both paths a desk can use: the server's and this browser's. */
export function Diagnose() {
  const [d, setD] = useState<Diag | null>(null);
  const [br, setBr] = useState<{ ok: boolean; msg: string; ms: number } | null>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true); setD(null); setBr(null);
    const t0 = performance.now();
    const b = askBrowser([{ role: 'user', content: 'Reply with the single word: ready' }])
      .then((r) => setBr({ ok: true, msg: r.label, ms: Math.round(performance.now() - t0) }))
      .catch((e) => setBr({ ok: false, msg: (e as Error).message, ms: Math.round(performance.now() - t0) }));
    const s = postJSON<Diag>('/api/llm/diagnose', {}).then(setD).catch(() => {});
    await Promise.all([b, s]);
    setBusy(false);
  }
  return (
    <div className="diag">
      <button className="btn sm" onClick={run} disabled={busy}>{busy ? 'checking…' : 'Check LLM connection'}</button>
      {(d || br) && (
        <div className="small" style={{ marginTop: 6 }}>
          {br && <div className="mono" style={{ color: br.ok ? 'var(--up)' : 'var(--dn)' }}>{br.ok ? '✓' : '✗'} your browser · {br.ms} ms · {br.msg}</div>}
          {d?.providers.map((p) => (
            <div key={p.name} className="mono" style={{ color: p.ok ? 'var(--up)' : 'var(--mut)' }}>{p.ok ? '✓' : '✗'} server → {p.name} · {p.ms} ms{p.error ? ` · ${p.error}` : ''}</div>
          ))}
          {d && <div style={{ marginTop: 6 }}>{d.verdict}</div>}
        </div>
      )}
    </div>
  );
}
