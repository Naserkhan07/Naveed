import * as THREE from 'three';
import type { Layout } from '../types';
import { ThemeReg, box, cyl, std } from './registry';
import { Shared } from './world';
import { canvas, canvasTexture, chartTexture, labelTexture } from './textures';
import { Person, makePerson, snapSit } from './people';

export interface Rooms {
  group: THREE.Group;
  judges: Record<string, { person: Person; strip: THREE.MeshStandardMaterial; ring: THREE.Mesh; light: THREE.PointLight }>;
  ceo: { person: Person; ring: THREE.Mesh; light: THREE.PointLight };
  delegates: Record<string, Person>;
  deskRings: THREE.Mesh[];
  pickables: { obj: THREE.Object3D; seat: string }[];
  guard: Person;
  update(t: number): void;
}

const hex = (s: string) => parseInt(s.replace('#', ''), 16);

export function buildRooms(L: Layout, S: Shared, reg: ThemeReg): Rooms {
  const g = new THREE.Group();
  const seatC = L.palette.seat_colors;
  const pickables: { obj: THREE.Object3D; seat: string }[] = [];
  const judges: Rooms['judges'] = {};

  // ---------------------------------------------------------------- 5 review cabins
  const woodM = std(0xd8dde6, 0.45, 0.1), deskTop = std(0xf1f4f8, 0.3, 0.05), chairM = std(0x263042, 0.7);
  for (const c of L.cabins) {
    const col = hex(seatC[c.seat]);
    const [dx, dz] = c.desk;
    g.add(box(3.2, 0.08, 1.1, deskTop, dx, 0.78, dz, true));
    g.add(box(3.0, 0.72, 0.9, woodM, dx, 0.36, dz, true));
    // monitor + nameplate
    const mon = box(0.9, 0.55, 0.05, std(0x0b1220, 0.3, 0.5), dx, 1.2, dz - 0.25);
    mon.rotation.x = -0.12; g.add(mon);
    const scr = new THREE.MeshStandardMaterial({ map: chartTexture(c.id), emissiveMap: chartTexture(c.id), emissive: 0xffffff, roughness: 0.3 });
    reg.emissive(scr, 0.7, 1.4);
    const sp = new THREE.Mesh(new THREE.PlaneGeometry(0.82, 0.47), scr); sp.position.set(dx, 1.2, dz - 0.222); sp.rotation.set(-0.12, Math.PI, 0); g.add(sp);
    // chair
    g.add(cyl(0.3, 0.3, 0.08, chairM, c.chair[0], 0.55, c.chair[1] + 0.05, 20));
    g.add(box(0.6, 0.7, 0.08, chairM, c.chair[0], 0.95, c.chair[1] - 0.3));
    // judge
    const p = makePerson(col, c.id + 1);
    p.position.set(c.chair[0], 0.04, c.chair[1] + 0.1); p.rotation.y = 0; snapSit(p, true);
    g.add(p);
    pickables.push({ obj: p, seat: c.seat });
    // colour strip along the back wall + glass plate
    const stripM = new THREE.MeshStandardMaterial({ color: col, emissive: col, roughness: 0.4 });
    reg.emissive(stripM, 0.7, 2.0);
    g.add(box(c.w - 1.4, 0.1, 0.06, stripM, c.x, 5.25, c.z0 + 0.15));
    g.add(box(c.w - 1.4, 0.06, 0.06, stripM, c.x, 0.06, c.z1 - 0.12));
    const tex = labelTexture(`${c.id} · ${c.seat}`, { fg: '#0f172a', bg: '#f8fafc', border: seatC[c.seat], w: 640, h: 128, font: '800 70px Inter, system-ui, sans-serif' });
    const pm = new THREE.MeshStandardMaterial({ map: tex, emissiveMap: tex, emissive: 0xffffff, roughness: 0.5 });
    reg.emissive(pm, 0.35, 0.9);
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 0.84), pm);
    plate.position.set(c.x, 4.35, c.z1 + 0.09); plate.rotation.y = Math.PI; g.add(plate);
    const plate2 = plate.clone(); plate2.position.z = c.z1 - 0.09; plate2.rotation.y = 0; g.add(plate2);
    // hearing ring
    const ringM = new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.8, roughness: 0.4, transparent: true, opacity: 0.85 });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.72, 40), ringM);
    ring.rotation.x = -Math.PI / 2; ring.position.set(c.hear[0], 0.03, c.hear[1]); g.add(ring);
    const light = reg.light(new THREE.PointLight(col, 1, 13, 1.8), 0, 12, false);
    light.position.set(c.x, 4.6, (c.z0 + c.z1) / 2); g.add(light);
    judges[c.seat] = { person: p, strip: stripM, ring, light };
  }

  // ---------------------------------------------------------------- trading pit
  const D = L.desks;
  const topM = std(0xf3f5f9, 0.32, 0.05), legM = std(0x8a95a6, 0.4, 0.6);
  const tops = new THREE.InstancedMesh(new THREE.BoxGeometry(2.4, 0.06, 1.6), topM, D.length);
  const skirts = new THREE.InstancedMesh(new THREE.BoxGeometry(2.3, 0.5, 0.05), std(0xc4ccd8, 0.5), D.length);
  const legs = new THREE.InstancedMesh(new THREE.BoxGeometry(0.06, 0.72, 1.5), legM, D.length * 2);
  const mons = new THREE.InstancedMesh(new THREE.BoxGeometry(0.62, 0.4, 0.04), std(0x0b1220, 0.3, 0.5), D.length * 2);
  const scrM = new THREE.MeshStandardMaterial({ map: chartTexture(3), emissiveMap: chartTexture(3), emissive: 0xffffff, roughness: 0.3 });
  reg.emissive(scrM, 0.7, 1.5);
  const screens = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.56, 0.34), scrM, D.length * 2);
  const chairs = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.27, 0.27, 0.07, 16), chairM, D.length);
  const backs = new THREE.InstancedMesh(new THREE.BoxGeometry(0.5, 0.55, 0.07), chairM, D.length);
  const m4 = new THREE.Matrix4();
  const deskRings: THREE.Mesh[] = [];
  D.forEach((d, i) => {
    tops.setMatrixAt(i, m4.makeTranslation(d.x, 0.76, d.z));
    skirts.setMatrixAt(i, m4.makeTranslation(d.x, 0.5, d.z + 0.55));
    for (const k of [-1, 1]) {
      legs.setMatrixAt(i * 2 + (k > 0 ? 1 : 0), m4.makeTranslation(d.x + k * 1.12, 0.36, d.z));
      const mx = d.x + k * 0.36, mz = d.z - 0.3;
      mons.setMatrixAt(i * 2 + (k > 0 ? 1 : 0), m4.makeTranslation(mx, 1.13, mz));
      screens.setMatrixAt(i * 2 + (k > 0 ? 1 : 0), new THREE.Matrix4().makeRotationY(Math.PI).setPosition(mx, 1.13, mz + 0.023));
    }
    chairs.setMatrixAt(i, m4.makeTranslation(d.seat[0], 0.5, d.seat[1] + 0.05));
    backs.setMatrixAt(i, m4.makeTranslation(d.seat[0], 0.85, d.seat[1] + 0.34));
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.76, 32), new THREE.MeshStandardMaterial({ color: 0x34d399, emissive: 0x34d399, emissiveIntensity: 1.4, transparent: true, opacity: 0.9 }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(d.stand[0], 0.03, d.stand[1]); ring.visible = false; g.add(ring); deskRings.push(ring);
    // number plate
    const nt = labelTexture(String(i + 1).padStart(2, '0'), { fg: '#334155', bg: '#e8edf4', w: 96, h: 64, font: '700 40px ui-monospace, Menlo, monospace' });
    const np = new THREE.Mesh(new THREE.PlaneGeometry(0.3, 0.2), new THREE.MeshStandardMaterial({ map: nt, roughness: 0.6 }));
    np.rotation.x = -Math.PI / 2; np.position.set(d.x, 0.797, d.z + 0.55); g.add(np);
  });
  [tops, skirts, legs, mons, screens, chairs, backs].forEach((m) => { m.castShadow = true; m.receiveShadow = true; g.add(m); });
  // colonnade — single line x -17.3
  const colM = std(0xf4f6f9, 0.5);
  for (const z of L.pit.colonnade.zs) {
    g.add(cyl(0.4, 0.42, 11.5, colM, L.pit.colonnade.x, 5.75, z, 24));
    const band = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x38bdf8, roughness: 0.4 });
    reg.emissive(band, 0.5, 2.2);
    g.add(cyl(0.43, 0.43, 0.12, band, L.pit.colonnade.x, 2.4, z, 24));
  }
  // corridor pillars
  for (const x of [-38, -12, 12, 38]) g.add(cyl(0.45, 0.47, 11.5, colM, x, 5.75, L.corridor.mid, 24));

  // ---------------------------------------------------------------- east wing
  const [ex0, ez0, ex1, ez1] = L.executive.box;
  const walnut = std(0x4a3427, 0.45, 0.1), carpet = std(0x2a1f3a, 0.9);
  const ef = new THREE.Mesh(new THREE.PlaneGeometry(ex1 - ex0, ez1 - ez0), carpet); ef.rotation.x = -Math.PI / 2; ef.position.set((ex0 + ex1) / 2, 0.02, (ez0 + ez1) / 2); ef.receiveShadow = true; g.add(ef);
  const dz = L.executive.door_z;
  g.add(box(1.8, 0.1, 4.6, walnut, 38.5, 0.8, dz, true)); g.add(box(1.6, 0.75, 4.4, walnut, 38.5, 0.4, dz, true));
  g.add(box(0.6, 1.3, 0.6, std(0x2a1f3a), 41.0, 0.9, dz));
  g.add(box(0.7, 3.2, 10.5, walnut, 41.6, 1.6, -5.8, true));
  const ceoCol = hex(seatC.NAVEED);
  const ceo = makePerson(ceoCol, 3, 0x2b2140); ceo.position.set(40.5, 0.04, dz); ceo.rotation.y = -Math.PI / 2; snapSit(ceo, true); g.add(ceo);
  pickables.push({ obj: ceo, seat: 'NAVEED' });
  g.add(cyl(0.34, 0.34, 0.08, chairM, 40.5, 0.55, dz)); g.add(box(0.08, 0.8, 0.7, chairM, 40.9, 0.95, dz));
  const plq = labelTexture('NAVEED · CEO', { fg: '#f3e8ff', bg: '#241a36', border: seatC.NAVEED, w: 512, h: 112, font: '800 58px Inter, system-ui, sans-serif' });
  const plqM = new THREE.MeshStandardMaterial({ map: plq, emissiveMap: plq, emissive: 0xffffff, roughness: 0.5 }); reg.emissive(plqM, 0.5, 1.1);
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 0.57), plqM); plate.position.set(41.28, 3.6, -5.8); plate.rotation.y = -Math.PI / 2; g.add(plate);
  const cRingM = new THREE.MeshStandardMaterial({ color: ceoCol, emissive: ceoCol, emissiveIntensity: 0.9, transparent: true, opacity: 0.85 });
  const cRing = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.72, 40), cRingM); cRing.rotation.x = -Math.PI / 2; cRing.position.set(30.4, 0.04, dz); g.add(cRing);
  const rug = new THREE.Mesh(new THREE.CircleGeometry(2.4, 48), std(0x3b2a58, 0.95)); rug.rotation.x = -Math.PI / 2; rug.position.set(30.4, 0.03, dz); g.add(rug);
  const ceoLight = reg.light(new THREE.PointLight(ceoCol, 1, 18, 1.8), 0, 16, true); ceoLight.position.set(32, 5.2, dz); g.add(ceoLight);

  // vault
  const [vx0, vz0, vx1, vz1] = L.vault.box;
  const steelF = new THREE.Mesh(new THREE.PlaneGeometry(vx1 - vx0, vz1 - vz0), std(0x7d8898, 0.35, 0.7)); steelF.rotation.x = -Math.PI / 2; steelF.position.set((vx0 + vx1) / 2, 0.02, (vz0 + vz1) / 2); g.add(steelF);
  const drawerM = std(0xaab4c3, 0.35, 0.8);
  const drawers = new THREE.InstancedMesh(new THREE.BoxGeometry(0.85, 0.42, 0.1), drawerM, 2 * 22 * 5);
  let di = 0;
  for (const zz of [3.3, 9.9]) {
    const face = zz === 3.3 ? 4.15 : 9.05;
    g.add(box(19.4, 2.6, 0.8, std(0x475467, 0.5, 0.6), 31.7, 1.3, zz === 3.3 ? 3.7 : 9.5, true));
    for (let i = 0; i < 22; i++) for (let j = 0; j < 5; j++) drawers.setMatrixAt(di++, m4.makeTranslation(22.6 + i * 0.86, 0.3 + j * 0.5, face + (zz === 3.3 ? 0.05 : -0.05)));
  }
  g.add(drawers);
  const wheel = new THREE.Group();
  const wm = std(0xc7d0dc, 0.3, 0.9);
  wheel.add(new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.14, 12, 40), wm));
  for (let i = 0; i < 4; i++) { const s = box(3.0, 0.12, 0.12, wm); s.rotation.z = (i * Math.PI) / 4; wheel.add(s); }
  wheel.add(new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.3, 20), wm));
  wheel.rotation.y = -Math.PI / 2; wheel.rotation.order = 'YXZ'; wheel.position.set(vx1 - 0.3, 2.4, L.vault.door_z); g.add(wheel);
  const vlab = labelTexture('VAULT · PLAYBOOK', { fg: '#e2e8f0', bg: '#0f172a', border: '#94a3b8', w: 512, h: 96, font: '800 50px Inter, system-ui, sans-serif' });
  const vlm = new THREE.MeshStandardMaterial({ map: vlab, emissiveMap: vlab, emissive: 0xffffff }); reg.emissive(vlm, 0.5, 1.1);
  const vpl = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 0.68), vlm); vpl.position.set(vx1 - 0.2, 4.5, L.vault.door_z); vpl.rotation.y = -Math.PI / 2; g.add(vpl);
  const vl = reg.light(new THREE.PointLight(0x9ecbff, 1, 16, 1.8), 0, 8, true); vl.position.set(31, 4.8, 6.6); g.add(vl);

  // debate chamber
  const [bx0, bz0, bx1, bz1] = L.debate.box;
  const df = new THREE.Mesh(new THREE.PlaneGeometry(bx1 - bx0, bz1 - bz0), std(0x20263a, 0.55, 0.1)); df.rotation.x = -Math.PI / 2; df.position.set((bx0 + bx1) / 2, 0.02, (bz0 + bz1) / 2); g.add(df);
  const [cx, cz] = L.debate.center;
  g.add(cyl(2.6, 2.6, 0.12, std(0x3a2d44, 0.35, 0.2), cx, 0.78, cz, 48)); g.add(cyl(0.5, 0.7, 0.75, std(0x2a2033, 0.5), cx, 0.38, cz, 20));
  const ringL = new THREE.MeshStandardMaterial({ color: 0xc084fc, emissive: 0xc084fc, roughness: 0.4 }); reg.emissive(ringL, 0.6, 2.4);
  const tor = new THREE.Mesh(new THREE.TorusGeometry(2.1, 0.05, 8, 64), ringL); tor.rotation.x = Math.PI / 2; tor.position.set(cx, 0.86, cz); g.add(tor);
  const order = ['ATLAS', 'QUANTA', 'MERIDIAN', 'VOLTA', 'VECTOR', 'DROSOPHILA'];
  const delegates: Record<string, Person> = {};
  L.debate.seats.forEach((s, i) => {
    const seat = order[i];
    const p = makePerson(hex(seatC[seat]), i + 2);
    p.position.set(s[0], 0.04, s[1]); p.rotation.y = Math.atan2(cx - s[0], cz - s[1]); snapSit(p, true); g.add(p);
    g.add(cyl(0.3, 0.3, 0.07, chairM, s[0], 0.5, s[1], 16));
    delegates[seat] = p; pickables.push({ obj: p, seat });
  });
  const dl = reg.light(new THREE.PointLight(0xc084fc, 1, 18, 1.8), 0, 14, true); dl.position.set(cx, 5, cz); g.add(dl);

  // ---------------------------------------------------------------- arrival hall
  const [sx, sz] = L.decor.security_desk;
  g.add(box(4.0, 1.05, 1.0, std(0xe6ebf2, 0.35, 0.1), sx, 0.53, sz, true)); g.add(box(4.1, 0.06, 1.1, std(0x1b2333, 0.3, 0.4), sx, 1.08, sz));
  const sm = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x38bdf8 }); reg.emissive(sm, 0.5, 2.0);
  g.add(box(3.9, 0.05, 0.05, sm, sx, 0.2, sz + 0.52));
  const guard = makePerson(0x94a3b8, 1, 0x223046); guard.position.set(sx, 0, sz - 0.9); guard.rotation.y = 0; g.add(guard);
  const turnM = std(0x1b2333, 0.4, 0.4), armM = new THREE.MeshStandardMaterial({ color: 0x9be7ff, transparent: true, opacity: 0.45 });
  L.decor.turnstiles.forEach((t, i) => {
    g.add(box(0.5, 1.0, 1.2, turnM, t.x, 0.5, t.z, true));
    const led = new THREE.MeshStandardMaterial({ color: 0x111111, emissive: i < 2 ? 0x22c55e : 0xef4444 }); reg.emissive(led, 0.8, 2.5);
    g.add(box(0.3, 0.05, 0.6, led, t.x, 1.03, t.z)); g.add(box(0.05, 0.4, 0.8, armM, t.x + (t.x > 0 ? -0.5 : 0.5) * 0.3, 0.8, t.z));
  });
  const sofaBase = std(0x2b3a55, 0.7), sofaCush = std(0xc9d3e3, 0.8);
  L.decor.sofas.forEach((s) => {
    g.add(box(s.w, 0.45, s.d, sofaBase, s.x, 0.25, s.z, true));
    const horiz = s.w > s.d;
    g.add(box(horiz ? s.w : 0.3, 0.55, horiz ? 0.3 : s.d, sofaBase, s.x + (horiz ? 0 : (s.x < 0 ? -0.4 : 0.4)), 0.75, s.z + (horiz ? 0.4 : 0), true));
    g.add(box(horiz ? s.w - 0.2 : s.w - 0.4, 0.18, horiz ? s.d - 0.4 : s.d - 0.2, sofaCush, s.x + (horiz ? 0 : (s.x < 0 ? 0.1 : -0.1)), 0.55, s.z - (horiz ? 0.1 : 0)));
  });
  const potM = std(0xdfe5ee, 0.5), leafA = std(0x3f7d4e, 0.8);
  reg.on((t) => leafA.color.set(t === 'night' ? 0x2b5a3a : 0x3f7d4e));
  L.decor.planters.forEach((p) => {
    g.add(cyl(0.5, 0.42, 0.7, potM, p.x, 0.35, p.z, 16));
    const l = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62, 1), leafA); l.position.set(p.x, 1.2, p.z); l.scale.y = 1.3; l.castShadow = true; g.add(l);
  });
  // concourse light strips
  const strip = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x38bdf8 }); reg.emissive(strip, 0.3, 1.8);
  const [c0, cz0, c1, cz1] = L.concourse;
  g.add(box(0.06, 0.06, cz1 - cz0, strip, c0, 0.05, (cz0 + cz1) / 2)); g.add(box(0.06, 0.06, cz1 - cz0, strip, c1, 0.05, (cz0 + cz1) / 2));

  // neon pools in pit + lobby
  for (const [x, z, col] of [[-30, -3, 0x38bdf8], [-8, -3, 0x22d3ee], [-30, 8, 0x60a5fa], [-8, 8, 0x22d3ee], [-8, 22, 0x34d399], [-32, 22, 0x38bdf8], [16, 6, 0x38bdf8], [-4, -15, 0xa78bfa], [-26, -15, 0x38bdf8], [22, -15, 0x38bdf8]] as [number, number, number][]) {
    const pl = reg.light(new THREE.PointLight(col, 1, 20, 1.8), 0, 9); pl.position.set(x, 6.5, z); g.add(pl);
  }

  const cRing2 = cRing;
  return {
    group: g, judges, ceo: { person: ceo, ring: cRing2, light: ceoLight }, delegates, deskRings, pickables, guard,
    update(t: number) {
      for (const j of Object.values(judges)) j.ring.rotation.z = t * 0.6;
      cRing2.rotation.z = -t * 0.6;
      wheel.rotation.z = Math.sin(t * 0.2) * 0.3;
    },
  };
}
