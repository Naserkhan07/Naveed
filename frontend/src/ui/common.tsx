import type { Layout } from '../types';

export const SEAT_ORDER = ['ATLAS', 'QUANTA', 'MERIDIAN', 'VOLTA', 'VECTOR', 'NAVEED', 'DROSOPHILA'];
export const SEAT_ROLE: Record<string, string> = {
  ATLAS: 'macro & regime', QUANTA: 'statistics & edge', MERIDIAN: 'flow & structure', VOLTA: 'volatility & risk',
  VECTOR: 'momentum & timing', NAVEED: 'CEO · final ruling', DROSOPHILA: 'fly brain · hunter',
};
export const seatColor = (L: Layout | null, s: string) => L?.palette.seat_colors[s] ?? '#94a3b8';
export const fmtPx = (p: number) => (p >= 1000 ? p.toFixed(1) : p >= 100 ? p.toFixed(2) : p >= 10 ? p.toFixed(3) : p >= 1 ? p.toFixed(4) : p.toFixed(5));

export function Pill({ children, color, solid, title }: { children: React.ReactNode; color?: string; solid?: boolean; title?: string }) {
  return (
    <span className={'pill' + (solid ? ' solid' : '')} title={title} style={color ? ({ '--c': color } as React.CSSProperties) : undefined}>{children}</span>
  );
}
