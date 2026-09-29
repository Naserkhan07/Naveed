import * as THREE from 'three';
import type { Layout, Wall } from '../types';
import { ThemeReg, box, cyl, std } from './registry';
import { canvas, canvasTexture, daylightWindowTexture, labelTexture, rng, stoneTexture, windowMaskTexture, windowTexture } from './textures';

export interface Shared {
  wall: THREE.MeshStandardMaterial; glass: THREE.MeshStandardMaterial; frame: THREE.MeshStandardMaterial;
  floor: THREE.MeshStandardMaterial; steel: THREE.MeshStandardMaterial; dark: THREE.MeshStandardMaterial;
}

export function sharedMaterials(L: Layout): Shared {
  const stone = stoneTexture(L.palette.floor_a, L.palette.floor_b, L.palette.grid);
  const [x0, z0, x1, z1] = L.hall;
  stone.repeat.set((x1 - x0) / 23, (z1 - z0) / 23);
  return {
    wall: std(L.palette.walls, 0.88, 0),
    glass: new THREE.MeshStandardMaterial({ color: 0xcfe8ff, transparent: true, opacity: 0.17, roughness: 0.04, metalness: 0.1, side: THREE.DoubleSide, depthWrite: false }),
    frame: std(0xaab4c3, 0.35, 0.65),
    floor: new THREE.MeshStandardMaterial({ map: stone, roughness: 0.24, metalness: 0.02, envMapIntensity: 0.7 }),
    steel: std(0x9aa5b4, 0.4, 0.7),
    dark: std(0x1b2333, 0.55, 0.2),
  };
}

const H = 11.5;

/** floor, pathway inlays, walls (white shell, glass cabins/chambers), lintels, cornice, ceiling structure */
export function buildShell(L: Layout, S: Shared, reg: ThemeReg): THREE.Group {
  const g = new THREE.Group();
  const [x0, z0, x1, z1] = L.hall;
  // floor
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, z1 - z0), S.floor);
  floor.rotation.x = -Math.PI / 2; floor.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2); floor.receiveShadow = true;
  g.add(floor);
  // pathway inlays 0xe2e8f1 / 0xe9eef5
  L.decor.pathways.forEach((p, i) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(p[2] - p[0], p[3] - p[1]), std(i % 2 ? L.palette.inlay_b : L.palette.inlay_a, 0.3));
    m.rotation.x = -Math.PI / 2; m.position.set((p[0] + p[2]) / 2, 0.012, (p[1] + p[3]) / 2); m.receiveShadow = true; g.add(m);
  });
  // plaza apron 0xd9dee6
  for (const a of L.decor.aprons) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(a[2] - a[0], a[3] - a[1]), std(L.palette.plaza, 0.75));
    m.rotation.x = -Math.PI / 2; m.position.set((a[0] + a[2]) / 2, 0.006, (a[1] + a[3]) / 2); m.receiveShadow = true; g.add(m);
  }
  // walls
  const solidWhite = (w: Wall, h: number, y0 = 0) => {
    const b = box(w.x1 - w.x0, h, w.z1 - w.z0, S.wall, (w.x0 + w.x1) / 2, y0 + h / 2, (w.z0 + w.z1) / 2, true);
    g.add(b);
  };
  const glassPane = (w: Wall, h: number, y0: number) => {
    const dx = w.x1 - w.x0, dz = w.z1 - w.z0;
    g.add(box(dx, h, dz, S.glass, (w.x0 + w.x1) / 2, y0 + h / 2, (w.z0 + w.z1) / 2));
    // aluminium mullion posts + head/sill rails
    const along = dx > dz ? 'x' : 'z';
    const len = along === 'x' ? dx : dz;
    const n = Math.max(1, Math.round(len / 2.4));
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const px = along === 'x' ? w.x0 + dx * t : (w.x0 + w.x1) / 2;
      const pz = along === 'z' ? w.z0 + dz * t : (w.z0 + w.z1) / 2;
      g.add(box(0.07, h, 0.07, S.frame, px, y0 + h / 2, pz));
    }
    g.add(box(dx + (along === 'x' ? 0.07 : 0.1), 0.09, dz + (along === 'z' ? 0.07 : 0.1), S.frame, (w.x0 + w.x1) / 2, y0 + h, (w.z0 + w.z1) / 2));
  };
  for (const w of L.walls) {
    if (w.tag === 'shell') solidWhite(w, H);
    else if (w.tag === 'cabin' || w.tag === 'glass') glassPane(w, 5.6, 0);
    else { solidWhite(w, 1.05); glassPane(w, 5.2, 1.05); }
  }
  // lintels over gates/doors
  for (const o of L.openings) {
    const t = o.kind === 'gate' ? 0.4 : o.kind === 'glass_door' ? 0.12 : 0.4;
    const top = o.kind === 'gate' ? H : o.kind === 'glass_door' ? 5.6 : 6.25;
    const y0 = o.kind === 'gate' ? 4.4 : o.kind === 'glass_door' ? 3.3 : 3.4;
    const mat = o.kind === 'glass_door' ? S.glass : S.wall;
    const [w, d] = o.axis === 'x' ? [o.w, t] : [t, o.w];
    g.add(box(w, top - y0, d, mat, o.x, (top + y0) / 2, o.z, true));
    // door frame posts + header bar
    const fw = 0.12;
    if (o.axis === 'x') {
      g.add(box(fw, y0, t + 0.06, S.frame, o.x - o.w / 2, y0 / 2, o.z)); g.add(box(fw, y0, t + 0.06, S.frame, o.x + o.w / 2, y0 / 2, o.z));
      g.add(box(o.w + fw, 0.1, t + 0.06, S.frame, o.x, y0, o.z));
    } else {
      g.add(box(t + 0.06, y0, fw, S.frame, o.x, y0 / 2, o.z - o.w / 2)); g.add(box(t + 0.06, y0, fw, S.frame, o.x, y0 / 2, o.z + o.w / 2));
      g.add(box(t + 0.06, 0.1, o.w + fw, S.frame, o.x, y0, o.z));
    }
    if (o.kind === 'gate') {
      const col = o.id === 'entry_gate' ? 0x22c55e : 0xef4444;
      const m = new THREE.MeshStandardMaterial({ color: 0x111111, emissive: col, roughness: 0.4 });
      reg.emissive(m, 0.9, 2.2);
      g.add(box(o.w, 0.12, 0.12, m, o.x, y0 - 0.12, o.z + 0.2));
    }
  }
  // cornice + ceiling structure (open truss grid + light panels; no solid roof so the overview stays readable)
  const trim = std(0xe6eaf0, 0.6);
  g.add(box(x1 - x0 + 0.8, 0.35, 0.5, trim, (x0 + x1) / 2, H + 0.1, z0 - 0.25));
  g.add(box(x1 - x0 + 0.8, 0.35, 0.5, trim, (x0 + x1) / 2, H + 0.1, L.south_wall_z + 0.25));
  g.add(box(0.5, 0.35, z1 - z0, trim, x0 - 0.25, H + 0.1, (z0 + L.south_wall_z) / 2));
  g.add(box(0.5, 0.35, z1 - z0, trim, x1 + 0.25, H + 0.1, (z0 + L.south_wall_z) / 2));
  const beamM = std(0xdfe4ec, 0.5, 0.2);
  const panelM = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff6e6, roughness: 0.4 });
  reg.emissive(panelM, 0.25, 0.9);
  const panels = new THREE.InstancedMesh(new THREE.BoxGeometry(3.4, 0.08, 1.1), panelM, 12 * 6);
  const mtx = new THREE.Matrix4(); let pi = 0;
  for (let i = 0; i < 12; i++) for (let j = 0; j < 6; j++) {
    const x = x0 + 4.5 + i * 7.7, z = z0 + 4 + j * 9.6;
    mtx.setPosition(x, H - 0.55, z); panels.setMatrixAt(pi++, mtx);
  }
  g.add(panels);
  for (let j = 0; j < 6; j++) g.add(box(x1 - x0, 0.16, 0.2, beamM, (x0 + x1) / 2, H - 0.4, z0 + 4 + j * 9.6 + 0.9));
  return g;
}

/** ground, road, curb, street lamps, trees, fountain, taxis, distant city */
export function buildOutdoor(L: Layout, reg: ThemeReg): { group: THREE.Group; water: THREE.Mesh; update(t: number): void } {
  const g = new THREE.Group();
  const D = L.decor;
  // ground
  const groundMat = std(0x8d99a8, 0.95);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1600, 1600), groundMat);
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.03; ground.receiveShadow = true; g.add(ground);
  reg.on((t) => groundMat.color.set(t === 'night' ? 0x101826 : 0x9aa8b6));
  // road + lane markings + curb
  const rd = D.road;
  const asphalt = std(0x2f3541, 0.9);
  const road = new THREE.Mesh(new THREE.PlaneGeometry(rd[2] - rd[0] + 500, rd[3] - rd[1]), asphalt);
  road.rotation.x = -Math.PI / 2; road.position.set(0, 0.004, (rd[1] + rd[3]) / 2); road.receiveShadow = true; g.add(road);
  const dash = std(0xf1f5f9, 0.6);
  for (let x = -240; x < 240; x += 6) g.add(box(2.6, 0.01, 0.16, dash, x, 0.012, (rd[1] + rd[3]) / 2));
  g.add(box(rd[2] - rd[0] + 500, 0.22, 0.4, std(0xc4cad4, 0.7), 0, 0.11, D.curb_z));
  // street lamps
  const poleM = std(0x29313f, 0.5, 0.6);
  const lampM = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffd9a0, roughness: 0.4 });
  reg.emissive(lampM, 0, 3.2);
  D.lamps.forEach((p, i) => {
    g.add(cyl(0.07, 0.09, 5.4, poleM, p.x, 2.7, p.z, 8));
    g.add(box(1.0, 0.09, 0.12, poleM, p.x + 0.4, 5.4, p.z));
    g.add(box(0.5, 0.1, 0.3, lampM, p.x + 0.8, 5.33, p.z));
    if (i % 2 === 0) {
      const pl = reg.light(new THREE.PointLight(0xffd9a0, 1, 17, 1.6), 0, 22);
      pl.position.set(p.x + 0.8, 5.1, p.z); g.add(pl);
    }
  });
  // trees
  const trunkM = std(0x5b4636, 0.9), leafM = std(0x3f7d4e, 0.85), leafM2 = std(0x4f9160, 0.85);
  reg.on((t) => { leafM.color.set(t === 'night' ? 0x1f3f2a : 0x3f7d4e); leafM2.color.set(t === 'night' ? 0x28503a : 0x4f9160); });
  D.trees.forEach((p, i) => {
    g.add(cyl(0.16, 0.22, 2.4, trunkM, p.x, 1.2, p.z, 8));
    const a = new THREE.Mesh(new THREE.IcosahedronGeometry(1.7, 1), i % 2 ? leafM : leafM2); a.position.set(p.x, 3.7, p.z); a.castShadow = true; g.add(a);
    const b = new THREE.Mesh(new THREE.IcosahedronGeometry(1.2, 1), i % 2 ? leafM2 : leafM); b.position.set(p.x + 0.6, 4.8, p.z - 0.3); b.castShadow = true; g.add(b);
  });
  // fountain
  const f = D.fountain;
  const stoneM = std(0xcfd6e0, 0.6);
  g.add(cyl(f.r, f.r + 0.15, 0.55, stoneM, f.x, 0.28, f.z, 40));
  const water = new THREE.Mesh(new THREE.CylinderGeometry(f.r - 0.25, f.r - 0.25, 0.05, 40),
    new THREE.MeshStandardMaterial({ color: 0x5aa9d8, roughness: 0.08, metalness: 0.2, transparent: true, opacity: 0.85 }));
  water.position.set(f.x, 0.52, f.z); g.add(water);
  g.add(cyl(0.35, 0.5, 1.6, stoneM, f.x, 1.1, f.z, 16));
  const jets: THREE.Mesh[] = [];
  const jetM = new THREE.MeshStandardMaterial({ color: 0xd8f0ff, transparent: true, opacity: 0.55, roughness: 0.1 });
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    const j = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.05, 1, 6), jetM);
    j.position.set(f.x + Math.cos(a) * 1.3, 0.9, f.z + Math.sin(a) * 1.3); g.add(j); jets.push(j);
  }
  const fl = reg.light(new THREE.PointLight(0x7dd3fc, 0, 12, 1.5), 0, 14); fl.position.set(f.x, 1.6, f.z); g.add(fl);
  // taxis
  const taxiM = std(0xf5c518, 0.45, 0.2), glassM = std(0x1d2733, 0.2, 0.5), tyre = std(0x0d0f14, 0.9);
  D.taxis.forEach((p) => {
    const t = new THREE.Group();
    t.add(box(4.4, 0.8, 1.9, taxiM, 0, 0.7, 0, true)); t.add(box(2.2, 0.7, 1.7, taxiM, -0.2, 1.45, 0, true));
    t.add(box(2.0, 0.5, 1.72, glassM, -0.2, 1.5, 0));
    t.add(box(0.5, 0.18, 0.3, new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff2b0, emissiveIntensity: 1.2 }), -0.2, 1.95, 0));
    for (const [x, z] of [[1.4, 0.95], [-1.4, 0.95], [1.4, -0.95], [-1.4, -0.95]]) {
      const w = cyl(0.36, 0.36, 0.28, tyre, x, 0.36, z); w.rotation.x = Math.PI / 2; t.add(w);
    }
    t.position.set(p.x, 0, p.z); t.rotation.y = p.rot; g.add(t);
  });
  // city ring
  buildCity(g, L, reg);
  return {
    group: g, water,
    update(t: number) {
      jets.forEach((j, i) => { const h = 1.0 + 0.5 * Math.sin(t * 2.2 + i); j.scale.y = h; j.position.y = 0.55 + h / 2; });
    },
  };
}

function buildCity(g: THREE.Group, L: Layout, reg: ThemeReg) {
  const r = rng(2024);
  const classes = [{ w: 20, h: 34, n: 70 }, { w: 24, h: 62, n: 50 }, { w: 22, h: 112, n: 28 }];
  const winNight = windowTexture(), winMask = windowMaskTexture(), winDay = daylightWindowTexture();
  const [hx0, hz0, hx1, hz1] = L.hall;
  const keepOut = (x: number, z: number, hw: number) => x > hx0 - 26 - hw && x < hx1 + 26 + hw && z > hz0 - 26 - hw && z < 70 + hw;
  for (const c of classes) {
    const rep = (t: THREE.Texture) => { const k = t.clone(); k.needsUpdate = true; k.wrapS = k.wrapT = THREE.RepeatWrapping; k.repeat.set(c.w / 24, c.h / 48); return k; };
    const dayT = rep(winDay), nightT = rep(winNight), mask = rep(winMask);
    const mat = new THREE.MeshStandardMaterial({ map: dayT, emissiveMap: mask, emissive: 0xffffff, roughness: 0.7, metalness: 0.1 });
    reg.emissive(mat, 0, 1.6);
    reg.on((t) => { mat.map = t === 'night' ? nightT : dayT; mat.needsUpdate = true; });
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, c.n);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    let placed = 0, guard = 0;
    while (placed < c.n && guard++ < 4000) {
      const ang = r() * Math.PI * 2, rad = 110 + r() * 330;
      const x = Math.cos(ang) * rad * 1.15, z = Math.sin(ang) * rad * 0.95 + 10;
      const w = c.w * (0.8 + r() * 0.5), d = c.w * (0.8 + r() * 0.5), h = c.h * (0.75 + r() * 0.6);
      if (keepOut(x, z, Math.max(w, d) / 2)) continue;
      if (z > 40 && z < 80 && Math.abs(x) < 300) continue;      // keep the road corridor open
      p.set(x, h / 2, z); s.set(w, h, d); q.identity();
      m4.compose(p, q, s); im.setMatrixAt(placed++, m4);
    }
    im.count = placed;
    g.add(im);
  }
}
