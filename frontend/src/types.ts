export type Theme = 'day' | 'night';
export type XZ = [number, number];

export interface Rect { kind: 'rect'; x0: number; z0: number; x1: number; z1: number; tag: string; seat?: string }
export interface Circle { kind: 'circle'; x: number; z: number; r: number; tag: string }
export type Solid = Rect | Circle;
export interface Wall { kind: 'rect'; x0: number; z0: number; x1: number; z1: number; tag: string }

export interface Cabin {
  id: number; seat: string; x: number; w: number; z0: number; z1: number;
  desk: XZ; chair: XZ; hear: XZ; door: XZ; outside: XZ;
}
export interface Desk { id: number; row: number; block: number; pod: number; x: number; z: number; w: number; d: number; seat: XZ; stand: XZ }
export interface Opening { id: string; kind: string; axis: 'x' | 'z'; x: number; z: number; w: number }
export interface TickerSpec { x: number; z: number; y: number; w: number }

export interface Layout {
  hall: [number, number, number, number];
  ceiling: number;
  palette: { walls: number; floor_a: string; floor_b: string; grid: string; inlay_a: number; inlay_b: number; plaza: number; seat_colors: Record<string, string> };
  cabins: Cabin[];
  desks: Desk[];
  corridor: { z0: number; z1: number; mid: number };
  pit: { rows: number[]; blocks: number[]; colonnade: { x: number; zs: number[] }; boulevard: number[] };
  concourse: number[];
  executive: { box: number[]; door_z: number; ceo: XZ };
  vault: { box: number[]; door_z: number };
  debate: { box: number[]; door_z: number; center: XZ; radius: number; seats: XZ[] };
  gates: { entry: { x: number; w: number; z: number }; exit: { x: number; w: number; z: number } };
  south_wall_z: number;
  walls: Wall[];
  openings: Opening[];
  props: Solid[];
  decor: {
    video_walls: { id: string; title: string; x: number; z: number; y: number; w: number; h: number; facing: string }[];
    signs: { text: string; x: number; y: number; z: number; w: number; facing: string }[];
    tickers: { corridor: TickerSpec; pit: TickerSpec; lobby: TickerSpec };
    curb_z: number; road: number[];
    taxis: { x: number; z: number; rot: number }[];
    lamps: { x: number; z: number }[];
    trees: { x: number; z: number }[];
    fountain: { x: number; z: number; r: number };
    sofas: { x: number; z: number; w: number; d: number }[];
    planters: { x: number; z: number }[];
    security_desk: XZ;
    turnstiles: { x: number; z: number }[];
    pathways: number[][];
    aprons: number[][];
  };
  waypoints: Record<string, XZ>;
  cameras: Record<string, { pos: [number, number, number]; look: [number, number, number] }>;
}

export interface WalkerPose { id: string; x: number; z: number; h: number; sit: boolean; l: string; c: string; k: string; st: string; gone: boolean }
export interface Frame {
  t: number; sim: number; speed: number; walkers: WalkerPose[];
  judges: Record<string, { state: string; ticket: string | null; say?: { ok: boolean; conf: number; text: string; sym: string; tid: string } }>;
  thinking: { seat: string; color: string };
  debate: { speaker: string | null; text: string };
  brain_state: string;
  extra?: Extra;
}
export interface TapeRow { s: string; c: string; p: number; ch: number; r: string }
export interface VoteCard { seat: string; cabin: number; vote: 'approve' | 'reject'; score: number; reason: string; label: string; ms?: number; confidence?: number; thesis?: string; risk?: string }
export interface Mt5Info { status: string; symbol: string; side: string; lots: number; retcode: number | null; msg: string; mt5_ticket: number | null; price: number | null }
export interface OrderCard {
  id: string; sym: string; cls: string; dir: 'LONG' | 'SHORT'; emitter: string; conviction: number; entry: number; sl: number; tp: number;
  rr: number; desk: number; status: string; stage: string; cabin: number; approvals: number; votes: VoteCard[];
  ceo: { vote: string; reason: string; label: string; ms?: number; confidence?: number; thesis?: string; risk?: string } | null; mt5?: Mt5Info | null; verdict: string; path: string; paper: string; r: number | null; t0: number;
  info: Record<string, unknown>; regime: string; dopamine: number | null; features: Record<string, number>;
}
export interface FlySnap {
  state: string; threshold: number; fatigue: number; dopamine: number; baseline: number; updates: number;
  focus: { s: string; hunger: number; dir: number; heading_deg: number; g: number[]; pn: number[]; kc: number[]; mb: number[] };
  watch: { s: string; h: number; missing: string[] }[];
  funnel: {
    scans: number; candidates: Record<string, number>; emitted: Record<string, number>;
    stages: Record<string, { in: number; out: number }>; blocked: Record<string, number>; corr_band_blocked: number; corr_stale_blocked: number;
  };
  mbon_names: string[];
  correlation: { age_s: number; fresh: boolean; n_strong: number; strong_pairs: { a: string; b: string; rho: number; band: string }[]; ccy_strength: Record<string, number> };
  microstructure: { reachable: boolean; polls: number; errors: number; symbols: Record<string, { pressure: number; ofi: number; weight: number }> };
  mode: string;
}
export interface Extra {
  fly: FlySnap; orders: OrderCard[]; tape: TapeRow[]; mode: string;
  events: { t: number; kind: string; text: string; ticket: string | null }[];
  lessons: { t: number; seat: string; kind: string; text: string }[];
  stats: Record<string, number>;
  chatroom: { t: number; name: string; text: string; color: string; label?: string }[];
  seats: SeatInfo[];
  llm?: { enabled: boolean; label: string; stats: Record<string, number>; last_error?: string; waiting: number; relay?: { available: boolean; queued: number; running: number; done: number; failed: number; last_error: string }; seat_endpoints: Record<string, string> };
  mt5?: { connected: boolean; auto: boolean };
  record?: string;
}
export interface SeatInfo { id: string; cabin: number; persona: string; role: string; bio: string; lens: string; color: string; state: string; ticket: string | null; label: string; messages: number; model: string; bias: number; notes: string[] }
export interface ChatMsg { role: 'user' | 'assistant'; content: string; label?: string; ms?: number; seat?: string; color?: string }

export interface TradeDetail {
  card: OrderCard;
  verdict_why: string;
  approved_by: { seat: string; confidence: number }[];
  rejected_by: { seat: string; confidence: number }[];
  levels: { entry: number; sl: number; tp: number; risk_abs: number; risk_pct: number | null; reward_abs: number; atr: number; rr: number };
  found: { emitter: string; conviction: number; regime: string; info: Record<string, unknown>; top_senses: { name: string; v: number }[]; mbon: { name: string; v: number }[]; sim_time: number };
  facts: Record<string, string | number>;
  timeline: { stage: string; t: number }[];
  events: { t: number; kind: string; text: string }[];
  outcome: { paper: string; how: string; r: number | null; t_fill: number | null; t_resolved: number | null; verdict_was: string | null; note: string } | null;
  mt5: Mt5Info | null;
  walker: { desk: number; status: string; stage: string };
}
