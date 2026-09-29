import * as THREE from 'three';
import type { Layout, TapeRow, TickerSpec } from '../types';
import { ThemeReg, box } from './registry';
import { canvas, canvasTexture, labelTexture } from './textures';

const UP = '#34d399', DOWN = '#f87171';
const STRIP_W = 8192, CELL = 470;

function fmt(r: TapeRow) {
  const dec = r.p >= 1000 ? 1 : r.p >= 100 ? 2 : r.p >= 10 ? 3 : r.p >= 1 ? 4 : 5;
  return r.p.toFixed(dec);
}

/** scrolling canvas ticker tape (a wide strip texture, scrolled by texture offset — no per-frame upload) */
class Ticker {
  tex: THREE.CanvasTexture;
  ctx: CanvasRenderingContext2D;
  cv: HTMLCanvasElement;
  meters: number;
  speed: number;
  constructor(public spec: TickerSpec, public filter: (r: TapeRow) => boolean, reg: ThemeReg, parent: THREE.Group, public title: string, speed = 2.4) {
    const [cv, ctx] = canvas(STRIP_W, 64);
    this.cv = cv; this.ctx = ctx;
    this.tex = canvasTexture(cv);
    this.tex.wrapS = THREE.RepeatWrapping;
    this.meters = STRIP_W * (0.9 / 64);
    this.tex.repeat.set(spec.w / this.meters, 1);
    this.speed = speed;
    const mat = new THREE.MeshStandardMaterial({ map: this.tex, emissiveMap: this.tex, emissive: 0xffffff, roughness: 0.4, color: 0xffffff });
    reg.emissive(mat, 0.75, 1.5);
    const body = new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.5, metalness: 0.4 });
    const front = new THREE.Mesh(new THREE.PlaneGeometry(spec.w, 0.9), mat);
    front.position.set(0, 0, 0.061);
    const back = new THREE.Mesh(new THREE.PlaneGeometry(spec.w, 0.9), mat);
    back.rotation.y = Math.PI; back.position.set(0, 0, -0.061);
    const g = new THREE.Group();
    g.add(box(spec.w + 0.2, 1.0, 0.12, body), front, back);
    g.position.set(spec.x, spec.y, spec.z);
    // hanger wires
    const wire = new THREE.MeshStandardMaterial({ color: 0x9aa5b4, metalness: 0.7, roughness: 0.4 });
    for (const dx of [-spec.w / 2 + 1, spec.w / 2 - 1]) g.add(box(0.03, 11.0 - spec.y, 0.03, wire, dx, (11.0 - spec.y) / 2 + 0.5, 0));
    parent.add(g);
    this.draw([]);
  }
  cursor = 0; lastRot = 0;
  draw(rows: TapeRow[], now = 0) {
    const g = this.ctx;
    g.fillStyle = '#0a101c'; g.fillRect(0, 0, STRIP_W, 64);
    const list = rows.filter(this.filter);
    g.textBaseline = 'middle';
    if (!list.length) { g.fillStyle = '#64748b'; g.font = '600 30px ui-monospace, Menlo, monospace'; g.fillText(`${this.title}  ·  waiting for tape…`, 20, 34); this.tex.needsUpdate = true; return; }
    if (now - this.lastRot > 20) { this.lastRot = now; this.cursor = (this.cursor + 9) % list.length; }
    const n = Math.floor(STRIP_W / CELL);
    for (let i = 0; i < n; i++) {
      const r = list[(this.cursor + i) % list.length], x = i * CELL + 14;
      g.font = '700 27px ui-monospace, Menlo, monospace'; g.fillStyle = '#e2e8f0'; g.fillText(r.s.replace('_', ' '), x, 33);
      g.font = '600 25px ui-monospace, Menlo, monospace'; g.fillStyle = '#93a4bd'; g.fillText(fmt(r), x + 150, 33);
      g.fillStyle = r.ch >= 0 ? UP : DOWN;
      g.fillText(`${r.ch >= 0 ? '▲' : '▼'}${Math.abs(r.ch).toFixed(2)}%`, x + 150 + 138, 33);
      g.fillStyle = '#1f2a3d'; g.fillRect(i * CELL + CELL - 6, 12, 2, 40);
    }
    this.tex.needsUpdate = true;
  }
  tick(t: number) { this.tex.offset.x = (t * this.speed / this.meters) % 1; }
}

const dot = (x: number, y: number, g: CanvasRenderingContext2D, c: string, r = 2) => { g.fillStyle = c; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); };

/** big video wall — animated sparklines, movers, world dot-matrix */
class VideoWall {
  cv: HTMLCanvasElement; ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture;
  hist: Map<string, number[]> = new Map();
  constructor(public spec: { id: string; title: string; w: number; h: number }, parent: THREE.Group, reg: ThemeReg, place: (m: THREE.Object3D) => void) {
    const W = 768, Hh = Math.round(768 * spec.h / spec.w);
    const [cv, ctx] = canvas(W, Hh);
    this.cv = cv; this.ctx = ctx; this.tex = canvasTexture(cv);
    const mat = new THREE.MeshStandardMaterial({ map: this.tex, emissiveMap: this.tex, emissive: 0xffffff, roughness: 0.3 });
    reg.emissive(mat, 0.8, 1.35);
    const g = new THREE.Group();
    g.add(box(spec.w + 0.3, spec.h + 0.3, 0.16, new THREE.MeshStandardMaterial({ color: 0x0e1420, roughness: 0.4, metalness: 0.5 }), 0, 0, -0.09));
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(spec.w, spec.h), mat);
    g.add(scr);
    place(g); parent.add(g);
    this.draw([], 0, 0);
  }
  draw(rows: TapeRow[], t: number, kind: number) {
    const g = this.ctx, W = this.cv.width, Hh = this.cv.height;
    g.fillStyle = '#070b14'; g.fillRect(0, 0, W, Hh);
    // grid
    g.strokeStyle = 'rgba(70,110,160,0.16)'; g.lineWidth = 1;
    for (let x = 0; x < W; x += 48) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, Hh); g.stroke(); }
    for (let y = 0; y < Hh; y += 48) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
    // title
    g.fillStyle = '#e2e8f0'; g.font = '800 40px Inter, system-ui, sans-serif'; g.textBaseline = 'top';
    g.fillText(this.spec.title, 24, 18);
    g.fillStyle = '#38bdf8'; g.fillRect(24, 66, 120, 3);
    // world dot matrix (kind 0 only)
    if (kind === 0) {
      for (let i = 0; i < 380; i++) {
        const a = i * 2.399, r = (i % 19) / 19;
        const x = W * 0.66 + Math.cos(a) * W * 0.3 * (0.35 + r * 0.65), y = Hh * 0.58 + Math.sin(a * 1.3) * Hh * 0.28 * (0.3 + r * 0.7);
        dot(x, y, g, `rgba(80,140,200,${0.15 + 0.15 * Math.sin(t * 1.5 + i)})`, 2.2);
      }
    }
    const list = rows.slice().sort((a, b) => Math.abs(b.ch) - Math.abs(a.ch)).slice(0, kind === 0 ? 9 : 6);
    const rh = (Hh - 110) / Math.max(list.length, 1);
    list.forEach((r, i) => {
      const y = 92 + i * rh;
      let h = this.hist.get(r.s);
      if (!h) { h = []; this.hist.set(r.s, h); }
      if (h.length === 0 || Math.abs(h[h.length - 1] - r.p) > 0) { h.push(r.p); if (h.length > 60) h.shift(); }
      g.font = '700 28px ui-monospace, Menlo, monospace'; g.fillStyle = '#e2e8f0'; g.textBaseline = 'middle';
      g.fillText(r.s.replace('_', ' '), 24, y + rh / 2);
      g.font = '600 24px ui-monospace, Menlo, monospace'; g.fillStyle = '#93a4bd'; g.fillText(fmt(r), 230, y + rh / 2);
      g.fillStyle = r.ch >= 0 ? UP : DOWN; g.fillText(`${r.ch >= 0 ? '▲' : '▼'}${Math.abs(r.ch).toFixed(2)}%`, 390, y + rh / 2);
      if (h.length > 2) {
        const mn = Math.min(...h), mx = Math.max(...h), sx = 210, x0 = W - sx - 24;
        g.strokeStyle = r.ch >= 0 ? UP : DOWN; g.lineWidth = 2.4; g.beginPath();
        h.forEach((v, k) => { const px = x0 + (k / (h!.length - 1)) * sx, py = y + rh - 8 - ((v - mn) / (mx - mn || 1)) * (rh - 16); k ? g.lineTo(px, py) : g.moveTo(px, py); });
        g.stroke();
      }
    });
    this.tex.needsUpdate = true;
  }
}

const FACING: Record<string, number> = { south: 0, north: Math.PI, east: Math.PI / 2, west: -Math.PI / 2 };

export class Screens {
  group = new THREE.Group();
  tickers: Ticker[] = [];
  walls: { w: VideoWall; kind: number }[] = [];
  tapeWall: { cv: HTMLCanvasElement; ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture } | null = null;
  debate: { cv: HTMLCanvasElement; ctx: CanvasRenderingContext2D; tex: THREE.CanvasTexture; last: string } | null = null;
  rows: TapeRow[] = [];
  private acc = 0;

  constructor(private L: Layout, reg: ThemeReg) {
    const T = L.decor.tickers;
    this.tickers.push(new Ticker(T.corridor, (r) => r.c === 'forex' || r.c === 'crypto', reg, this.group, 'CORRIDOR TAPE · FX + CRYPTO', 2.6));
    this.tickers.push(new Ticker(T.pit, (r) => r.c === 'stock' || r.c === 'index', reg, this.group, 'PIT TAPE · EQUITIES + INDICES', 2.1));
    this.tickers.push(new Ticker(T.lobby, (r) => r.c === 'future' || r.c === 'option' || r.c === 'index', reg, this.group, 'LOBBY TAPE · FUTURES + OPTIONS', 1.8));
    L.decor.video_walls.forEach((v, i) => {
      const vw = new VideoWall(v, this.group, reg, (g) => {
        g.position.set(v.x, v.y + v.h / 2, v.z);
        g.rotation.y = FACING[v.facing] ?? 0;
      });
      this.walls.push({ w: vw, kind: i === 0 ? 0 : 1 });
    });
    // signs
    L.decor.signs.forEach((s) => {
      const big = s.text === 'SOUL EXTER';
      const tex = labelTexture(s.text, { fg: big ? '#0f172a' : '#e2e8f0', bg: big ? '#e8edf5' : '#0f172a', border: big ? '#38bdf8' : '#38bdf8', w: 768, h: big ? 192 : 160, font: `800 ${big ? 116 : 92}px Inter, system-ui, sans-serif` });
      const m = new THREE.MeshStandardMaterial({ map: tex, emissiveMap: tex, emissive: 0xffffff, roughness: 0.5 });
      reg.emissive(m, big ? 0.35 : 0.6, big ? 0.9 : 1.2);
      const p = new THREE.Mesh(new THREE.PlaneGeometry(s.w, s.w * (big ? 0.25 : 160 / 768)), m);
      p.position.set(s.x, s.y, s.z); p.rotation.y = FACING[s.facing] ?? 0;
      this.group.add(p);
      if (s.y > 7) { // hung from the ceiling
        const wire = new THREE.MeshStandardMaterial({ color: 0x9aa5b4, metalness: 0.7, roughness: 0.4 });
        const h = 11.4 - s.y;
        if (Math.abs(s.z) < 30 && s.text !== 'SOUL EXTER') for (const dx of [-s.w / 2 + 0.3, s.w / 2 - 0.3]) this.group.add(box(0.03, h, 0.03, wire, s.x + dx, s.y + h / 2, s.z));
      }
    });
    // west-wall TAPE board (camera preset "tape" looks at it)
    const [cv, ctx] = canvas(1024, 512);
    const tex = canvasTexture(cv);
    const m = new THREE.MeshStandardMaterial({ map: tex, emissiveMap: tex, emissive: 0xffffff, roughness: 0.3 });
    reg.emissive(m, 0.8, 1.4);
    const board = new THREE.Group();
    board.add(box(14.4, 5.6, 0.14, new THREE.MeshStandardMaterial({ color: 0x0e1420, roughness: 0.4, metalness: 0.5 }), 0, 0, -0.08));
    board.add(new THREE.Mesh(new THREE.PlaneGeometry(14, 5.2), m));
    board.position.set(-45.72, 2.6 + 1.4, -1.4); board.rotation.y = Math.PI / 2;
    this.group.add(board);
    this.tapeWall = { cv, ctx, tex };
    // debate screen
    const [dcv, dctx] = canvas(1024, 448);
    const dtex = canvasTexture(dcv);
    const dm = new THREE.MeshStandardMaterial({ map: dtex, emissiveMap: dtex, emissive: 0xffffff, roughness: 0.3 });
    reg.emissive(dm, 0.8, 1.4);
    const [dx0, dz0, dx1, dz1] = L.debate.box;
    const scr = new THREE.Group();
    scr.add(box(9.2, 4.0, 0.14, new THREE.MeshStandardMaterial({ color: 0x0e1420, roughness: 0.4, metalness: 0.5 }), 0, 0, 0.08));
    scr.add(new THREE.Mesh(new THREE.PlaneGeometry(9, 3.8), dm));
    scr.position.set(dx1 - 0.3, 3.4, (dz0 + dz1) / 2 + 2); scr.rotation.y = -Math.PI / 2;
    this.group.add(scr);
    this.debate = { cv: dcv, ctx: dctx, tex: dtex, last: '\u0000' };
    this.drawDebate('', '');
  }

  setRows(rows: TapeRow[]) {
    if (!rows.length) return;
    this.rows = rows;
    this.tickers.forEach((t) => t.draw(rows, performance.now() / 1000));
  }

  drawDebate(speaker: string, text: string, color = '#c084fc') {
    const d = this.debate!;
    const key = speaker + text;
    if (d.last === key) return;
    d.last = key;
    const g = d.ctx;
    g.fillStyle = '#080c16'; g.fillRect(0, 0, 1024, 448);
    g.strokeStyle = 'rgba(192,132,252,.35)'; g.lineWidth = 4; g.strokeRect(6, 6, 1012, 436);
    g.fillStyle = '#e2e8f0'; g.font = '800 44px Inter, system-ui, sans-serif'; g.textBaseline = 'top';
    g.fillText('DEBATE CHAMBER — LESSONS', 30, 26);
    if (speaker) {
      g.fillStyle = color; g.font = '800 38px Inter, system-ui, sans-serif'; g.fillText(speaker, 30, 100);
      g.fillStyle = '#cbd5e1'; g.font = '500 31px Inter, system-ui, sans-serif';
      const words = text.split(' '); let line = '', y = 158;
      for (const w of words) { const t = line + w + ' '; if (g.measureText(t).width > 960) { g.fillText(line, 30, y); y += 42; line = w + ' '; if (y > 380) break; } else line = t; }
      g.fillText(line, 30, y);
    } else { g.fillStyle = '#64748b'; g.font = '500 32px Inter, system-ui, sans-serif'; g.fillText('The delegates are between rounds…', 30, 110); }
    d.tex.needsUpdate = true;
  }

  update(t: number, dt: number) {
    this.tickers.forEach((k) => k.tick(t));
    this.acc += dt;
    if (this.acc > 0.3) {
      this.acc = 0;
      const rows = this.rows;
      this.walls.forEach(({ w, kind }, i) => w.draw(rows.filter((r) => (i === 1 ? r.c === 'forex' || r.c === 'crypto' : i === 2 ? r.c === 'stock' || r.c === 'index' || r.c === 'future' : true)), t, kind));
      // west-wall tape: vertical scrolling list
      const tw = this.tapeWall!, g = tw.ctx;
      g.fillStyle = '#070b14'; g.fillRect(0, 0, 1024, 512);
      g.fillStyle = '#e2e8f0'; g.font = '800 34px Inter, system-ui, sans-serif'; g.textBaseline = 'top'; g.fillText('LIVE TAPE', 22, 14);
      g.fillStyle = '#38bdf8'; g.fillRect(22, 56, 100, 3);
      if (rows.length) {
        const rowH = 38, off = (t * 26) % rowH;
        for (let i = 0; i < 12; i++) {
          const r = rows[(Math.floor(t * 26 / rowH) + i * 3) % rows.length];
          const y = 70 + i * rowH - off;
          g.font = '700 26px ui-monospace, Menlo, monospace'; g.fillStyle = '#e2e8f0'; g.textBaseline = 'middle';
          g.fillText(r.s.replace('_', ' '), 26, y + 19);
          g.fillStyle = '#93a4bd'; g.fillText(r.c, 250, y + 19);
          g.fillStyle = '#cbd5e1'; g.fillText(fmt(r), 420, y + 19);
          g.fillStyle = r.ch >= 0 ? UP : DOWN; g.fillText(`${r.ch >= 0 ? '▲' : '▼'} ${Math.abs(r.ch).toFixed(2)}%`, 640, y + 19);
          g.fillStyle = 'rgba(148,163,184,.55)'; g.fillText(r.r.replace('_', ' '), 830, y + 19);
        }
      }
      g.fillStyle = '#070b14'; g.fillRect(0, 0, 1024, 64);
      g.fillStyle = '#e2e8f0'; g.font = '800 34px Inter, system-ui, sans-serif'; g.textBaseline = 'top'; g.fillText('LIVE TAPE', 22, 14);
      g.fillStyle = '#38bdf8'; g.fillRect(22, 56, 100, 3);
      tw.tex.needsUpdate = true;
    }
  }
}
