import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import type { FlySnap } from '../types';
import { labelTexture, rng } from './textures';

export interface Wiring { gp: [number, number][][]; fan: number[][]; mb: number[][]; instincts: number[][] }

const N_G = 29, N_PN = 26, N_KC = 140, N_MB = 8;
const BEAM = 5.2, TRAIL = 28;          // one fast light packet: head size 5.2 px, 28-point trail
const BLOOM = { strength: 0.35, radius: 0.42, threshold: 0.32 };

interface Neuron { pos: THREE.Vector3; v0: number; vn: number; }

/** Fly-brain connectome: somas + branching arbors + tract polylines, one light packet hopping along real tracts. Restrained bloom, no glow blobs. */
export class FlyBrainView {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
  private controls: OrbitControls;
  private composer: EffectComposer;
  private raf = 0;
  private ro: ResizeObserver;
  private layers: { g: Neuron[]; pn: Neuron[]; kc: Neuron[]; mb: Neuron[] } = { g: [], pn: [], kc: [], mb: [] };
  private somas!: THREE.InstancedMesh;
  private soma0: Record<'g' | 'pn' | 'kc' | 'mb', number> = { g: 0, pn: N_G, kc: N_G + N_PN, mb: N_G + N_PN + N_KC };
  private arbor!: THREE.LineSegments;
  private tractA!: THREE.LineSegments;
  private tractRanges: { a: number; b: number; v0: number; n: number }[] = [];   // a,b = global soma indices
  private tractPoly = new Map<string, THREE.Vector3[]>();
  private tractCol!: THREE.BufferAttribute;
  private mbLabels: THREE.Sprite[] = [];
  private act = new Float32Array(N_G + N_PN + N_KC + N_MB);
  private actTarget = new Float32Array(N_G + N_PN + N_KC + N_MB);
  private color = new THREE.Color('#34d399');
  private focus: FlySnap['focus'] | null = null;
  // packet
  private head!: THREE.Points; private trail!: THREE.Line;
  private route: THREE.Vector3[] = []; private routeLen: number[] = []; private routeS = 0; private routeTotal = 0;
  private trailPts: THREE.Vector3[] = [];
  private pause = 0;
  private rand = rng(4242);
  private t = 0; private last = performance.now();
  private ready = false;
  private group = new THREE.Group();

  constructor(private host: HTMLElement, mbNames: string[], wiring: Wiring | null) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setClearColor(0x04070d, 1);
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.cssText = 'display:block;width:100%;height:100%';
    this.camera.position.set(1.5, 4.5, 21);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true; this.controls.autoRotate = true; this.controls.autoRotateSpeed = 0.55;
    this.controls.minDistance = 8; this.controls.maxDistance = 46; this.controls.target.set(1.2, 0, 0);
    this.scene.add(this.group);
    this.scene.add(new THREE.AmbientLight(0x6b7f9e, 0.9));
    const key = new THREE.DirectionalLight(0xdfe9ff, 1.6); key.position.set(6, 10, 12); this.scene.add(key);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.composer.addPass(new UnrealBloomPass(new THREE.Vector2(512, 512), BLOOM.strength, BLOOM.radius, BLOOM.threshold));
    this.composer.addPass(new OutputPass());

    this.build(mbNames, wiring ?? this.fallbackWiring());
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.loop();
  }

  private fallbackWiring(): Wiring {
    const r = rng(7);
    return {
      gp: Array.from({ length: N_PN }, () => Array.from({ length: 5 }, () => [Math.floor(r() * N_G), r() - 0.2] as [number, number])),
      fan: Array.from({ length: N_KC }, () => Array.from({ length: 6 }, () => Math.floor(r() * N_PN))),
      mb: Array.from({ length: N_MB }, () => Array.from({ length: N_KC }, () => 0)), instincts: [],
    };
  }

  private build(mbNames: string[], W: Wiring) {
    const r = this.rand;
    const gauss = () => (r() + r() + r() + r() - 2) * 1.2;
    // ---- positions
    const L = this.layers;
    for (let i = 0; i < N_G; i++) {
      const a = -1.15 + (i / (N_G - 1)) * 2.3, row = i % 2;
      L.g.push({ pos: new THREE.Vector3(-8.2 + row * 0.7 + Math.cos(a * 2) * 0.3, Math.sin(a) * 5.2, Math.cos(a) * 1.9 - 0.4 + (row ? 0.6 : 0)), v0: 0, vn: 0 });
    }
    for (let i = 0; i < N_PN; i++) {
      const a = -1.1 + (i / (N_PN - 1)) * 2.2;
      L.pn.push({ pos: new THREE.Vector3(-4.3 + Math.sin(i * 1.7) * 0.35, Math.sin(a) * 4.6, Math.cos(a) * 2.2 - 0.3), v0: 0, vn: 0 });
    }
    for (let i = 0; i < N_KC; i++) {
      const u = r() * Math.PI * 2, v = Math.acos(2 * r() - 1), rad = 0.55 + 0.45 * Math.cbrt(r());
      L.kc.push({ pos: new THREE.Vector3(1.2 + Math.sin(v) * Math.cos(u) * 3.0 * rad, Math.cos(v) * 3.5 * rad, Math.sin(v) * Math.sin(u) * 2.4 * rad), v0: 0, vn: 0 });
    }
    for (let i = 0; i < N_MB; i++) L.mb.push({ pos: new THREE.Vector3(7.6 + Math.sin(i * 0.9) * 0.4, (i - (N_MB - 1) / 2) * 1.3, Math.cos(i * 1.4) * 0.9), v0: 0, vn: 0 });
    void gauss;
    const all = [...L.g, ...L.pn, ...L.kc, ...L.mb];

    // ---- somas (matte, instance-coloured by activity)
    const sg = new THREE.SphereGeometry(1, 14, 10);
    const sm = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55, metalness: 0.05 });
    this.somas = new THREE.InstancedMesh(sg, sm, all.length);
    const m4 = new THREE.Matrix4();
    const radius = (i: number) => (i < N_G ? 0.17 : i < N_G + N_PN ? 0.12 : i < N_G + N_PN + N_KC ? 0.075 : 0.23);
    all.forEach((n, i) => { m4.compose(n.pos, new THREE.Quaternion(), new THREE.Vector3().setScalar(radius(i))); this.somas.setMatrixAt(i, m4); this.somas.setColorAt(i, new THREE.Color(0x3a4a66)); });
    this.group.add(this.somas);

    // ---- arbors: recursive branching polylines; per-vertex colour follows the neuron's activity
    const av: number[] = [];
    const branch = (o: THREE.Vector3, d: THREE.Vector3, len: number, depth: number, out: number[]) => {
      const e = o.clone().addScaledVector(d, len);
      out.push(o.x, o.y, o.z, e.x, e.y, e.z);
      if (depth <= 0) return;
      const k = depth > 2 ? 2 : 2 + (r() < 0.4 ? 1 : 0);
      for (let i = 0; i < k; i++) {
        const nd = d.clone().add(new THREE.Vector3((r() - 0.5) * 1.3, (r() - 0.5) * 1.3, (r() - 0.5) * 1.3)).normalize();
        branch(e, nd, len * (0.62 + r() * 0.15), depth - 1, out);
      }
    };
    all.forEach((n, i) => {
      const out: number[] = [];
      const sz = i < N_G ? 1.0 : i < N_G + N_PN ? 0.85 : i < N_G + N_PN + N_KC ? 0.5 : 1.2;
      const nDend = i < N_G + N_PN + N_KC ? 3 : 4;
      const axisDir = new THREE.Vector3(i < N_G + N_PN + N_KC ? -1 : 1, 0, 0);
      for (let k = 0; k < nDend; k++) {
        const d = axisDir.clone().add(new THREE.Vector3((r() - 0.5) * 1.6, (r() - 0.5) * 1.6, (r() - 0.5) * 1.6)).normalize();
        branch(n.pos, d, sz * (0.5 + r() * 0.25), i < N_G + N_PN + N_KC ? 3 : 4, out);
      }
      n.v0 = av.length / 3; n.vn = out.length / 3; av.push(...out);
    });
    const ag = new THREE.BufferGeometry();
    ag.setAttribute('position', new THREE.Float32BufferAttribute(av, 3));
    ag.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(av.length).fill(0.16), 3));
    this.arbor = new THREE.LineSegments(ag, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }));
    this.group.add(this.arbor);

    // ---- tracts (bezier polylines between real connected neurons)
    const tv: number[] = [];
    const addTract = (key: string, a: number, b: number, bend: number) => {
      const p0 = all[a].pos, p3 = all[b].pos;
      const dx = (p3.x - p0.x) * 0.45;
      const off = new THREE.Vector3((r() - 0.5) * bend, (r() - 0.5) * bend, (r() - 0.5) * bend);
      const c1 = new THREE.Vector3(p0.x + dx, p0.y, p0.z).add(off), c2 = new THREE.Vector3(p3.x - dx, p3.y, p3.z).add(off);
      const curve = new THREE.CubicBezierCurve3(p0, c1, c2, p3);
      const pts = curve.getPoints(12);
      this.tractPoly.set(key, pts);
      const v0 = tv.length / 3;
      for (let i = 0; i < pts.length - 1; i++) tv.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
      this.tractRanges.push({ a, b, v0, n: (pts.length - 1) * 2 });
    };
    W.gp.forEach((row, pn) => row.forEach(([g]) => addTract(`gp:${g}:${pn}`, g, N_G + pn, 0.5)));
    W.fan.forEach((row, kc) => row.forEach((pn) => addTract(`pk:${pn}:${kc}`, N_G + pn, N_G + N_PN + kc, 0.9)));
    for (let kc = 0; kc < N_KC; kc++) {
      const order = Array.from({ length: N_MB }, (_, m) => m).sort((a, b) => Math.abs(W.mb[b]?.[kc] ?? 0) - Math.abs(W.mb[a]?.[kc] ?? 0) || ((a * 7 + kc * 3) % 8) - ((b * 7 + kc * 3) % 8));
      for (const m of order.slice(0, 2)) addTract(`km:${kc}:${m}`, N_G + N_PN + kc, N_G + N_PN + N_KC + m, 0.7);
    }
    const tg = new THREE.BufferGeometry();
    tg.setAttribute('position', new THREE.Float32BufferAttribute(tv, 3));
    this.tractCol = new THREE.Float32BufferAttribute(new Float32Array(tv.length).fill(0.08), 3);
    tg.setAttribute('color', this.tractCol);
    this.tractA = new THREE.LineSegments(tg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.75 }));
    this.group.add(this.tractA);

    // ---- faint wire ellipsoid outlines (AL, calyx, output lobe)
    const wire = (cx: number, cy: number, sx: number, sy: number, sz: number) => {
      const m = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14), new THREE.MeshBasicMaterial({ color: 0x5c7fb0, wireframe: true, transparent: true, opacity: 0.07 }));
      m.position.set(cx, cy, 0); m.scale.set(sx, sy, sz); this.group.add(m);
    };
    wire(-7.6, 0, 1.8, 6.4, 3.2); wire(-4.3, 0, 1.5, 5.8, 3.0); wire(1.2, 0, 4.0, 4.6, 3.4); wire(7.6, 0, 1.6, 5.6, 2.2);

    // ---- MBON labels
    mbNames.forEach((nm, i) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTexture(nm.toUpperCase(), { fg: '#cbd5e1', w: 256, h: 64, font: '700 34px ui-monospace, Menlo, monospace' }), transparent: true, depthWrite: false, opacity: 0.8 }));
      s.scale.set(1.9, 0.48, 1); s.position.copy(L.mb[i].pos).add(new THREE.Vector3(1.35, 0, 0)); this.group.add(s); this.mbLabels.push(s);
    });

    // ---- the single fast light packet: crisp head point + 28-point trail
    const hg = new THREE.BufferGeometry(); hg.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3));
    this.head = new THREE.Points(hg, new THREE.PointsMaterial({ size: BEAM, sizeAttenuation: false, color: this.color, depthTest: false }));
    this.head.renderOrder = 10; this.head.visible = false;
    const trg = new THREE.BufferGeometry();
    trg.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(TRAIL * 3), 3));
    trg.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(TRAIL * 3), 3));
    this.trail = new THREE.Line(trg, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false }));
    this.trail.renderOrder = 9; this.trail.frustumCulled = false; this.trail.visible = false;
    this.group.add(this.head, this.trail);
    this.ready = true;
    this.fanCache = W.fan; this.gpCache = W.gp;
  }
  private fanCache: number[][] = []; private gpCache: [number, number][][] = [];

  setColor(c: string) { this.color.set(c); (this.head.material as THREE.PointsMaterial).color.copy(this.color); }

  /** ~1 Hz snapshot from the server */
  setFocus(f: FlySnap['focus']) {
    this.focus = f;
    const T = this.actTarget, s0 = this.soma0;
    const norm = (a: number[], scale = 1) => { const mx = Math.max(1e-6, ...a.map((v) => Math.abs(v))); return a.map((v) => Math.min(1, Math.abs(v) / mx * scale)); };
    norm(f.g).forEach((v, i) => (T[s0.g + i] = v));
    norm(f.pn).forEach((v, i) => (T[s0.pn + i] = v));
    for (let i = 0; i < N_KC; i++) T[s0.kc + i] = 0;
    f.kc.forEach((k) => { if (k >= 0 && k < N_KC) T[s0.kc + k] = 1; });
    const mb = f.mb; const lo = Math.min(...mb), hi = Math.max(...mb);
    mb.forEach((v, i) => (T[s0.mb + i] = (v - lo) / Math.max(1e-6, hi - lo)));
  }

  private pickRoute() {
    const f = this.focus; if (!f || !this.ready) return false;
    const pick = (arr: number[]) => { let tot = 0; const w = arr.map((v) => { const x = Math.max(0.02, Math.abs(v)); tot += x * x; return x * x; }); let u = this.rand() * tot; for (let i = 0; i < w.length; i++) { u -= w[i]; if (u <= 0) return i; } return 0; };
    // PN first (weighted by activity), a glomerulus that feeds it, an active KC it drives, then the winning MBON
    const pn = pick(f.pn);
    const gs = this.gpCache[pn]; if (!gs || !gs.length) return false;
    const g = gs[Math.floor(this.rand() * gs.length)][0];
    const kcs = f.kc.filter((k) => this.fanCache[k]?.includes(pn));
    const pool = kcs.length ? kcs : this.fanCache.map((row, k) => (row.includes(pn) ? k : -1)).filter((k) => k >= 0);
    if (!pool.length) return false;
    const kc = pool[Math.floor(this.rand() * pool.length)];
    let mbi = 0; f.mb.forEach((v, i) => { if (v > f.mb[mbi]) mbi = i; });
    const a = this.tractPoly.get(`gp:${g}:${pn}`), b = this.tractPoly.get(`pk:${pn}:${kc}`);
    let c = this.tractPoly.get(`km:${kc}:${mbi}`);
    if (!c) { for (let m = 0; m < N_MB && !c; m++) c = this.tractPoly.get(`km:${kc}:${m}`); }
    if (!a || !b || !c) return false;
    this.route = [...a, ...b.slice(1), ...c.slice(1)];
    this.routeLen = [0];
    for (let i = 1; i < this.route.length; i++) this.routeLen.push(this.routeLen[i - 1] + this.route[i].distanceTo(this.route[i - 1]));
    this.routeTotal = this.routeLen[this.routeLen.length - 1]; this.routeS = 0; this.trailPts = [];
    return true;
  }

  private at(s: number, out: THREE.Vector3) {
    let i = 1; while (i < this.routeLen.length - 1 && this.routeLen[i] < s) i++;
    const u = (s - this.routeLen[i - 1]) / Math.max(1e-6, this.routeLen[i] - this.routeLen[i - 1]);
    return out.lerpVectors(this.route[i - 1], this.route[i], Math.min(1, Math.max(0, u)));
  }

  private paint(dt: number) {
    const A = this.act, T = this.actTarget, k = 1 - Math.exp(-dt * 6);
    for (let i = 0; i < A.length; i++) A[i] += (T[i] - A[i]) * k;
    const base = new THREE.Color(0x2c3a54), hot = this.color.clone().lerp(new THREE.Color(0xe8f6ff), 0.35);
    const tmp = new THREE.Color();
    const ic = this.somas.instanceColor!;
    for (let i = 0; i < A.length; i++) { tmp.copy(base).lerp(hot, Math.min(1, A[i] * 0.85)); ic.setXYZ(i, tmp.r, tmp.g, tmp.b); }
    ic.needsUpdate = true;
    // arbors
    const ac = this.arbor.geometry.getAttribute('color') as THREE.BufferAttribute;
    const all = [...this.layers.g, ...this.layers.pn, ...this.layers.kc, ...this.layers.mb];
    const dim = new THREE.Color(0x1c2638);
    all.forEach((n, i) => {
      tmp.copy(dim).lerp(hot, Math.min(1, A[i] * 0.75));
      for (let v = 0; v < n.vn; v++) { const d = 1 - (v % 8) * 0.03; ac.setXYZ(n.v0 + v, tmp.r * d, tmp.g * d, tmp.b * d); }
    });
    ac.needsUpdate = true;
    // tracts: brightness = pre × post activity
    const tdim = new THREE.Color(0x141c2b);
    for (const t of this.tractRanges) {
      const s = Math.min(1, A[t.a] * A[t.b] * 1.4);
      tmp.copy(tdim).lerp(hot, s * 0.9);
      for (let v = 0; v < t.n; v++) this.tractCol.setXYZ(t.v0 + v, tmp.r, tmp.g, tmp.b);
    }
    this.tractCol.needsUpdate = true;
    this.mbLabels.forEach((l, i) => ((l.material as THREE.SpriteMaterial).opacity = 0.45 + 0.55 * A[this.soma0.mb + i]));
  }

  private movePacket(dt: number) {
    if (this.pause > 0) { this.pause -= dt; this.head.visible = false; this.trail.visible = this.trailPts.length > 1 && this.pause > 0; if (this.trailPts.length) this.trailPts.shift(); this.writeTrail(); return; }
    if (!this.route.length || this.routeS >= this.routeTotal) {
      if (this.route.length) { this.pause = 0.08 + this.rand() * 0.25; this.route = []; return; }
      if (!this.pickRoute()) return;
    }
    this.routeS += dt * 15;             // fast
    const p = this.at(Math.min(this.routeS, this.routeTotal), new THREE.Vector3());
    this.trailPts.push(p); if (this.trailPts.length > TRAIL) this.trailPts.shift();
    const pos = this.head.geometry.getAttribute('position') as THREE.BufferAttribute; pos.setXYZ(0, p.x, p.y, p.z); pos.needsUpdate = true;
    this.head.visible = true; this.trail.visible = true;
    this.writeTrail();
  }
  private writeTrail() {
    const pa = this.trail.geometry.getAttribute('position') as THREE.BufferAttribute, ca = this.trail.geometry.getAttribute('color') as THREE.BufferAttribute;
    const n = this.trailPts.length;
    for (let i = 0; i < TRAIL; i++) {
      const p = this.trailPts[Math.max(0, i - (TRAIL - n))] ?? this.trailPts[0] ?? new THREE.Vector3();
      const f = i < TRAIL - n ? 0 : Math.pow((i - (TRAIL - n) + 1) / n, 2.2);
      pa.setXYZ(i, p.x, p.y, p.z); ca.setXYZ(i, this.color.r * f, this.color.g * f, this.color.b * f);
    }
    pa.needsUpdate = true; ca.needsUpdate = true;
  }

  resize() {
    const w = Math.max(1, this.host.clientWidth), h = Math.max(1, this.host.clientHeight);
    this.renderer.setSize(w, h, false); this.composer.setSize(w, h);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const now = performance.now(), dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now; this.t += dt;
    if (this.ready) { this.paint(dt); this.movePacket(dt); }
    this.controls.update();
    this.composer.render();
  };

  dispose() {
    cancelAnimationFrame(this.raf); this.ro.disconnect(); this.controls.dispose();
    this.composer.dispose(); this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
