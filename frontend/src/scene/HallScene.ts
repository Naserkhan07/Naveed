import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { Extra, Frame, Layout, Theme } from '../types';
import { CameraRig } from './controls';
import { ThemeReg } from './registry';
import { Shared, buildOutdoor, buildShell, sharedMaterials } from './world';
import { Rooms, buildRooms } from './rooms';
import { Screens } from './screens';
import { Person, animatePerson, fitLabel, makePerson, setAccent, setCarry, setLabel, setSitting } from './people';
import { canvas, canvasTexture, rng } from './textures';

interface Actor { p: Person; tx: number; tz: number; th: number; x: number; z: number; h: number; sit: boolean; born: number; npc: boolean; }

/** speech bubble over a judge: verdict, confidence, one-line thesis. Click = open that desk's chat. */
class Bubble {
  sprite: THREE.Sprite; private c: HTMLCanvasElement; private g: CanvasRenderingContext2D; private tex: THREE.CanvasTexture; private key = '';
  constructor(parent: THREE.Object3D, y: number) {
    const [c, g] = canvas(512, 200); this.c = c; this.g = g;
    this.tex = new THREE.CanvasTexture(c); this.tex.colorSpace = THREE.SRGBColorSpace; this.tex.anisotropy = 4;
    this.sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.tex, transparent: true, depthWrite: false, depthTest: false }));
    this.sprite.renderOrder = 30; this.sprite.position.y = y; this.sprite.visible = false; parent.add(this.sprite);
  }
  set(say: { ok: boolean; conf: number; text: string; sym: string } | undefined, color: string, camDist: number) {
    if (!say || camDist > 70) { this.sprite.visible = false; return; }
    const k = say.sym + say.text + say.ok;
    if (k !== this.key) {
      this.key = k;
      const g = this.g, W = 512, H = 200;
      g.clearRect(0, 0, W, H);
      g.fillStyle = 'rgba(9,14,24,0.94)'; g.strokeStyle = color; g.lineWidth = 5;
      g.beginPath(); g.roundRect(4, 4, W - 8, H - 30, 18); g.fill(); g.stroke();
      g.beginPath(); g.moveTo(W / 2 - 14, H - 27); g.lineTo(W / 2, H - 4); g.lineTo(W / 2 + 14, H - 27); g.closePath(); g.fillStyle = 'rgba(9,14,24,0.94)'; g.fill();
      g.font = '800 34px Inter, system-ui, sans-serif'; g.textBaseline = 'alphabetic'; g.textAlign = 'left';
      g.fillStyle = say.ok ? '#34d399' : '#f87171'; g.fillText(`${say.ok ? 'APPROVE' : 'REJECT'} ${say.conf}%`, 24, 50);
      g.fillStyle = '#94a3b8'; g.font = '600 26px Inter, system-ui, sans-serif'; g.textAlign = 'right'; g.fillText(say.sym, W - 24, 50);
      g.textAlign = 'left'; g.fillStyle = '#e2e8f0'; g.font = '500 25px Inter, system-ui, sans-serif';
      const words = say.text.split(' '); let line = '', y = 88, n = 0;
      for (const w of words) {
        if (g.measureText(line + w).width > W - 48) { g.fillText(line, 24, y); y += 30; line = ''; if (++n >= 3) break; }
        line += w + ' ';
      }
      if (n < 3) g.fillText(line, 24, y);
      this.tex.needsUpdate = true;
    }
    const s = Math.min(2.6, Math.max(1, camDist / 26));
    this.sprite.scale.set(3.6 * s, 1.41 * s, 1);
    this.sprite.visible = true;
  }
}
const hex = (s: string) => parseInt(s.replace('#', ''), 16);
const angDiff = (a: number, b: number) => Math.atan2(Math.sin(b - a), Math.cos(b - a));

export class HallScene {
  renderer: THREE.WebGLRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  rig: CameraRig;
  reg = new ThemeReg();
  rooms: Rooms;
  screens: Screens;
  theme: Theme = 'night';
  onPickSeat: (seat: string) => void = () => {};
  onPickTicket: (id: string) => void = () => {};
  onDblTicket: (id: string) => void = () => {};
  private actors = new Map<string, Actor>();
  private raf = 0; private last = performance.now(); private t = 0;
  private sun: THREE.DirectionalLight; private hemi: THREE.HemisphereLight;
  private domeMat: THREE.ShaderMaterial; private stars: THREE.Points;
  private outdoor: ReturnType<typeof buildOutdoor>;
  private ro: ResizeObserver;
  private ray = new THREE.Raycaster(); private downAt = { x: 0, y: 0 };
  private selectRing: THREE.Mesh; private selected: string | null = null;
  private frame: Frame | null = null;
  private say: Record<string, { ok: boolean; conf: number; text: string; sym: string }> = {};
  private envRT: THREE.WebGLRenderTarget;
  private dprMax = 1.5; private dpr = 1.5; private ftAvg = 16; private ftN = 0;
  private bubbles: Record<string, Bubble> = {};
  private camDistTo = new THREE.Vector3();

  constructor(private host: HTMLElement, private L: Layout, theme: Theme) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: false });
    this.dprMax = Math.min(devicePixelRatio, 1.5); this.dpr = this.dprMax;
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = 'block';

    this.camera = new THREE.PerspectiveCamera(52, 1, 0.1, 2600);
    this.rig = new CameraRig(this.camera, this.renderer.domElement);
    const ov = L.cameras.overview;
    this.rig.goPreset('overview', ov, true);

    const pm = new THREE.PMREMGenerator(this.renderer);
    this.envRT = pm.fromScene(new RoomEnvironment(), 0.04);
    this.scene.environment = this.envRT.texture;
    this.scene.environmentIntensity = 0.55;
    pm.dispose();

    // lights
    this.hemi = this.reg.light(new THREE.HemisphereLight(0xbfd8ff, 0x9aa6b8, 1), 1.0, 0.3);
    this.scene.add(this.hemi);
    this.sun = this.reg.light(new THREE.DirectionalLight(0xfff3de, 1), 2.3, 0.0);
    this.sun.position.set(70, 120, 80);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera as THREE.OrthographicCamera;
    sc.left = -70; sc.right = 70; sc.top = 55; sc.bottom = -55; sc.near = 20; sc.far = 320;
    this.sun.shadow.bias = -0.0004; this.sun.shadow.normalBias = 0.04;
    this.sun.target.position.set(0, 0, 2);
    this.scene.add(this.sun, this.sun.target);
    const moon = this.reg.light(new THREE.DirectionalLight(0x8fb2ff, 1), 0, 0.45);
    moon.position.set(-60, 100, -50); this.scene.add(moon);

    // sky dome (gradient) + stars
    this.domeMat = new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: { top: { value: new THREE.Color(0x2f6fc4) }, bot: { value: new THREE.Color(0xa9d3f2) } },
      vertexShader: 'varying vec3 vp; void main(){ vp = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
      fragmentShader: 'varying vec3 vp; uniform vec3 top; uniform vec3 bot; void main(){ float h = clamp(vp.y*1.4+0.05,0.0,1.0); gl_FragColor = vec4(mix(bot, top, pow(h,0.7)),1.0); }',
    });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(1500, 32, 16), this.domeMat);
    dome.renderOrder = -10; this.scene.add(dome);
    const r = rng(77); const sp: number[] = [];
    for (let i = 0; i < 900; i++) { const a = r() * Math.PI * 2, e = Math.acos(r() * 0.95 + 0.05), R = 1400; sp.push(Math.sin(e) * Math.cos(a) * R, Math.cos(e) * R, Math.sin(e) * Math.sin(a) * R); }
    const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
    this.stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xdfe8ff, size: 2.6, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.85 }));
    this.scene.add(this.stars);

    // world
    const S: Shared = sharedMaterials(L);
    this.scene.add(buildShell(L, S, this.reg));
    this.outdoor = buildOutdoor(L, this.reg);
    this.scene.add(this.outdoor.group);
    this.rooms = buildRooms(L, S, this.reg);
    this.scene.add(this.rooms.group);
    for (const [seat, j] of Object.entries(this.rooms.judges)) { setLabel(j.person, seat, L.palette.seat_colors[seat] ?? '#94a3b8'); this.bubbles[seat] = new Bubble(j.person, 2.5); }
    setLabel(this.rooms.ceo.person, 'NAVEED · CEO', L.palette.seat_colors.NAVEED ?? '#c084fc'); this.bubbles.NAVEED = new Bubble(this.rooms.ceo.person, 2.5);
    this.screens = new Screens(L, this.reg);
    this.scene.add(this.screens.group);

    this.selectRing = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.62, 32), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
    this.selectRing.rotation.x = -Math.PI / 2; this.selectRing.visible = false; this.scene.add(this.selectRing);

    this.reg.on((t) => {
      const n = t === 'night';
      this.renderer.toneMappingExposure = n ? 1.05 : 1.5;
      this.scene.background = new THREE.Color(n ? 0x141d2e : 0xa9d3f2);
      this.scene.fog = n ? new THREE.FogExp2(0x0a0f18, 0.0042) : new THREE.FogExp2(0xbcd9f2, 0.0016);
      this.domeMat.uniforms.top.value.set(n ? 0x050a16 : 0x2f6fc4);
      this.domeMat.uniforms.bot.value.set(n ? 0x1a2740 : 0xa9d3f2);
      this.stars.visible = n;
      this.hemi.intensity = n ? 0.85 : 1.0; this.hemi.color.set(n ? 0x6f88bd : 0xbfd8ff); this.hemi.groundColor.set(n ? 0x1a2233 : 0x9aa6b8);
      this.sun.castShadow = !n;
      this.scene.environmentIntensity = n ? 0.3 : 0.6;
    });
    this.setTheme(theme);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    const dom = this.renderer.domElement;
    dom.addEventListener('pointerdown', (e) => { this.downAt = { x: e.clientX, y: e.clientY }; });
    dom.addEventListener('dblclick', (e) => this.pick(e, true));
    dom.addEventListener('pointerup', (e) => { if (Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) < 5) this.pick(e); });
    this.loop();
  }

  setTheme(t: Theme) { this.theme = t; this.reg.apply(t); }
  resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = '100%'; this.renderer.domElement.style.height = '100%';
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  private pick(e: MouseEvent, dbl = false) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const v = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(v, this.camera);
    const targets: THREE.Object3D[] = [];
    this.rooms.pickables.forEach((p) => targets.push(p.obj));
    this.actors.forEach((a, id) => { if (id.startsWith('w_')) targets.push(a.p); });
    const hits = this.ray.intersectObjects(targets, true);
    if (!hits.length) return;
    let o: THREE.Object3D | null = hits[0].object;
    while (o) {
      const pk = this.rooms.pickables.find((p) => p.obj === o);
      if (pk) { if (!dbl) this.onPickSeat(pk.seat); return; }
      for (const [id, a] of this.actors) if (a.p === o && id.startsWith('w_')) { this.selected = id; if (dbl) this.onDblTicket(id.slice(2)); else this.onPickTicket(id.slice(2)); return; }
      o = o.parent;
    }
  }
  select(ticket: string | null) { this.selected = ticket ? 'w_' + ticket : null; }

  goPreset(name: string) { const c = this.L.cameras[name]; if (c) this.rig.goPreset(name, c); }

  /** 12 Hz frame from the server: targets only; motion is lerped every render frame */
  setFrame(f: Frame) {
    this.frame = f;
    const seen = new Set<string>();
    const desks = this.L.desks;
    const ringOn = new Set<number>();
    for (const w of f.walkers) {
      seen.add(w.id);
      let a = this.actors.get(w.id);
      if (!a) {
        const seed = Math.abs([...w.id].reduce((s, c) => s * 31 + c.charCodeAt(0), 7));
        const p = makePerson(w.k === 'npc' ? 0x94a3b8 : hex(w.c), seed, w.k === 'npc' ? [0x243043, 0x2d3748, 0x3b4658, 0x1f2a3a][seed % 4] : 0x1e2735);
        p.position.set(w.x, 0, w.z); p.rotation.y = w.h;
        this.scene.add(p);
        a = { p, tx: w.x, tz: w.z, th: w.h, x: w.x, z: w.z, h: w.h, sit: w.sit, born: this.t, npc: w.k === 'npc' };
        this.actors.set(w.id, a);
      }
      a.tx = w.x; a.tz = w.z; a.th = w.h; a.sit = w.sit;
      setSitting(a.p, w.sit);
      setCarry(a.p, w.k !== 'npc');
      if (w.k === 'npc') setLabel(a.p, w.l, w.c || '#94a3b8', true);
      else {
        setAccent(a.p, w.c);
        setLabel(a.p, w.l, w.c);
        desks.forEach((d, i) => { if (Math.hypot(d.seat[0] - w.x, d.seat[1] - w.z) < 0.8 && w.sit) ringOn.add(i); });
      }
      a.p.visible = !w.gone;
    }
    for (const [id, a] of this.actors) if (!seen.has(id)) { this.scene.remove(a.p); this.actors.delete(id); }
    this.rooms.deskRings.forEach((r, i) => { r.visible = ringOn.has(i); });

    // judges / CEO glow while working
    for (const [seat, j] of Object.entries(this.rooms.judges)) {
      const st = f.judges[seat]?.state ?? 'idle';
      const act = st !== 'idle';
      (j.ring.material as THREE.MeshStandardMaterial).emissiveIntensity = act ? 2.4 : 0.6;
      j.person.userData.accentMat.emissiveIntensity = act ? 1.3 : 0.35;
    }
    const cs = f.judges.NAVEED?.state ?? 'idle';
    (this.rooms.ceo.ring.material as THREE.MeshStandardMaterial).emissiveIntensity = cs !== 'idle' ? 2.6 : 0.6;
    this.rooms.ceo.person.userData.accentMat.emissiveIntensity = cs !== 'idle' ? 1.3 : 0.35;
    // debate
    const sp = f.debate.speaker;
    for (const [seat, p] of Object.entries(this.rooms.delegates)) p.userData.accentMat.emissiveIntensity = sp === seat ? 1.6 : 0.3;
    this.say = {}; for (const [seat, j] of Object.entries(f.judges)) if (j.say) this.say[seat] = j.say;
    if (sp) this.screens.drawDebate(sp, f.debate.text, this.L.palette.seat_colors[sp] ?? '#c084fc');
    else this.screens.drawDebate('', '');
  }

  setExtra(x: Extra) { this.screens.setRows(x.tape); }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const now = performance.now();
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now; this.t += dt;
    // smooth walkers between 12 Hz frames; drive the walk cycle from the distance actually covered
    const k = 1 - Math.exp(-dt * 14), kr = 1 - Math.exp(-dt * 12);
    const cp = this.camera.position;
    for (const a of this.actors.values()) {
      const dx = a.tx - a.x, dz = a.tz - a.z, ox = a.x, oz = a.z;
      if (dx * dx + dz * dz > 9) { a.x = a.tx; a.z = a.tz; } else { a.x += dx * k; a.z += dz * k; }
      a.h += angDiff(a.h, a.th) * kr;
      a.p.position.set(a.x, 0, a.z); a.p.rotation.y = a.h;
      const cd = Math.hypot(cp.x - a.x, cp.y - 1.5, cp.z - a.z);
      if (cd < 70 || a.p.userData.sitK !== (a.sit ? 1 : 0)) animatePerson(a.p, this.t, dt, Math.hypot(a.x - ox, a.z - oz) / Math.max(dt, 1e-3));
      fitLabel(a.p, cd, a.npc);
    }
    for (const [seat, j] of Object.entries(this.rooms.judges)) {
      const wp = j.person.getWorldPosition(this.camDistTo);
      const cd = wp.distanceTo(cp);
      fitLabel(j.person, cd, false);
      this.bubbles[seat]?.set(this.say[seat], this.L.palette.seat_colors[seat] ?? '#38bdf8', cd);
    }
    { const wp = this.rooms.ceo.person.getWorldPosition(this.camDistTo); const cd = wp.distanceTo(cp);
      fitLabel(this.rooms.ceo.person, cd, false); this.bubbles.NAVEED?.set(this.say.NAVEED, this.L.palette.seat_colors.NAVEED ?? '#c084fc', cd); }
    const sel = this.selected ? this.actors.get(this.selected) : null;
    this.selectRing.visible = !!sel;
    if (sel) { this.selectRing.position.set(sel.x, 0.05, sel.z); this.selectRing.scale.setScalar(1 + 0.08 * Math.sin(this.t * 5)); }
    this.rooms.update(this.t);
    this.outdoor.update(this.t);
    this.screens.update(this.t, dt);
    this.rig.update(dt);
    this.renderer.render(this.scene, this.camera);
    // adaptive resolution: hold ~50 fps on modest GPUs
    this.ftAvg += (dt * 1000 - this.ftAvg) * 0.05;
    if (++this.ftN % 45 === 0) {
      if (this.ftAvg > 24 && this.dpr > 0.8) { this.dpr = Math.max(0.8, this.dpr - 0.25); this.renderer.setPixelRatio(this.dpr); this.resize(); }
      else if (this.ftAvg < 13.5 && this.dpr < this.dprMax) { this.dpr = Math.min(this.dprMax, this.dpr + 0.25); this.renderer.setPixelRatio(this.dpr); this.resize(); }
    }
  };

  dispose() {
    cancelAnimationFrame(this.raf); this.ro.disconnect(); this.rig.dispose();
    this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
