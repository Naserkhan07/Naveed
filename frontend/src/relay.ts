/** Browser relay worker. The server has no internet, so cabin verdicts, CEO rulings and the fly's debate are queued on the
 *  server; this page (which does have internet) picks them up, sends each to a keyless free model and posts the answer back.
 *  It runs for as long as the page is open. */
import { useEffect, useState } from 'react';
import { postJSON } from './api';
import { askBrowser } from './llm';

interface Job { id: number; messages: { role: string; content: string }[]; max_tokens: number }
const CONCURRENCY = 3;

export interface RelayStat { served: number; failed: number; last_error: string; active: number }

export function useRelayWorker(): RelayStat {
  const [st, setSt] = useState<RelayStat>({ served: 0, failed: 0, last_error: '', active: 0 });
  useEffect(() => {
    let alive = true;
    let active = 0;
    const bump = (p: Partial<RelayStat>) => setSt((s) => ({ ...s, ...p, active }));
    async function run(j: Job) {
      active++; bump({});
      try {
        const r = await askBrowser(j.messages, j.max_tokens, true);
        await postJSON('/api/relay/result', { id: j.id, text: r.text });
        setSt((s) => ({ ...s, served: s.served + 1, last_error: '' }));
      } catch (e) {
        await postJSON('/api/relay/result', { id: j.id, error: (e as Error).message }).catch(() => {});
        setSt((s) => ({ ...s, failed: s.failed + 1, last_error: (e as Error).message }));
      } finally { active--; bump({}); }
    }
    async function loop() {
      while (alive) {
        try {
          const free = CONCURRENCY - active;
          const r = await postJSON<{ jobs: Job[] }>('/api/relay/next', { max: Math.max(0, free) });   // also serves as the heartbeat
          if (free > 0) r.jobs.forEach((j) => { void run(j); });
        } catch { /* server restarting */ }
        await new Promise((res) => setTimeout(res, 700));
      }
    }
    void loop();
    return () => { alive = false; };
  }, []);
  return st;
}
