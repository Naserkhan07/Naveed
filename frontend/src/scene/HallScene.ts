import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import type { Extra, Frame, Layout, Theme } from '../types';
import { CameraRig } from './controls';
import { ThemeReg } from './registry';
import { Shared, buildOutdoor, buildShell, sharedMaterials } from './world';
import { Rooms, buildRooms } from './rooms';
import { Screens } from './screens';
import { Person, makePerson, setAccent, setLabel, setSitting } from './people';
import { canvas, canvasTexture, rng } from './textures';

interface Actor { p: Person; tx: number; tz: number; th: number; x: number; z: number; h: number; sit: boolean; born: number; }
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
  private actors = new Map<string, Actor>();
  private raf = 0; private last = performance.now(); private t = 0;
  private sun: THREE.DirectionalLight; private hemi: THREE.HemisphereLight;
  private domeMat: THREE.ShaderMaterial; private stars: THREE.Points;
  private outdoor: ReturnType<typeof buildOutdoor>;
  private ro: ResizeObserver;
  private ray = new THREE.Raycaster(); private downAt = { x: 0, y: 0 };
  private selectRing: THREE.Mesh; private selected: string | null = null;
  private frame: Frame | null = null;
  private envRT: THREE.WebGLRenderTarget;

  constructor(private host: HTMLElement, private L: Layout, theme: Theme) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: false });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
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
      this.hemi.color.set(n ? 0x5b74a8 : 0xbfd8ff); this.hemi.groundColor.set(n ? 0x1a2233 : 0x9aa6b8);
      this.sun.castShadow = !n;
      this.scene.environmentIntensity = n ? 0.16 : 0.6;
    });
    this.setTheme(theme);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    const dom = this.renderer.domElement;
    dom.addEventListener('pointerdown', (e) => { this.downAt = { x: e.clientX, y: e.clientY }; });
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

  private pick(e: PointerEvent) {
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
      if (pk) { this.onPickSeat(pk.seat); return; }
      for (const [id, a] of this.actors) if (a.p === o && id.startsWith('w_')) { this.selected = id; this.onPickTicket(id.slice(2)); return; }
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
        a = { p, tx: w.x, tz: w.z, th: w.h, x: w.x, z: w.z, h: w.h, sit: w.sit, born: this.t };
        this.actors.set(w.id, a);
      }
      a.tx = w.x; a.tz = w.z; a.th = w.h; a.sit = w.sit;
      setSitting(a.p, w.sit);
      if (w.k !== 'npc') {
        setAccent(a.p, w.c);
        setLabel(a.p, w.l, w.c);
        if (a.p.userData.label) a.p.userData.label.position.y = w.sit ? 1.75 : 2.2;
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
    if (sp) this.screens.drawDebate(sp, f.debate.text, this.L.palette.seat_colors[sp] ?? '#c084fc');
    else this.screens.drawDebate('', '');
  }

  setExtra(x: Extra) { this.screens.setRows(x.tape); }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const now = performance.now();
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now; this.t += dt;
    // smooth walkers between 12 Hz frames
    const k = 1 - Math.exp(-dt * 14), kr = 1 - Math.exp(-dt * 12);
    for (const a of this.actors.values()) {
      const dx = a.tx - a.x, dz = a.tz - a.z;
      if (dx * dx + dz * dz > 9) { a.x = a.tx; a.z = a.tz; } else { a.x += dx * k; a.z += dz * k; }
      a.h += angDiff(a.h, a.th) * kr;
      a.p.position.set(a.x, 0, a.z); a.p.rotation.y = a.h;
      // little walking bob
      if (!a.sit) { const sp = Math.hypot(dx, dz); a.p.position.y = sp > 0.02 ? Math.abs(Math.sin(this.t * 9 + a.born)) * 0.03 : 0; }
    }
    const sel = this.selected ? this.actors.get(this.selected) : null;
    this.selectRing.visible = !!sel;
    if (sel) { this.selectRing.position.set(sel.x, 0.05, sel.z); this.selectRing.scale.setScalar(1 + 0.08 * Math.sin(this.t * 5)); }
    this.rooms.update(this.t);
    this.outdoor.update(this.t);
    this.screens.update(this.t, dt);
    this.rig.update(dt);
    this.renderer.render(this.scene, this.camera);
  };

  dispose() {
    cancelAnimationFrame(this.raf); this.ro.disconnect(); this.rig.dispose();
    this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
