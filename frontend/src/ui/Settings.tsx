import { useEffect, useState } from 'react';
import { getJSON, postJSON } from '../api';
import { SEAT_ORDER, seatColor } from './common';
import type { Layout } from '../types';

export interface SettingsT {
  speed: number; live: boolean; llm: boolean; free_gpt: boolean; ambient: number; ceo_doctrine: boolean; theme: string; seed: number;
  markets: Record<string, boolean>; off: string[]; mt5_auto: boolean; mt5_lots: number; mt5_allow_synth: boolean;
}
interface Uni { markets: Record<string, boolean>; classes: Record<string, { sym: string; name: string; on: boolean }[]>; enabled: number; total: number }
interface SeatCfg { provider: string; base_url: string; model: string; api_key: string; has_key: boolean; default_model: string; role: string; stats: { ok: number; err: number; ms: number; last_error: string } }
interface LlmCfg { seats: Record<string, SeatCfg>; presets: Record<string, { base_url: string; note: string }> }
interface Mt5S { bridge: { connected: boolean; age_s: number | null; account: { login?: number; server?: string; demo?: boolean; balance?: number; equity?: number; currency?: string } | null }; counts: Record<string, number>; recent: { id: string; symbol: string; side: string; lots: number; status: string; msg: string; mt5_ticket: number | null; price: number | null }[]; server: string }

type Tab = 'general' | 'markets' | 'llm' | 'mt5';

export function Settings({ onClose, onChanged, layout }: { onClose: () => void; onChanged: (s: SettingsT) => void; layout: Layout | null }) {
  const [tab, setTab] = useState<Tab>('general');
  const [s, setS] = useState<SettingsT | null>(null);
  useEffect(() => { getJSON<SettingsT>('/api/settings').then(setS).catch(() => {}); }, []);
  async function set(patch: Partial<SettingsT>) {
    if (!s) return;
    setS({ ...s, ...patch });
    const r = await postJSON<SettingsT>('/api/settings', patch); setS(r); onChanged(r);
  }
  return (
    <div className="modal" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="ph"><b>Settings</b><span className="grow" /><button className="btn sm" onClick={onClose}>Close ✕</button></div>
        <div className="tabs">
          {([['general', 'General'], ['markets', 'Markets & symbols'], ['llm', 'LLM seats'], ['mt5', 'MetaTrader 5']] as [Tab, string][]).map(([k, n]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}</button>)}
        </div>
        <div className="dbody">
          {!s ? <div className="pad muted">loading…</div> : tab === 'general' ? <General s={s} set={set} /> : tab === 'markets' ? <Markets /> : tab === 'llm' ? <Llm layout={layout} /> : <Mt5 s={s} set={set} />}
        </div>
      </div>
    </div>
  );
}

function Row({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return <label className="set-row"><div><b>{title}</b>{hint && <div className="muted small">{hint}</div>}</div>{children}</label>;
}

function General({ s, set }: { s: SettingsT; set: (p: Partial<SettingsT>) => void }) {
  const Tog = ({ k, title, hint }: { k: 'live' | 'llm' | 'free_gpt' | 'ceo_doctrine'; title: string; hint: string }) => (
    <Row title={title} hint={hint}><input type="checkbox" checked={!!s[k]} onChange={(e) => set({ [k]: e.target.checked })} /></Row>
  );
  return (
    <>
      <Row title="Simulation speed" hint={`${s.speed}× (0.25 – 32). Live-price checks need ≤ 1.5×`}><input type="range" min={0.25} max={32} step={0.25} value={s.speed} onChange={(e) => set({ speed: parseFloat(e.target.value) })} /></Row>
      <Row title="Ambient people" hint={`${s.ambient} background traders, labelled with the assets the fly-brain is hunting`}><input type="range" min={0} max={24} step={1} value={s.ambient} onChange={(e) => set({ ambient: parseInt(e.target.value) })} /></Row>
      <Tog k="live" title="Live market data" hint="merge keyless Binance / Yahoo bars into the tape (needs network)" />
      <Tog k="llm" title="LLM judges" hint="off = every judge reasons offline from the numbers" />
      <Tog k="free_gpt" title="Free GPT (Pollinations)" hint="keyless default for seats without their own endpoint; then env-key providers; then offline reasoning" />
      <Tog k="ceo_doctrine" title="CEO doctrine" hint="every ~4 sim-minutes NAVEED writes a short doctrine note from the results" />
      <div className="muted small" style={{ paddingTop: 10 }}>Settings persist on the server. Seed {s.seed} applies at the next server start.</div>
    </>
  );
}

function Markets() {
  const [u, setU] = useState<Uni | null>(null);
  const [q, setQ] = useState('');
  const load = () => getJSON<Uni>('/api/universe').then(setU).catch(() => {});
  useEffect(() => { load(); }, []);
  async function patch(p: Partial<SettingsT>) { await postJSON('/api/settings', p); await load(); }
  if (!u) return <div className="pad muted">loading…</div>;
  const off = new Set(Object.values(u.classes).flat().filter((x) => !x.on).map((x) => x.sym));
  const toggleSym = (sym: string) => { off.has(sym) ? off.delete(sym) : off.add(sym); patch({ off: [...off] }); };
  return (
    <>
      <div className="note-box">The fly-brain only hunts what is enabled here. <b>{u.enabled}</b> of <b>{u.total}</b> symbols are live. Disabled assets get zero hunger and are skipped by the correlation finders.</div>
      <div className="grid2">
        {Object.entries(u.classes).map(([c, list]) => (
          <div key={c} className={'mk' + (u.markets[c] ? '' : ' off')} onClick={() => patch({ markets: { [c]: !u.markets[c] } })}>
            <input type="checkbox" readOnly checked={!!u.markets[c]} /><div><b>{c}</b><div className="muted small">{list.filter((x) => x.on).length}/{list.length} symbols</div></div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12 }}><input className="field" placeholder="Filter symbols…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      {Object.entries(u.classes).map(([c, list]) => {
        const f = list.filter((x) => !q || x.sym.toLowerCase().includes(q.toLowerCase()) || x.name.toLowerCase().includes(q.toLowerCase()));
        if (!f.length) return null;
        return (
          <div key={c} style={{ opacity: u.markets[c] ? 1 : 0.4 }}>
            <div className="sect" style={{ paddingLeft: 0, display: 'flex', gap: 8 }}>{c}
              <span className="grow" /><a style={{ cursor: 'pointer', color: 'var(--acc)' }} onClick={() => { list.forEach((x) => off.delete(x.sym)); patch({ off: [...off] }); }}>all</a>
              <a style={{ cursor: 'pointer', color: 'var(--acc)' }} onClick={() => { list.forEach((x) => off.add(x.sym)); patch({ off: [...off] }); }}>none</a></div>
            <div className="syms">{f.map((x) => <span key={x.sym} title={x.name} className={'symchip' + (x.on ? ' on' : '')} onClick={() => toggleSym(x.sym)}>{x.sym}</span>)}</div>
          </div>
        );
      })}
    </>
  );
}

function Llm({ layout }: { layout: Layout | null }) {
  const [cfg, setCfg] = useState<LlmCfg | null>(null);
  const [reveal, setReveal] = useState(false);
  const [test, setTest] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState<Record<string, Partial<SeatCfg>>>({});
  const load = (r = false) => getJSON<LlmCfg>('/api/llm/config' + (r ? '?reveal=1' : '')).then(setCfg).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!cfg) return <div className="pad muted">loading…</div>;
  const val = (seat: string, k: keyof SeatCfg) => (dirty[seat]?.[k] ?? cfg.seats[seat][k]) as string;
  const edit = (seat: string, k: keyof SeatCfg, v: string) => setDirty((d) => ({ ...d, [seat]: { ...d[seat], [k]: v } }));
  async function save(seat?: string) {
    const body = seat ? { [seat]: dirty[seat] ?? {} } : dirty;
    await postJSON('/api/llm/config', { seats: body }); setDirty(seat ? (d) => { const n = { ...d }; delete n[seat]; return n; } : {}); await load(reveal);
  }
  async function runTest(seat: string) {
    if (dirty[seat]) await save(seat);
    setTest((t) => ({ ...t, [seat]: 'testing…' }));
    try {
      const r = await postJSON<{ ok: boolean; label?: string; reply?: string; error?: string; ms: number }>(`/api/llm/test/${seat}`, {});
      setTest((t) => ({ ...t, [seat]: r.ok ? `✓ ${r.label} · ${r.ms} ms · “${r.reply}”` : `✗ ${r.error}` }));
    } catch (e) { setTest((t) => ({ ...t, [seat]: `✗ ${(e as Error).message}` })); }
  }
  function applyAll(provider: string) {
    const p = cfg!.presets[provider];
    SEAT_ORDER.forEach((s) => { edit(s, 'provider', provider); edit(s, 'base_url', p?.base_url ?? ''); });
  }
  return (
    <>
      <div className="note-box">Every seat can use its <b>own model and endpoint</b>. Use <b>auto</b> for the free keyless GPT (default). For open-source models on a Kaggle GPU, choose <b>ollama</b> (<span className="mono">http://127.0.0.1:11434/v1</span>) — or any OpenAI-compatible URL (OpenRouter, Groq, Together, HF, vLLM). Keys are stored on the server only and are masked unless you reveal them.</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="muted small">Apply to all seats:</span>
        {Object.keys(cfg.presets).map((p) => <button key={p} className="btn sm" title={cfg.presets[p].note} onClick={() => applyAll(p)}>{p}</button>)}
        <span className="grow" />
        <button className={'btn sm' + (reveal ? ' on' : '')} onClick={() => { setReveal(!reveal); load(!reveal); }}>{reveal ? 'Hide keys' : 'Reveal keys'}</button>
        <button className="btn pri sm" onClick={() => save()}>Save all</button>
      </div>
      {SEAT_ORDER.map((seat) => {
        const c = cfg.seats[seat]; if (!c) return null;
        const col = seatColor(layout, seat);
        return (
          <div key={seat} className="seatrow" style={{ '--c': col } as React.CSSProperties}>
            <div><b style={{ color: col }}>{seat}</b><div className="muted small">{c.role}</div></div>
            <select className="field" value={val(seat, 'provider')} onChange={(e) => { edit(seat, 'provider', e.target.value); const b = cfg.presets[e.target.value]?.base_url; if (b !== undefined) edit(seat, 'base_url', b); }}>
              {Object.keys(cfg.presets).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <input className="field" placeholder={c.default_model || 'model name'} value={val(seat, 'model')} onChange={(e) => edit(seat, 'model', e.target.value)} />
            <div className="full">
              <input className="field" placeholder="base URL (OpenAI-compatible /v1)" value={val(seat, 'base_url')} onChange={(e) => edit(seat, 'base_url', e.target.value)} />
              <input className="field" type={reveal ? 'text' : 'password'} placeholder="API key (optional)" value={val(seat, 'api_key')} onChange={(e) => edit(seat, 'api_key', e.target.value)} style={{ maxWidth: 190 }} />
              <button className="btn sm" onClick={() => runTest(seat)}>Test</button>
            </div>
            {(test[seat] || c.stats.last_error) && <div className="full small" style={{ color: test[seat]?.startsWith('✓') ? 'var(--up)' : 'var(--mut)' }}>{test[seat] ?? `last error: ${c.stats.last_error}`}</div>}
          </div>
        );
      })}
    </>
  );
}

function Mt5({ s, set }: { s: SettingsT; set: (p: Partial<SettingsT>) => void }) {
  const [st, setSt] = useState<Mt5S | null>(null);
  const [tok, setTok] = useState('');
  useEffect(() => {
    const go = () => getJSON<Mt5S>('/api/mt5/status').then(setSt).catch(() => {});
    go(); const id = window.setInterval(go, 3000);
    getJSON<{ token: string }>('/api/mt5/token').then((r) => setTok(r.token)).catch(() => {});
    return () => clearInterval(id);
  }, []);
  const b = st?.bridge;
  const url = location.origin;
  return (
    <>
      <div className="note-box">MetaTrader 5's Python API only runs on <b>Windows next to the terminal</b>, so the trading floor never logs in to your account. Instead a small <b>bridge script</b> on your PC polls this server and places the orders. <b>Your MT5 password is only ever typed into the bridge's environment — never into this app.</b> Only forex symbols are routed. Use a <b>demo</b> account first.</div>
      <div className="set-row"><div><b>Bridge status</b><div className="muted small">{b?.connected ? `connected · last seen ${b.age_s}s ago` : 'not connected — start the bridge script below'}</div></div>
        <span className={'pill solid'} style={{ '--c': b?.connected ? '#2fc68a' : '#8492a8' } as React.CSSProperties}>{b?.connected ? 'ONLINE' : 'OFFLINE'}</span></div>
      {b?.account && <div className="set-row"><div><b>Account</b><div className="muted small">{b.account.server} · #{b.account.login} · {b.account.demo ? 'DEMO' : 'REAL'}</div></div><span className="mono">{b.account.balance?.toFixed(2)} {b.account.currency} · eq {b.account.equity?.toFixed(2)}</span></div>}
      <Row title="Auto-send every ENTRY verdict" hint="when a ticket is approved for entry, queue a market order automatically"><input type="checkbox" checked={s.mt5_auto} onChange={(e) => set({ mt5_auto: e.target.checked })} /></Row>
      <Row title="Lot size" hint="volume per order"><input className="field" style={{ width: 90 }} type="number" min={0.01} step={0.01} value={s.mt5_lots} onChange={(e) => set({ mt5_lots: Math.max(0.01, parseFloat(e.target.value) || 0.01) })} /></Row>
      <Row title="Allow signals from synthetic prices (test only)" hint="by default only tickets built on LIVE prices are sent; SL/TP distances are re-applied to the MT5 tick"><input type="checkbox" checked={s.mt5_allow_synth} onChange={(e) => set({ mt5_allow_synth: e.target.checked })} /></Row>
      <div className="sect" style={{ paddingLeft: 0 }}>Run the bridge on your Windows PC</div>
      <div className="code">{`pip install MetaTrader5
set SOUL_URL=${url}
set MT5_BRIDGE_TOKEN=${tok || '…'}
set MT5_LOGIN=<your login>
set MT5_PASSWORD=<your password>
set MT5_SERVER=${st?.server ?? 'MetaQuotes-Demo'}
python backend\\bridge\\mt5_bridge.py`}</div>
      <div className="sect" style={{ paddingLeft: 0 }}>Recent orders {st && <span className="dim">({Object.entries(st.counts).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none yet'})</span>}</div>
      {(st?.recent ?? []).map((o) => (
        <div key={o.id} className="set-row" style={{ padding: '6px 0' }}>
          <div><b className="mono">{o.id}</b> {o.symbol} {o.side} {o.lots}<div className="muted small">{o.msg}</div></div>
          <span className="pill solid" style={{ '--c': o.status === 'filled' ? '#2fc68a' : o.status === 'error' ? '#f0616d' : '#f5b73b' } as React.CSSProperties}>{o.status}{o.mt5_ticket ? ` #${o.mt5_ticket}` : ''}</span>
        </div>
      ))}
    </>
  );
}
