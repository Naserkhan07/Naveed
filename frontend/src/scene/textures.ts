import * as THREE from 'three';

export function canvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return [c, c.getContext('2d')!];
}
const tex = (c: HTMLCanvasElement, srgb = true) => {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
};
function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/** polished WHITE stone: #f5f7fa -> #e9edf3 blotches, grey grain, panel grid rgba(110,140,180,0.09) */
export function stoneTexture(a = '#f5f7fa', b = '#e9edf3', grid = 'rgba(110,140,180,0.09)', size = 2048, panels = 8): THREE.CanvasTexture {
  const [c, g] = canvas(size, size);
  g.fillStyle = a; g.fillRect(0, 0, size, size);
  const r = rng(42);
  // periodic soft blotches (wrap-around) between the two whites
  for (let i = 0; i < 46; i++) {
    const x = r() * size, y = r() * size, rad = 140 + r() * 320;
    const col = r() < 0.5 ? b : a;
    for (const ox of [-size, 0, size]) for (const oy of [-size, 0, size]) {
      const gr = g.createRadialGradient(x + ox, y + oy, 0, x + ox, y + oy, rad);
      gr.addColorStop(0, col); gr.addColorStop(1, 'rgba(255,255,255,0)');
      g.globalAlpha = 0.5; g.fillStyle = gr;
      g.fillRect(x + ox - rad, y + oy - rad, rad * 2, rad * 2);
    }
  }
  g.globalAlpha = 1;
  // grey grain
  const img = g.getImageData(0, 0, size, size);
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (r() - 0.5) * 9;
    img.data[i] += n; img.data[i + 1] += n; img.data[i + 2] += n * 1.05;
  }
  g.putImageData(img, 0, 0);
  // faint veins
  g.strokeStyle = 'rgba(150,160,175,0.10)'; g.lineWidth = 1.2;
  for (let i = 0; i < 26; i++) {
    g.beginPath();
    let x = r() * size, y = r() * size;
    g.moveTo(x, y);
    for (let k = 0; k < 8; k++) { x += (r() - 0.3) * 160; y += (r() - 0.5) * 120; g.lineTo(x, y); }
    g.stroke();
  }
  // panel grid
  g.strokeStyle = grid; g.lineWidth = 2;
  const step = size / panels;
  for (let i = 0; i <= panels; i++) {
    g.beginPath(); g.moveTo(i * step, 0); g.lineTo(i * step, size); g.stroke();
    g.beginPath(); g.moveTo(0, i * step); g.lineTo(size, i * step); g.stroke();
  }
  const t = tex(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

export function labelTexture(text: string, opts: { font?: string; fg?: string; bg?: string; w?: number; h?: number; border?: string } = {}) {
  const w = opts.w ?? 512, h = opts.h ?? 128;
  const [c, g] = canvas(w, h);
  if (opts.bg) { g.fillStyle = opts.bg; g.fillRect(0, 0, w, h); }
  if (opts.border) { g.strokeStyle = opts.border; g.lineWidth = 6; g.strokeRect(3, 3, w - 6, h - 6); }
  g.fillStyle = opts.fg ?? '#0f172a';
  g.font = opts.font ?? `700 ${Math.floor(h * 0.56)}px Inter, system-ui, sans-serif`;
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, w / 2, h / 2 + 2);
  return tex(c);
}

export function windowTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(256, 512);
  g.fillStyle = '#0b0f17'; g.fillRect(0, 0, 256, 512);
  const r = rng(9);
  for (let y = 8; y < 504; y += 16) for (let x = 8; x < 248; x += 16) {
    const lit = r() < 0.55;
    g.fillStyle = lit ? (r() < 0.2 ? '#7dd3fc' : '#ffe6a8') : '#111827';
    g.fillRect(x, y, 9, 9);
  }
  const t = tex(c); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
export function windowMaskTexture(): THREE.CanvasTexture { // emissive: only the lit windows
  const [c, g] = canvas(256, 512);
  g.fillStyle = '#000'; g.fillRect(0, 0, 256, 512);
  const r = rng(9);
  for (let y = 8; y < 504; y += 16) for (let x = 8; x < 248; x += 16) {
    const lit = r() < 0.55;
    const k = r() < 0.2;
    if (lit) { g.fillStyle = k ? '#7dd3fc' : '#ffe6a8'; g.fillRect(x, y, 9, 9); }
  }
  const t = tex(c); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
export function daylightWindowTexture(): THREE.CanvasTexture {
  const [c, g] = canvas(256, 512);
  g.fillStyle = '#9db2c8'; g.fillRect(0, 0, 256, 512);
  for (let y = 8; y < 504; y += 16) for (let x = 8; x < 248; x += 16) { g.fillStyle = '#5f7f9e'; g.fillRect(x, y, 9, 9); }
  const t = tex(c); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

export function chartTexture(seed = 1) {
  const [c, g] = canvas(256, 128);
  g.fillStyle = '#0b1220'; g.fillRect(0, 0, 256, 128);
  g.strokeStyle = 'rgba(80,120,170,.25)'; g.lineWidth = 1;
  for (let x = 0; x < 256; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 128); g.stroke(); }
  for (let y = 0; y < 128; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(256, y); g.stroke(); }
  const r = rng(seed * 77);
  let y = 64;
  g.strokeStyle = r() < 0.5 ? '#34d399' : '#38bdf8'; g.lineWidth = 2; g.beginPath();
  for (let x = 0; x < 256; x += 4) { y += (r() - 0.5) * 16; y = Math.max(16, Math.min(112, y)); x ? g.lineTo(x, y) : g.moveTo(x, y); }
  g.stroke();
  return tex(c);
}

export { tex as canvasTexture, rng };
