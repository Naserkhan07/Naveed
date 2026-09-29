import { useEffect, useRef, useState } from 'react';
import type { Frame, Extra, Layout } from './types';

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}
export const fetchLayout = () => getJSON<Layout>('/api/layout');

/** Live stream: the latest frame is kept in a ref (for the 3D scene, 12 Hz); React state only follows the ~1 Hz `extra` block. */
export function useFloorStream(onFrame: (f: Frame) => void) {
  const [extra, setExtra] = useState<Extra | null>(null);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onFrame);
  cb.current = onFrame;
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;
    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (ev) => {
        const f: Frame = JSON.parse(ev.data);
        cb.current(f);
        if (f.extra) setExtra(f.extra);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = window.setTimeout(open, 1500);
      };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);
  return { extra, connected };
}
