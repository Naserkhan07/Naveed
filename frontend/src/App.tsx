import { useCallback, useEffect, useRef, useState } from 'react';
import { HallScene } from './scene/HallScene';
import { fetchLayout, getJSON, postJSON, useFloorStream } from './api';
import type { Frame, Layout, Theme } from './types';
import { TopBar } from './ui/TopBar';
import { BrainHUD } from './ui/BrainHUD';
import { Orders } from './ui/Orders';
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
  const [panels, setPanels] = useState({ brain: true, orders: true, chat: true });
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
    s.onPickSeat = (seat) => { setChatTarget(seat); setTradeId(null); setPanels((p) => ({ ...p, chat: true })); };
    s.onPickTicket = (id) => { setSelected(id); setPanels((p) => ({ ...p, orders: true })); };
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
      else if (e.key === 'Escape' && scene.current?.rig.freefly) toggleFly();
      else if (!scene.current?.rig.freefly && /^[1-8]$/.test(e.key) && layout) goPreset(['overview', 'pit', 'corridor', 'cabins', 'executive', 'debate', 'gates', 'tape'][+e.key - 1]);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [layout, toggleFly, toggleTheme]);

  const fly = extra?.fly ?? null;
  const thinkingName = thinking.seat;

  return (
    <div className={'app ' + theme}>
      <div className="canvas" ref={host} />
      {!layout && <div className="loading">{err ? `Cannot reach the floor engine: ${err}` : 'Loading the trading floor…'}</div>}
      <TopBar preset={preset} freefly={freefly} theme={theme} speed={speed} connected={connected} panels={panels}
        onPreset={goPreset} onFly={toggleFly} onTheme={toggleTheme} onSpeed={changeSpeed}
        onPanel={(k) => setPanels((p) => ({ ...p, [k]: !p[k] }))} onSettings={() => setShowSettings(true)} />
      {panels.brain && <div className="dock left"><BrainHUD fly={fly} color={thinking.color} seatName={thinkingName} /></div>}
      {panels.orders && (
        <div className="dock right">
          <Orders orders={extra?.orders ?? []} layout={layout} selected={selected}
            onSelect={(id) => setSelected(id)}
            onAsk={(id, seat) => { setTradeId(id); setChatTarget(seat); setPanels((p) => ({ ...p, chat: true })); }} />
        </div>
      )}
      {panels.chat && (
        <div className="dock bottom">
          <ChatDock layout={layout} extra={extra} target={chatTarget} tradeId={tradeId}
            onTarget={(t) => { setChatTarget(t); if (t === ALL) setTradeId(null); }} onClearTrade={() => setTradeId(null)} />
        </div>
      )}
      {freefly && (
        <div className="hint">
          <b>360° free-fly</b> · drag = look · W A S D / arrows = move · Q / E = down / up · Shift = fast · Alt = slow · wheel = speed · Esc / F = exit
        </div>
      )}
      <Footer extra={extra} frame={frame} />
      {showSettings && <Settings onClose={() => setShowSettings(false)} onChanged={(s) => setSpeed(s.speed)} />}
    </div>
  );
}
