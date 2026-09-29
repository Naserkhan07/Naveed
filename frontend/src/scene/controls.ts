import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export const FLY_LIMITS = { x: 150, zMin: -110, zMax: 130, yMin: 0.7, yMax: 150 };
export const SPEED_MIN = 1.5, SPEED_MAX = 90;
export const ORBIT_MIN = 1.6, ORBIT_MAX = 340;

/** Orbit camera + presets + a 360° free-fly viewer (drag to look, WASD/arrows, Q/E down/up, Shift x2.6, Alt x0.35, wheel = speed). */
export class CameraRig {
  camera: THREE.PerspectiveCamera;
  orbit: OrbitControls;
  freefly = false;
  speed = 18;
  yaw = 0; pitch = 0;
  keys = new Set<string>();
  preset: string | null = 'overview';
  private anim: { t: number; dur: number; p0: THREE.Vector3; t0: THREE.Vector3; p1: THREE.Vector3; t1: THREE.Vector3 } | null = null;
  private dragging = false;
  private last = { x: 0, y: 0 };
  onChange: () => void = () => {};

  constructor(camera: THREE.PerspectiveCamera, private dom: HTMLElement) {
    this.camera = camera;
    this.orbit = new OrbitControls(camera, dom);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.08;
    this.orbit.minDistance = ORBIT_MIN;
    this.orbit.maxDistance = ORBIT_MAX;
    this.orbit.maxPolarAngle = Math.PI * 0.495;
    this.orbit.zoomSpeed = 1.1;
    this.orbit.addEventListener('start', () => { if (!this.anim) this.preset = this.preset; });

    dom.addEventListener('pointerdown', this.onDown);
    window.addEventListener('pointermove', this.onMove);
    window.addEventListener('pointerup', this.onUp);
    dom.addEventListener('wheel', this.onWheel, { passive: false });
    window.addEventListener('keydown', this.onKey(true));
    window.addEventListener('keyup', this.onKey(false));
    window.addEventListener('blur', () => this.keys.clear());
  }

  dispose() {
    this.dom.removeEventListener('pointerdown', this.onDown);
    window.removeEventListener('pointermove', this.onMove);
    window.removeEventListener('pointerup', this.onUp);
    this.dom.removeEventListener('wheel', this.onWheel);
    this.orbit.dispose();
  }

  // ------------------------------------------------------------------ presets
  goPreset(name: string, spec: { pos: [number, number, number]; look: [number, number, number] }, instant = false) {
    if (this.freefly) this.setFreeFly(false);          // presets drop out of the free-fly mode
    this.preset = name;
    const p1 = new THREE.Vector3(...spec.pos), t1 = new THREE.Vector3(...spec.look);
    if (instant) {
      this.camera.position.copy(p1); this.orbit.target.copy(t1); this.orbit.update(); return;
    }
    this.anim = { t: 0, dur: 1.4, p0: this.camera.position.clone(), t0: this.orbit.target.clone(), p1, t1 };
    this.orbit.enabled = false;
  }

  setFreeFly(on: boolean) {
    if (on === this.freefly) return;
    this.anim = null;
    this.freefly = on;
    if (on) {
      const d = new THREE.Vector3(); this.camera.getWorldDirection(d);
      this.yaw = Math.atan2(-d.x, -d.z);
      this.pitch = Math.asin(THREE.MathUtils.clamp(d.y, -1, 1));
      this.orbit.enabled = false;
      this.preset = null;
    } else {
      const d = new THREE.Vector3(); this.camera.getWorldDirection(d);
      this.orbit.target.copy(this.camera.position).addScaledVector(d, Math.max(12, Math.min(60, this.camera.position.y * 1.2)));
      this.orbit.enabled = true; this.orbit.update();
    }
    this.onChange();
  }

  // --------------------------------------------------------------- free-fly input
  private onDown = (e: PointerEvent) => {
    if (!this.freefly) return;
    this.dragging = true; this.last = { x: e.clientX, y: e.clientY };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };
  private onMove = (e: PointerEvent) => {
    if (!this.freefly || !this.dragging) return;
    this.yaw -= (e.clientX - this.last.x) * 0.0032;
    this.pitch = THREE.MathUtils.clamp(this.pitch - (e.clientY - this.last.y) * 0.0032, -1.55, 1.55);
    this.last = { x: e.clientX, y: e.clientY };
  };
  private onUp = () => { this.dragging = false; };
  private onWheel = (e: WheelEvent) => {
    if (!this.freefly) return;
    e.preventDefault();
    this.speed = THREE.MathUtils.clamp(this.speed * Math.exp(-e.deltaY * 0.0012), SPEED_MIN, SPEED_MAX);
    this.onChange();
  };
  private onKey = (down: boolean) => (e: KeyboardEvent) => {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'q', 'e', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift', 'alt'].includes(k)) {
      if (this.freefly) e.preventDefault();
      if (down) this.keys.add(k); else this.keys.delete(k);
    }
  };

  update(dt: number) {
    if (this.anim) {
      const a = this.anim;
      a.t = Math.min(1, a.t + dt / a.dur);
      const k = a.t < 0.5 ? 4 * a.t ** 3 : 1 - (-2 * a.t + 2) ** 3 / 2;
      this.camera.position.lerpVectors(a.p0, a.p1, k);
      this.orbit.target.lerpVectors(a.t0, a.t1, k);
      this.camera.lookAt(this.orbit.target);
      if (a.t >= 1) { this.anim = null; this.orbit.enabled = true; this.orbit.update(); }
      return;
    }
    if (!this.freefly) { this.orbit.update(); return; }
    const c = this.camera;
    c.rotation.set(this.pitch, this.yaw, 0, 'YXZ');
    const k = this.keys;
    let mult = this.speed;
    if (k.has('shift')) mult *= 2.6;
    if (k.has('alt')) mult *= 0.35;
    const fwd = new THREE.Vector3(-Math.sin(this.yaw) * Math.cos(this.pitch), Math.sin(this.pitch), -Math.cos(this.yaw) * Math.cos(this.pitch));
    const right = new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    const mv = new THREE.Vector3();
    if (k.has('w') || k.has('arrowup')) mv.add(fwd);
    if (k.has('s') || k.has('arrowdown')) mv.sub(fwd);
    if (k.has('d') || k.has('arrowright')) mv.add(right);
    if (k.has('a') || k.has('arrowleft')) mv.sub(right);
    if (k.has('e')) mv.y += 1;
    if (k.has('q')) mv.y -= 1;
    if (mv.lengthSq() > 0) c.position.addScaledVector(mv.normalize(), mult * dt);
    c.position.x = THREE.MathUtils.clamp(c.position.x, -FLY_LIMITS.x, FLY_LIMITS.x);
    c.position.z = THREE.MathUtils.clamp(c.position.z, FLY_LIMITS.zMin, FLY_LIMITS.zMax);
    c.position.y = THREE.MathUtils.clamp(c.position.y, FLY_LIMITS.yMin, FLY_LIMITS.yMax);
  }
}
