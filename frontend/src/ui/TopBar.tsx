import type { Theme } from '../types';

const PRESETS: [string, string][] = [['overview', 'Overview'], ['pit', 'Pit'], ['corridor', 'Corridor'], ['cabins', 'Cabins'], ['executive', 'Exec'], ['debate', 'Debate'], ['gates', 'Gates'], ['tape', 'Tape']];

interface Props {
  preset: string | null; freefly: boolean; theme: Theme; speed: number; connected: boolean;
  panels: { brain: boolean; orders: boolean; chat: boolean };
  onPreset: (p: string) => void; onFly: () => void; onTheme: () => void; onSpeed: (s: number) => void;
  onPanel: (k: 'brain' | 'orders' | 'chat') => void; onSettings: () => void;
}

export function TopBar(p: Props) {
  return (
    <header className="topbar">
      <div className="brand"><span className="logo">◈</span><b>SOUL EXTER</b><span className="sub">autonomous trading floor</span></div>
      <nav className="presets">
        {PRESETS.map(([k, n]) => (
          <button key={k} className={!p.freefly && p.preset === k ? 'on' : ''} onClick={() => p.onPreset(k)}>{n}</button>
        ))}
        <button className={'fly' + (p.freefly ? ' on' : '')} onClick={p.onFly} title="Free-fly viewer (F)">⌖ 360°</button>
      </nav>
      <div className="right">
        <label className="speed" title="simulation speed">
          <span>speed</span>
          <select value={String(p.speed)} onChange={(e) => p.onSpeed(parseFloat(e.target.value))}>
            {[0.25, 0.5, 1, 2, 4, 8, 16, 32].map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
        <button className="toggle" onClick={p.onTheme} title="Day / Night (N)">{p.theme === 'night' ? '☾ NIGHT' : '☀ DAY'}</button>
        <div className="seg">
          <button className={p.panels.brain ? 'on' : ''} onClick={() => p.onPanel('brain')}>Brain</button>
          <button className={p.panels.orders ? 'on' : ''} onClick={() => p.onPanel('orders')}>Orders</button>
          <button className={p.panels.chat ? 'on' : ''} onClick={() => p.onPanel('chat')}>Desks</button>
        </div>
        <button onClick={p.onSettings} title="Settings">⚙</button>
        <span className={'dot ' + (p.connected ? 'ok' : 'bad')} title={p.connected ? 'stream connected' : 'reconnecting…'} />
      </div>
    </header>
  );
}
