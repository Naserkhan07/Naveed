/** Browser-side language-model client. Used when the server itself has no internet: the server hands back the finished
 *  prompt (persona + live floor status + history) and THIS browser sends it to a keyless free model. No keys involved. */
import { postJSON } from './api';

export interface Msg { role: string; content: string }
export interface Served { seat: string; answer: string; label: string; ms: number; color: string; ok?: boolean; why?: string; messages?: Msg[] }

const TIMEOUT_MS = 28000;

/** Keyless free tiers (2026): Pollinations serves one reasoning model anonymously (its reasoning tokens count against max_tokens, so we ask for
 *  plenty); LLM7 serves non-reasoning "turbo" models anonymously at ~10 requests/min. We rotate between them, remember which is cooling
 *  down after an HTTP 429, and never wait on a provider that is known to be limited. */
interface Prov { name: string; cool: number; call: (m: Msg[], n: number | undefined, sig: AbortSignal) => Promise<string> }

async function completion(url: string, body: unknown, sig: AbortSignal): Promise<string> {
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: sig });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const raw = await r.text();
  let txt = raw;
  try { txt = JSON.parse(raw).choices[0].message.content; } catch { /* some deployments answer in plain text */ }
  txt = (txt ?? '').trim();
  if (!txt || txt.startsWith('{"error')) throw new Error('empty reply');
  return txt;
}

let llm7Model: string | null = null;
async function pickLlm7Model(sig: AbortSignal): Promise<string> {
  if (llm7Model) return llm7Model;
  let pick = 'mistral-Nemo-Instruct-2407';
  try {
    const j = await (await fetch('https://api.llm7.io/v1/models', { signal: sig })).json();
    const free = (j.data as { id: string; model_type?: string; tier?: string; reasoning?: boolean }[]).filter((m) => (m.model_type ?? 'chat') === 'chat' && m.tier && m.tier !== 'pro');
    const best = free.find((m) => !m.reasoning && /nemo|gemma|glm|flash/i.test(m.id)) ?? free.find((m) => !m.reasoning) ?? free[0];
    if (best) pick = best.id;
  } catch { /* keep the default */ }
  return (llm7Model = pick);
}

const PROVS: Prov[] = [
  { name: 'pollinations', cool: 0, call: (m, n, sig) => completion('https://text.pollinations.ai/openai',
      { model: 'openai', messages: m, temperature: 0.5, private: true, max_tokens: Math.max((n ?? 400) * 3, 1200) }, sig) },
  { name: 'llm7', cool: 0, call: async (m, n, sig) => completion('https://api.llm7.io/v1/chat/completions',
      { model: await pickLlm7Model(sig), messages: m, temperature: 0.5, max_tokens: n ?? 600 }, sig) },
];
let rr = 0;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function attempt(p: Prov, messages: Msg[], maxTokens?: number): Promise<string> {
  const ctl = new AbortController();
  const to = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try { return await p.call(messages, maxTokens, ctl.signal); }
  catch (e) {
    const msg = (e as Error).name === 'AbortError' ? 'timed out' : (e as Error).message;
    p.cool = Date.now() + (/429/.test(msg) ? (p.name === 'llm7' ? 45000 : 16000) : 6000);
    llm7Model = /HTTP 4(00|04|22)/.test(msg) && p.name === 'llm7' ? null : llm7Model;
    throw new Error(msg);
  } finally { clearTimeout(to); }
}

/** answer from the first provider that is not cooling down (rotating to share the free quota); `patient` jobs wait out a cool-down once */
export async function askBrowser(messages: Msg[], maxTokens?: number, patient = false): Promise<{ text: string; label: string }> {
  const errs: string[] = [];
  for (let round = 0; round < (patient ? 3 : 1); round++) {
    const start = rr++;
    for (let k = 0; k < PROVS.length; k++) {
      const p = PROVS[(start + k) % PROVS.length];
      if (p.cool > Date.now()) continue;
      try { return { text: await attempt(p, messages, maxTokens), label: `free:gpt (${p.name}, via your browser)` }; }
      catch (e) { errs.push(`${p.name}: ${(e as Error).message}`); }
    }
    if (!patient) break;
    const wait = Math.min(...PROVS.map((p) => p.cool)) - Date.now();
    await sleep(Math.min(Math.max(wait, 800), 20000));
  }
  throw new Error(errs.length ? errs.join(' · ') : 'all free providers are rate-limited right now');
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
