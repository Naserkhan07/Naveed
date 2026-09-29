import * as THREE from 'three';
import { labelTexture } from './textures';

const bodyGeo = new THREE.CapsuleGeometry(0.23, 0.9, 6, 14);
const headGeo = new THREE.SphereGeometry(0.165, 20, 14);
const bandGeo = new THREE.TorusGeometry(0.245, 0.032, 8, 24);
const plateGeo = new THREE.BoxGeometry(0.14, 0.09, 0.02);
const SKIN = [0xf1c9a5, 0xd9a577, 0xb07c54, 0x8a5a3b, 0xe8b894];

export interface Person extends THREE.Group {
  userData: { body: THREE.Mesh; head: THREE.Mesh; band: THREE.Mesh; accentMat: THREE.MeshStandardMaterial; label?: THREE.Sprite; labelText?: string; sitting: boolean };
}

/** capsule body + head; the accent colour is the seat colour (band + chest plate) */
export function makePerson(accent: string | number, seed = 0, suit = 0x1e2735): Person {
  const g = new THREE.Group() as Person;
  const bodyM = new THREE.MeshStandardMaterial({ color: suit, roughness: 0.62, metalness: 0.05 });
  const accentM = new THREE.MeshStandardMaterial({ color: accent, roughness: 0.4, metalness: 0.1, emissive: accent, emissiveIntensity: 0.35 });
  const skinM = new THREE.MeshStandardMaterial({ color: SKIN[seed % SKIN.length], roughness: 0.7 });
  const body = new THREE.Mesh(bodyGeo, bodyM); body.position.y = 0.68; body.castShadow = true;
  const head = new THREE.Mesh(headGeo, skinM); head.position.y = 1.58; head.castShadow = true;
  const band = new THREE.Mesh(bandGeo, accentM); band.rotation.x = Math.PI / 2; band.position.y = 1.02;
  const plate = new THREE.Mesh(plateGeo, accentM); plate.position.set(0, 1.14, 0.225);
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), new THREE.MeshStandardMaterial({ color: [0x1b1b1f, 0x3a2a1f, 0x5a4632, 0x777777][seed % 4], roughness: 0.9 }));
  hair.position.y = 1.6; hair.rotation.x = -0.25;
  g.add(body, head, band, plate, hair);
  g.userData = { body, head, band, accentMat: accentM, sitting: false };
  return g;
}

export function setAccent(p: Person, color: string | number) {
  p.userData.accentMat.color.set(color);
  p.userData.accentMat.emissive.set(color);
}

export function setSitting(p: Person, sit: boolean) {
  if (p.userData.sitting === sit) return;
  p.userData.sitting = sit;
  p.children.forEach((c) => { if (c !== p.userData.label) c.position.y += sit ? -0.42 : 0.42; });
  p.userData.body.scale.y = sit ? 0.78 : 1;
}

const labelCache = new Map<string, THREE.SpriteMaterial>();
export function setLabel(p: Person, text: string, color: string) {
  if (!text) { if (p.userData.label) { p.remove(p.userData.label); p.userData.label = undefined; } return; }
  const key = text + color;
  if (p.userData.labelText === key) return;
  let mat = labelCache.get(key);
  if (!mat) {
    const tex = labelTexture(text, { fg: '#f8fafc', bg: 'rgba(12,18,30,0.86)', border: color, w: 384, h: 96, font: '700 44px Inter, system-ui, sans-serif' });
    mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
    labelCache.set(key, mat);
  }
  if (!p.userData.label) { p.userData.label = new THREE.Sprite(mat); p.userData.label.scale.set(1.9, 0.475, 1); p.add(p.userData.label); }
  else p.userData.label.material = mat;
  p.userData.label.position.y = p.userData.sitting ? 1.75 : 2.2;
  p.userData.labelText = key;
}
