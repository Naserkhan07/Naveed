import { useState } from 'react';
import { postJSON } from '../api';

interface Diag {
  providers: { name: string; ok: boolean; ms: number; error?: string; reply?: string }[];
  hosted_keys: string[]; internet: boolean; verdict: string;
}

/** One-click check of every language-model path the backend can use, with the exact error for each. */
export function Diagnose({ compact = false }: { compact?: boolean }) {
  const [d, setD] = useState<Diag | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  async function run() {
    setBusy(true); setErr('');
    try { setD(await postJSON<Diag>('/api/llm/diagnose', {})); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  }
  return (
    <div className="diag">
      <button className="btn sm" onClick={run} disabled={busy}>{busy ? 'checking…' : 'Check LLM connection'}</button>
      {err && <div className="small" style={{ color: 'var(--dn)' }}>{err}</div>}
      {d && (
        <div className="small">
          <div style={{ margin: '6px 0' }}>{d.verdict}</div>
          {!compact && d.providers.map((p) => (
            <div key={p.name} className="mono" style={{ color: p.ok ? 'var(--up)' : 'var(--mut)' }}>
              {p.ok ? '✓' : '✗'} {p.name} · {p.ms} ms{p.error ? ` · ${p.error}` : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
