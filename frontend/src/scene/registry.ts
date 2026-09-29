import * as THREE from 'three';
import type { Theme } from '../types';

type EmMat = THREE.MeshStandardMaterial | THREE.MeshPhysicalMaterial;

/** collects everything whose look depends on ☀ DAY / ☾ NIGHT */
export class ThemeReg {
  private em: { m: EmMat; day: number; night: number }[] = [];
  private li: { l: THREE.Light; day: number; night: number }[] = [];
  private fn: ((t: Theme) => void)[] = [];
  emissive(m: EmMat, day: number, night: number) { this.em.push({ m, day, night }); m.emissiveIntensity = night; return m; }
  /** point lights are expensive (every fragment loops over them): only those flagged `keep` stay on, the rest are emissive-only */
  light<T extends THREE.Light>(l: T, day: number, night: number, keep = false): T {
    this.li.push({ l, day, night }); l.intensity = night;
    if ((l as unknown as THREE.PointLight).isPointLight && !keep) l.visible = false;
    return l;
  }
  on(f: (t: Theme) => void) { this.fn.push(f); }
  apply(t: Theme) {
    const n = t === 'night';
    for (const e of this.em) e.m.emissiveIntensity = n ? e.night : e.day;
    for (const l of this.li) { l.l.intensity = n ? l.night : l.day; }
    for (const f of this.fn) f(t);
  }
}

export const box = (w: number, h: number, d: number, mat: THREE.Material, x = 0, y = 0, z = 0, shadow = false) => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = shadow; m.receiveShadow = true;
  return m;
};
export const cyl = (rt: number, rb: number, h: number, mat: THREE.Material, x = 0, y = 0, z = 0, seg = 20) => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat);
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true;
  return m;
};
export const std = (color: number | string, rough = 0.6, metal = 0, extra: THREE.MeshStandardMaterialParameters = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal, ...extra });
