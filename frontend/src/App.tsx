import { useCallback, useEffect, useRef, useState } from 'react';
import { HallScene } from './scene/HallScene';
import { fetchLayout, getJSON, postJSON, useFloorStream } from './api';
import type { Frame, Layout, Theme } from './types';
import { TopBar } from './ui/TopBar';
import { BrainHUD } from './ui/BrainHUD';
import { Orders } from './ui/Orders';
import { Council } from './ui/Council';
import { Dossier } from './ui/Dossier';
import { AssetCard } from './ui/AssetCard';
import { ALL, ChatDock } from './ui/ChatDock';
import { Settings, SettingsT } from './ui/Settings';
import { Footer } from './ui/Footer';

export function App() {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<HallScene | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>('night');
  const [preset, setPreset] = useState<string | null>('overview');
  const [freefly, setFreefly] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [tab, setTab] = useState<'orders' | 'chat' | 'council' | 'brain'>('orders');
  const [sideOpen, setSideOpen] = useState(true);
  const [dossier, setDossier] = useState<string | null>(null);
  const [asset, setAsset] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [chatTarget, setChatTarget] = useState('ATLAS');
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [thinking, setThinking] = useState({ seat: 'DROSOPHILA', color: '#34d399' });

  const lastFrameUI = useRef(0);
  const onFrame = useCallback((f: Frame) => {
    scene.current?.setFrame(f);
    if (f.extra) scene.current?.setExtra(f.extra);
    const now = performance.now();
    if (now - lastFrameUI.current > 500) {
      lastFrameUI.current = now;
      setFrame(f);
      setThinking((p) => (p.seat === f.thinking.seat ? p : f.thinking));
    }
  }, []);
  const { extra, connected } = useFloorStream(onFrame);

  useEffect(() => { fetchLayout().then(setLayout).catch((e) => setErr(String(e))); }, []);
  useEffect(() => {
    getJSON<SettingsT>('/api/settings').then((s) => { setSpeed(s.speed); if (s.theme === 'day' || s.theme === 'night') setTheme(s.theme); }).catch(() => {});
  }, []);

  // 3D scene lifecycle
  useEffect(() => {
    if (!layout || !host.current) return;
    const s = new HallScene(host.current, layout, 'night');
    scene.current = s;
    s.onPickSeat = (seat) => { setChatTarget(seat); setTradeId(null); setTab('chat'); setSideOpen(true); };
    s.onPickTicket = (id) => { setSelected(id); setDossier(id); };
    s.onPickNpc = (sym) => { if (sym) setAsset(sym); };
    (window as unknown as { __hall: HallScene }).__hall = s;
    return () => { s.dispose(); scene.current = null; };
  }, [layout]);
  useEffect(() => { scene.current?.setTheme(theme); }, [theme, layout]);
  useEffect(() => { scene.current?.select(selected); }, [selected]);

  const goPreset = (p: string) => { scene.current?.goPreset(p); setPreset(p); setFreefly(false); };
  const toggleFly = useCallback(() => {
    const s = scene.current; if (!s) return;
    const on = !s.rig.freefly; s.rig.setFreeFly(on); setFreefly(on); if (on) setPreset(null);
  }, []);
  const toggleTheme = useCallback(() => {
    setTheme((t) => { const n = t === 'night' ? 'day' : 'night'; postJSON('/api/settings', { theme: n }).catch(() => {}); return n; });
  }, []);
  const changeSpeed = (v: number) => { setSpeed(v); postJSON('/api/settings', { speed: v }).catch(() => {}); };

  // keyboard shortcuts (ignored while typing)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
      if (e.key === 'f' || e.key === 'F') toggleFly();
      else if (e.key === 'n' || e.key === 'N') toggleTheme();
      else if (e.key === '\\') setSideOpen((v) => !v);
      else if (e.key === 'Escape' && scene.current?.rig.freefly) toggleFly();
      else if (!scene.current?.rig.freefly && /^[1-8]$/.test(e.key) && layout) goPreset(['overview', 'pit', 'corridor', 'cabins', 'executive', 'debate', 'gates', 'tape'][+e.key - 1]);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [layout, toggleFly, toggleTheme]);

  const fly = extra?.fly ?? null;
  const active = (extra?.orders ?? []).filter((o) => !o.verdict).length;
  const PRESETS: [string, string][] = [['overview', 'Overview'], ['pit', 'Pit'], ['corridor', 'Corridor'], ['cabins', 'Cabins'], ['executive', 'Executive'], ['debate', 'Debate'], ['gates', 'Gates'], ['tape', 'Tape']];

  return (
    <div className={'app ' + theme}>
      <TopBar theme={theme} speed={speed} connected={connected} sideOpen={sideOpen} extra={extra} frame={frame}
        onTheme={toggleTheme} onSpeed={changeSpeed} onSide={() => setSideOpen((v) => !v)} onSettings={() => setShowSettings(true)} />
      <div className="stage">
        <div className="viewport">
          <div className="canvas" ref={host} />
          {!layout && <div className="loading">{err ? `Cannot reach the floor engine: ${err}` : 'Loading the trading floor…'}</div>}
          <div className="vbar">
            {PRESETS.map(([k, n], i) => <button key={k} className={'chipbtn' + (!freefly && preset === k ? ' on' : '')} onClick={() => goPreset(k)} title={`View ${i + 1}`}>{n}</button>)}
            <button className={'chipbtn' + (freefly ? ' on' : '')} onClick={toggleFly} title="Free-fly viewer (F)">⌖ 360° fly</button>
          </div>
          {freefly && <div className="hint"><b>Free-fly</b> · drag = look · W A S D = move · Q / E = down / up · Shift = fast · wheel = speed · Esc = exit</div>}
          {!freefly && <div className="vtag"><i />click any person — traders open their full dossier, judges open their chat · keys 1–8 views</div>}
        </div>
        <aside className={'side' + (sideOpen ? '' : ' closed')}>
          <div className="tabs">
            <button className={tab === 'orders' ? 'on' : ''} onClick={() => setTab('orders')}>Orders{active > 0 && <span className="badge">{active}</span>}</button>
            <button className={tab === 'chat' ? 'on' : ''} onClick={() => setTab('chat')}>Desks</button>
            <button className={tab === 'council' ? 'on' : ''} onClick={() => setTab('council')}>Council</button>
            <button className={tab === 'brain' ? 'on' : ''} onClick={() => setTab('brain')}>Brain</button>
          </div>
          {tab === 'orders' && <Orders orders={extra?.orders ?? []} layout={layout} selected={selected} onSelect={(id) => setSelected(id)} onDossier={setDossier}
            onAsk={(id, seat) => { setTradeId(id); setChatTarget(seat); setTab('chat'); }} />}
          {tab === 'chat' && <div className="pane"><ChatDock layout={layout} extra={extra} target={chatTarget} tradeId={tradeId}
            onTarget={(t) => { setChatTarget(t); if (t === ALL) setTradeId(null); }} onClearTrade={() => setTradeId(null)} /></div>}
          {tab === 'council' && <Council extra={extra} layout={layout} onChat={(seat) => { setChatTarget(seat); setTradeId(null); setTab('chat'); }} />}
          {tab === 'brain' && <div className="pane"><BrainHUD fly={fly} color={thinking.color} seatName={thinking.seat} /></div>}
        </aside>
      </div>
      <Footer extra={extra} />
      {dossier && <Dossier id={dossier} layout={layout} onClose={() => setDossier(null)} onAsk={(id, seat) => { setTradeId(id); setChatTarget(seat); setTab('chat'); setSideOpen(true); }} />}
      {asset && !dossier && <AssetCard sym={asset} extra={extra} onClose={() => setAsset(null)} onOpenTrade={(id) => { setAsset(null); setDossier(id); }} />}
      {showSettings && <Settings layout={layout} onClose={() => setShowSettings(false)} onChanged={(s) => setSpeed(s.speed)} />}
    </div>
  );
}
