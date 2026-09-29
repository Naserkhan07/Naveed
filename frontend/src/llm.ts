/** Browser-side language-model client. Used when the server itself has no internet: the server hands back the finished
 *  prompt (persona + live floor status + history) and THIS browser sends it to a keyless free model. No keys involved. */
import { postJSON } from './api';

export interface Msg { role: string; content: string }
export interface Served { seat: string; answer: string; label: string; ms: number; color: string; ok?: boolean; why?: string; messages?: Msg[] }

const TIMEOUT_MS = 30000;
const PROVIDERS: { name: string; url: string; body: (m: Msg[], n?: number) => unknown }[] = [
  { name: 'pollinations', url: 'https://text.pollinations.ai/openai', body: (m, n) => ({ model: 'openai', messages: m, temperature: 0.6, private: true, max_tokens: n }) },
  { name: 'llm7', url: 'https://api.llm7.io/v1/chat/completions', body: (m, n) => ({ model: 'default', messages: m, temperature: 0.6, max_tokens: n }) },
];

async function one(p: (typeof PROVIDERS)[number], messages: Msg[], maxTokens?: number): Promise<string> {
  const ctl = new AbortController();
  const to = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(p.url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(p.body(messages, maxTokens)), signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const raw = await r.text();
    let txt = raw;
    try { txt = JSON.parse(raw).choices[0].message.content; } catch { /* some deployments answer in plain text */ }
    txt = (txt ?? '').trim();
    if (!txt || txt.startsWith('{"error')) throw new Error('empty reply');
    return txt;
  } finally { clearTimeout(to); }
}

/** anonymous free tiers rate-limit hard (HTTP 429): background verdict jobs wait and retry instead of failing */
async function withBackoff(fn: () => Promise<string>, patient: boolean): Promise<string> {
  for (let i = 0; ; i++) {
    try { return await fn(); }
    catch (e) {
      if (!patient || i >= 4 || !/429|503/.test((e as Error).message)) throw e;
      await new Promise((r) => setTimeout(r, 4000 + i * 4000));
    }
  }
}

/** try every keyless provider from the browser; resolves with the reply or rejects with every error joined */
export async function askBrowser(messages: Msg[], maxTokens?: number, patient = false): Promise<{ text: string; label: string }> {
  const errs: string[] = [];
  for (const p of PROVIDERS) {
    try { return { text: await withBackoff(() => one(p, messages, maxTokens), patient), label: `free:gpt (${p.name}, via your browser)` }; }
    catch (e) { errs.push(`${p.name}: ${(e as Error).name === 'AbortError' ? 'timed out' : (e as Error).message}`); }
  }
  throw new Error(errs.join(' · '));
}

export function unreachableText(serverWhy: string, browserWhy: string): string {
  return `I can't reach a language model right now, so I won't guess.\nFrom the server: ${serverWhy}\nFrom your browser: ${browserWhy}\nBoth need internet access to a free model; ask again once one of them is online.`;
}

/** Turn a server reply into a final one: if the server had no model, let the browser make the call. */
export async function resolveReply(r: Served, question: string, remember: boolean): Promise<Served> {
  if (r.ok !== false || !r.messages) return r;
  const t0 = performance.now();
  try {
    const b = await askBrowser(r.messages);
    if (remember) postJSON('/api/chat/remember', { seat_id: r.seat, text: b.text, label: b.label, question }).catch(() => {});
    return { ...r, answer: b.text, label: b.label, ms: Math.round(performance.now() - t0), ok: true, messages: undefined };
  } catch (e) {
    const why = r.why || 'no provider answered';
    return { ...r, answer: unreachableText(why, (e as Error).message), label: 'no language model reachable', ok: false, messages: undefined };
  }
}
