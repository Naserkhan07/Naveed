import * as THREE from 'three';
import { labelTexture } from './textures';

/* shared geometry — every person reuses these, so 60 people stay cheap */
const G = {
  torso: new THREE.CapsuleGeometry(0.2, 0.36, 4, 10),
  hips: new THREE.CapsuleGeometry(0.19, 0.06, 4, 10),
  head: new THREE.SphereGeometry(0.14, 16, 12),
  neck: new THREE.CylinderGeometry(0.05, 0.06, 0.09, 8),
  hair: new THREE.SphereGeometry(0.152, 14, 9, 0, Math.PI * 2, 0, Math.PI * 0.56),
  upperArm: new THREE.CapsuleGeometry(0.056, 0.26, 3, 8),
  foreArm: new THREE.CapsuleGeometry(0.048, 0.24, 3, 8),
  hand: new THREE.SphereGeometry(0.05, 8, 6),
  thigh: new THREE.CapsuleGeometry(0.085, 0.34, 3, 8),
  shin: new THREE.CapsuleGeometry(0.07, 0.34, 3, 8),
  shoe: new THREE.BoxGeometry(0.12, 0.07, 0.26),
  tie: new THREE.BoxGeometry(0.05, 0.3, 0.02),
  card: new THREE.BoxGeometry(0.34, 0.24, 0.02),
  cardFace: new THREE.PlaneGeometry(0.3, 0.2),
};
const SKIN = [0xf1c9a5, 0xd9a577, 0xb07c54, 0x8a5a3b, 0xe8b894];
const HAIR = [0x1b1b1f, 0x3a2a1f, 0x5a4632, 0x777777, 0x24160e];
const skinMats = SKIN.map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.75 }));
const hairMats = HAIR.map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.9 }));
const shoeMat = new THREE.MeshStandardMaterial({ color: 0x0d1117, roughness: 0.5 });
const suitMats = new Map<number, { jacket: THREE.MeshStandardMaterial; trouser: THREE.MeshStandardMaterial }>();
const shirtMat = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.7 });
function suit(c: number) {
  let s = suitMats.get(c);
  if (!s) {
    const col = new THREE.Color(c);
    s = { jacket: new THREE.MeshStandardMaterial({ color: col, roughness: 0.68 }), trouser: new THREE.MeshStandardMaterial({ color: col.clone().multiplyScalar(0.82), roughness: 0.72 }) };
    suitMats.set(c, s);
  }
  return s;
}

const HIT = new THREE.CylinderGeometry(0.55, 0.55, 2.1, 8);
const HIT_MAT = new THREE.MeshBasicMaterial({ visible: false });
const HIP_Y = 0.94;            // standing hip height
const SIT_DROP = 0.30;         // hips drop when seated

interface Rig {
  root: THREE.Group;           // body (drops when sitting)
  thighL: THREE.Group; thighR: THREE.Group; shinL: THREE.Group; shinR: THREE.Group;
  armL: THREE.Group; armR: THREE.Group; elbowL: THREE.Group; elbowR: THREE.Group;
  torso: THREE.Group; head: THREE.Group; card: THREE.Group;
}
export interface Person extends THREE.Group {
  userData: {
    rig: Rig; accentMat: THREE.MeshStandardMaterial; cardMat: THREE.MeshStandardMaterial; label?: THREE.Sprite; labelKey?: string;
    sitting: boolean; sitK: number; phase: number; speed: number; carry: boolean; seed: number; labelBase: number;
  };
}

function limb(geo: THREE.BufferGeometry, mat: THREE.Material, len: number) {
  const m = new THREE.Mesh(geo, mat); m.position.y = -len / 2; return m;
}

/** articulated figure: hips, torso, head, two-segment arms and legs. accent = seat colour (tie + carried ticket card) */
export function makePerson(accent: string | number, seed = 0, suitColor = 0x1e2735): Person {
  const g = new THREE.Group() as Person;
  const S = suit(suitColor);
  const accentMat = new THREE.MeshStandardMaterial({ color: accent, roughness: 0.4, metalness: 0.1, emissive: accent, emissiveIntensity: 0.35 });
  const root = new THREE.Group(); root.position.y = HIP_Y; g.add(root);

  const hips = new THREE.Mesh(G.hips, S.trouser); hips.position.y = 0.02; root.add(hips);
  const torso = new THREE.Group(); torso.position.y = 0.06; root.add(torso);
  const chest = new THREE.Mesh(G.torso, S.jacket); chest.position.y = 0.3; chest.scale.z = 0.78; chest.castShadow = true; torso.add(chest);
  const tie = new THREE.Mesh(G.tie, accentMat); tie.position.set(0, 0.36, 0.152); torso.add(tie);
  const collar = new THREE.Mesh(G.neck, shirtMat); collar.position.y = 0.6; torso.add(collar);
  const head = new THREE.Group(); head.position.y = 0.72; torso.add(head);
  const skull = new THREE.Mesh(G.head, skinMats[seed % skinMats.length]); skull.scale.set(0.95, 1.08, 1); skull.castShadow = true; head.add(skull);
  const hair = new THREE.Mesh(G.hair, hairMats[seed % hairMats.length]); hair.position.y = 0.012; hair.rotation.x = -0.28; head.add(hair);

  const arm = (side: number) => {
    const sh = new THREE.Group(); sh.position.set(side * 0.27, 0.5, 0); torso.add(sh);
    sh.add(limb(G.upperArm, S.jacket, 0.3));
    const el = new THREE.Group(); el.position.y = -0.3; sh.add(el);
    el.add(limb(G.foreArm, S.jacket, 0.26));
    const hd = new THREE.Mesh(G.hand, skinMats[seed % skinMats.length]); hd.position.y = -0.3; el.add(hd);
    return { sh, el };
  };
  const leg = (side: number) => {
    const th = new THREE.Group(); th.position.set(side * 0.105, -0.02, 0); root.add(th);
    th.add(limb(G.thigh, S.trouser, 0.42));
    const kn = new THREE.Group(); kn.position.y = -0.43; th.add(kn);
    kn.add(limb(G.shin, S.trouser, 0.42));
    const shoe = new THREE.Mesh(G.shoe, shoeMat); shoe.position.set(0, -0.46, 0.05); kn.add(shoe);
    return { th, kn };
  };
  const aL = arm(-1), aR = arm(1), lL = leg(-1), lR = leg(1);

  // the trade being carried: a slim ticket board in the seat colour
  const card = new THREE.Group();
  const cm = new THREE.Mesh(G.card, new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.5 })); card.add(cm);
  const cardMat = new THREE.MeshStandardMaterial({ color: accent, emissive: accent, emissiveIntensity: 0.9 });
  const face = new THREE.Mesh(G.cardFace, cardMat); face.position.z = 0.012; card.add(face);
  card.position.set(0, 0.34, 0.34); card.rotation.x = -0.35; card.visible = false; torso.add(card);
  root.traverse((o) => { if ((o as THREE.Mesh).isMesh) o.castShadow = false; });
  // generous invisible hit volume so a person is easy to click, even far away or while walking
  const hit = new THREE.Mesh(HIT, HIT_MAT); hit.position.y = 1.0; g.add(hit);

  g.userData = {
    rig: { root, thighL: lL.th, thighR: lR.th, shinL: lL.kn, shinR: lR.kn, armL: aL.sh, armR: aR.sh, elbowL: aL.el, elbowR: aR.el, torso, head, card },
    accentMat, cardMat, sitting: false, sitK: 0, phase: seed * 0.7, speed: 0, carry: false, seed, labelBase: 2.2,
  };
  poseNow(g, 0, 0);
  return g;
}

export function setAccent(p: Person, color: string | number) {
  p.userData.accentMat.color.set(color); p.userData.accentMat.emissive.set(color);
  p.userData.cardMat.color.set(color); p.userData.cardMat.emissive.set(color);
}
export function setSitting(p: Person, sit: boolean) { p.userData.sitting = sit; }
/** seated (or standing) immediately, for static furniture people */
export function snapSit(p: Person, sit: boolean) { p.userData.sitting = sit; p.userData.sitK = sit ? 1 : 0; poseNow(p, 0, 0); }
export function setCarry(p: Person, carry: boolean) { p.userData.carry = carry; }

function poseNow(p: Person, t: number, walkAmp: number) {
  const u = p.userData, r = u.rig, s = u.sitK, ph = u.phase;
  const w = walkAmp * (1 - s);
  const sw = Math.sin(ph), sw2 = Math.sin(ph + Math.PI);
  r.root.position.y = HIP_Y - SIT_DROP * s + Math.abs(Math.cos(ph)) * 0.035 * w;
  // legs: walk swing, or thighs forward + shins down when seated
  const sitTh = -Math.PI / 2 + 0.06, sitSh = Math.PI / 2 - 0.08;
  r.thighL.rotation.x = sw * 0.62 * w + sitTh * s;
  r.thighR.rotation.x = sw2 * 0.62 * w + sitTh * s;
  r.shinL.rotation.x = Math.max(0, -Math.cos(ph + 0.4)) * 0.9 * w + sitSh * s;
  r.shinR.rotation.x = Math.max(0, -Math.cos(ph + Math.PI + 0.4)) * 0.9 * w + sitSh * s;
  // arms: swing; forward to the keyboard when seated; holding the ticket board when carrying
  const carry = u.carry && s < 0.5 ? 1 : 0;
  const armSwing = 0.55 * w * (1 - carry);
  const typ = s * (Math.sin(t * 9 + u.seed) * 0.06);
  r.armL.rotation.x = sw2 * armSwing + (-0.95) * s + (-1.0) * carry * (1 - s) + typ;
  r.armR.rotation.x = sw * armSwing + (-0.95) * s + (-1.0) * carry * (1 - s) - typ;
  r.armL.rotation.z = -0.06 - 0.06 * carry; r.armR.rotation.z = 0.06 + 0.06 * carry;
  r.elbowL.rotation.x = -0.25 * (1 - s - carry) - 0.7 * s - 0.9 * carry;
  r.elbowR.rotation.x = -0.25 * (1 - s - carry) - 0.7 * s - 0.9 * carry;
  r.torso.rotation.x = 0.03 + 0.06 * s + 0.05 * w;
  r.torso.rotation.y = Math.sin(ph) * 0.09 * w;
  r.head.rotation.x = -0.03 * s + (s > 0.5 ? Math.sin(t * 0.7 + u.seed) * 0.05 : 0);
  r.card.visible = carry > 0;
}

/** per-render-frame animation: speed = m/s actually moved; sitting blends smoothly */
export function animatePerson(p: Person, t: number, dt: number, speed: number) {
  const u = p.userData;
  u.speed += (speed - u.speed) * Math.min(1, dt * 10);
  u.sitK += ((u.sitting ? 1 : 0) - u.sitK) * Math.min(1, dt * 6);
  if (Math.abs(u.sitK - (u.sitting ? 1 : 0)) < 0.01) u.sitK = u.sitting ? 1 : 0;
  const moving = u.speed > 0.08;
  if (moving) u.phase += dt * (3.2 + Math.min(u.speed, 2.6) * 2.3);
  else u.phase += (Math.round(u.phase / Math.PI) * Math.PI - u.phase) * Math.min(1, dt * 8); // settle both feet together
  poseNow(p, t, moving ? Math.min(1, u.speed / 0.9) : 0);
}

const labelCache = new Map<string, THREE.SpriteMaterial>();
/** asset / role name floating above the head — always drawn on top so it can be read through any structure */
export function setLabel(p: Person, text: string, color: string, small = false) {
  if (!text) { if (p.userData.label) { p.remove(p.userData.label); p.userData.label = undefined; p.userData.labelKey = ''; } return; }
  const key = text + color + (small ? 's' : '');
  if (p.userData.labelKey === key) return;
  let mat = labelCache.get(key);
  if (!mat) {
    const tex = labelTexture(text, { fg: '#f8fafc', bg: small ? 'rgba(15,23,42,0.78)' : 'rgba(10,15,26,0.92)', border: color, w: 400, h: 96, font: '700 42px Inter, system-ui, sans-serif' });
    mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false });
    labelCache.set(key, mat);
  }
  if (!p.userData.label) { const sp = new THREE.Sprite(mat); sp.renderOrder = 20; p.userData.label = sp; p.add(sp); }
  else p.userData.label.material = mat;
  p.userData.labelKey = key;
}
/** keep the label readable at any distance (constant-ish screen size beyond ~22 m) */
export function fitLabel(p: Person, camDist: number, small: boolean) {
  const sp = p.userData.label; if (!sp) return;
  const k = Math.min(3.4, Math.max(1, camDist / 20)) * (small ? 0.78 : 1);
  sp.scale.set(1.9 * k, 0.456 * k, 1);
  sp.position.y = (p.userData.sitK > 0.5 ? 1.72 : 2.18) + 0.12 * k;
  sp.visible = camDist < 110;
}
