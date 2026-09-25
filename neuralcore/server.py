"""NeuralCore live server — talk to the brain in your browser.

The ONLY thing this server loads is brain file(s): weights + vocabulary
vectors + state. There is no database, no retrieval, no training data —
the answers come purely from learned neural dynamics.

Run:
    python3 -m neuralcore.server [path/to/brain.ncb] [--port 8000]

Endpoints:
    GET  /              chat UI
    GET  /brain         brain info (params, vocab, bytes)
    POST /ask           {"question": "..."} -> answer from the dynamics
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from .brain import Brain
from .output import ask, parse_question
from .perception import normalize_word

DEFAULT_BRAIN = "neuralcore_output/brain-grown.ncb"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NeuralCore — ask the brain</title>
<style>
  :root { --bg:#0b0e14; --panel:#121722; --line:#232b3b; --ink:#dfe6f3;
          --dim:#8b96ab; --acc:#5eead4; --warn:#f0ab5e; --bad:#f28b82; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
  .wrap { max-width:840px; margin:0 auto; padding:24px 16px 90px; }
  header h1 { margin:0 0 4px; font-size:22px; letter-spacing:.3px; }
  header h1 span { color:var(--acc); }
  header p { margin:0; color:var(--dim); font-size:13px; }
  .badges { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 6px; }
  .badge { border:1px solid var(--line); background:var(--panel); color:var(--dim);
           border-radius:999px; padding:4px 12px; font-size:12px; }
  .badge b { color:var(--ink); font-weight:600; }
  .badge.ok b { color:var(--acc); }
  select { background:var(--panel); color:var(--ink); border:1px solid var(--line);
           border-radius:8px; padding:6px 10px; font-size:13px; margin-top:10px; }
  .chat { margin-top:18px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:78%; padding:10px 14px; border-radius:14px; border:1px solid var(--line); }
  .msg.you { align-self:flex-end; background:#1a2233; border-color:#2a3650; }
  .msg.bot { align-self:flex-start; background:var(--panel); }
  .msg .ans { font-size:17px; font-weight:600; }
  .msg .ans.none { color:var(--dim); font-weight:400; font-style:italic; }
  .msg .meta { color:var(--dim); font-size:12px; margin-top:4px; }
  .bar { height:4px; background:#1c2433; border-radius:2px; margin-top:6px; overflow:hidden; }
  .bar i { display:block; height:100%; background:var(--acc); }
  .cands { margin-top:6px; display:flex; flex-wrap:wrap; gap:6px; }
  .cand { border:1px solid var(--line); border-radius:6px; padding:2px 8px;
          font-size:12px; color:var(--dim); }
  .hint { color:var(--dim); font-size:12.5px; margin-top:10px; }
  .hint code { color:var(--acc); background:#141b28; padding:1px 5px; border-radius:4px; }
  form { position:fixed; left:0; right:0; bottom:0; background:linear-gradient(
         transparent, var(--bg) 30%); padding:18px 16px 22px; }
  .inbar { max-width:840px; margin:0 auto; display:flex; gap:8px; }
  input { flex:1; background:var(--panel); border:1px solid var(--line); color:var(--ink);
          border-radius:12px; padding:12px 14px; font-size:15px; outline:none; }
  input:focus { border-color:var(--acc); }
  button { background:var(--acc); color:#06281f; border:0; border-radius:12px;
           padding:12px 20px; font-weight:700; font-size:15px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Neural<span>Core</span> — ask the brain</h1>
    <p>Knowledge lives only in neural weights. No database. No retrieval. No training data.</p>
    <div class="badges" id="badges"></div>
    <select id="brainSel"></select>
    <div class="hint">
      It only knows what it <b>experienced</b> — and says “I don’t know” otherwise.
      Ask like: <code>what does the fox absorb?</code> ·
      <code>what does marble contain?</code> ·
      <code>what does the sun heat?</code> ·
      <code>what does the baker make?</code> ·
      <code>what can the bird do?</code>
      (small brains also understand inverse forms like <code>what heats the water?</code>)
    </div>
  </header>
  <div class="chat" id="chat"></div>
</div>
<form id="f"><div class="inbar">
  <input id="q" autocomplete="off" placeholder="ask the brain…">
  <button id="go">Ask</button>
</div></form>
<script>
const chat = document.getElementById('chat');
const form = document.getElementById('f');
const input = document.getElementById('q');
const go = document.getElementById('go');
const sel = document.getElementById('brainSel');

function add(el){ chat.appendChild(el); window.scrollTo(0, document.body.scrollHeight); }
function bubble(cls, html){
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = html;
  add(d);
  return d;
}
function ask(q){
  bubble('you', escapeHtml(q));
  input.value=''; go.disabled = true; input.disabled = true;
  const thinking = bubble('bot', '<span class="ans none">…dynamics running</span>');
  fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'},
                 body: JSON.stringify({question:q, brain: sel.value})})
    .then(r=>r.json())
    .then(d=>{
      let html = '';
      if (d.answer === null){
        html += `<div class="ans none">${escapeHtml(d.detail || "I don't know.")}</div>`;
      } else {
        const pct = Math.round(100*Math.max(0,Math.min(1,d.confidence)));
        html += `<div class="ans">${escapeHtml(d.answer)}</div>
                 <div class="meta">confidence ${pct}%</div>
                 <div class="bar"><i style="width:${pct}%"></i></div>`;
        if (d.candidates && d.candidates.length > 1){
          html += '<div class="cands">' + d.candidates.map(c=>
            `<span class="cand">${escapeHtml(c[0])} ${Math.round(100*c[1])}%</span>`).join('') + '</div>';
        }
      }
      if (d.detail && d.answer !== null) html += `<div class="meta">${escapeHtml(d.detail)}</div>`;
      thinking.innerHTML = html;
    })
    .catch(()=>{ thinking.innerHTML = '<div class="ans none">server error</div>'; })
    .finally(()=>{ go.disabled=false; input.disabled=false; input.focus(); });
}
function escapeHtml(s){ return String(s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

form.addEventListener('submit', e=>{ e.preventDefault(); const q=input.value.trim(); if(q) ask(q); });
sel.addEventListener('change', ()=>{
  fetch('/brain?name='+encodeURIComponent(sel.value)).then(r=>r.json()).then(drawInfo);
});
function drawInfo(b){
  document.getElementById('badges').innerHTML = [
    `<div class="badge ok"><b>${b.label}</b></div>`,
    `<div class="badge"><b>${b.parameters.toLocaleString()}</b> synapses</div>`,
    `<div class="badge"><b>${(b.bytes/1e6).toFixed(2)} MB</b> brain file</div>`,
    `<div class="badge"><b>${b.vocabulary}</b> experienced concepts</div>`,
    `<div class="badge"><b>${b.hidden}</b> neurons</div>`,
    `<div class="badge ok"><b>0</b> databases · <b>0</b> retrievals</div>`,
  ].join('');
}
fetch('/brain').then(r=>r.json()).then(b=>{
  drawInfo(b);
  for (const n of b.available){
    const o = document.createElement('option');
    o.value = n; o.textContent = n.replace('.ncb','').replace('brain-','');
    if (n === b.name) o.selected = true;
    sel.appendChild(o);
  }
});
ask('what does the fire burn?');
</script>
</body>
</html>"""


class Server:
    """Lazy multi-brain holder. Brains are loaded once, from .ncb files only."""

    def __init__(self, brain_dir: str = "neuralcore_output"):
        self.brain_dir = brain_dir
        files = [f for f in os.listdir(brain_dir) if f.endswith(".ncb")] \
            if os.path.isdir(brain_dir) else []
        # newest-trained brain is the default (last in the list)
        self.available = sorted(files, key=lambda f: os.path.getmtime(os.path.join(brain_dir, f)))
        self._cache: dict[str, Brain] = {}
        if not self.available:
            raise SystemExit(f"no .ncb brain files in {brain_dir}/ — train one first: "
                             "python3 -m neuralcore.experiments")

    def get(self, name: str | None) -> tuple[str, Brain]:
        name = name if name in self.available else self.available[-1]  # default: newest
        if name not in self._cache:
            self._cache[name] = Brain.load(os.path.join(self.brain_dir, name))
        return name, self._cache[name]

    def info(self, name: str | None) -> dict:
        name, brain = self.get(name)
        return {
            "name": name,
            "label": name.replace(".ncb", "").replace("brain-", "").replace("brain", "toy brain"),
            "parameters": brain.net.parameter_count(),
            "hidden": brain.net.hidden_size(),
            "vocabulary": len(brain.vocab),
            "bytes": os.path.getsize(os.path.join(self.brain_dir, name)),
            "available": self.available,
        }


def candidates(brain: Brain, subject: str, relation: str, top: int = 3):
    """Top-k decodings of the output activation — transparency for testing."""
    if not brain.vocab.has(subject) or not brain.vocab.has(relation):
        return []
    perc = brain.perceiver()
    x = perc.encode_query(subject, relation, state_h=None)
    y = brain.net.forward(x)
    M = brain.vocab._matrix()
    norms = np.linalg.norm(M, axis=1)
    sims = (M @ y) / (norms * np.linalg.norm(y) + 1e-9)
    order = np.argsort(-sims)[:top]
    return [(brain.vocab.order[i], float(sims[i])) for i in order]


class Handler(BaseHTTPRequestHandler):
    core: "Server"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            return
        if self.path.startswith("/brain"):
            name = None
            if "name=" in self.path:
                name = self.path.split("name=", 1)[1].split("&")[0]
                from urllib.parse import unquote
                name = unquote(name)
            body = json.dumps(self.core.info(name)).encode()
            self._send(200, body, "application/json")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/ask":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, json.dumps({"answer": None, "detail": "bad JSON"}).encode(),
                       "application/json")
            return

        question = str(payload.get("question", "")).strip()
        name = payload.get("brain")
        brain_name, brain = self.core.get(name if name else None)

        if not question:
            self._send(200, json.dumps({"answer": None, "detail": "ask something"}).encode(),
                       "application/json")
            return

        parsed = parse_question(question)
        if parsed is None:
            self._send(200, json.dumps({
                "answer": None,
                "detail": "I couldn't parse that question form. Try: what does the X <verb>?",
            }).encode(), "application/json")
            return

        subject, relation = parsed
        inv_form = relation.startswith("inv_")
        head = relation[4:] if inv_form else relation
        if not brain.vocab.has(subject):
            self._send(200, json.dumps({
                "answer": None,
                "detail": f"I have never experienced the word '{subject}'.",
            }).encode(), "application/json")
            return
        if not brain.vocab.has(head):
            self._send(200, json.dumps({
                "answer": None,
                "detail": f"I have never experienced the word '{head}'.",
            }).encode(), "application/json")
            return
        if inv_form and not brain.vocab.has(relation):
            # this brain learned facts in one direction only
            fwd = ask(brain, subject, head)
            detail = ("this brain learned facts one-directional — ask "
                      f"'what does {subject} {head}?' — and it says: ")
            if fwd.concept:
                self._send(200, json.dumps({
                    "answer": fwd.concept, "confidence": fwd.confidence,
                    "detail": detail, "candidates": candidates(brain, subject, head),
                }).encode(), "application/json")
            else:
                self._send(200, json.dumps({
                    "answer": None,
                    "detail": f"I don't know. (this brain learned facts one-directional; "
                              f"try 'what does {subject} {head}?')",
                }).encode(), "application/json")
            return

        ans = ask(brain, subject, relation)
        cands = candidates(brain, subject, relation)
        detail = f"brain: {brain_name.replace('.ncb','').replace('brain-','')}"
        self._send(200, json.dumps({
            "answer": ans.concept,
            "confidence": ans.confidence,
            "detail": detail,
            "candidates": cands,
        }).encode(), "application/json")

    def log_message(self, fmt, *args):  # quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("brain", nargs="?", default=None, help=".ncb file (default: newest in output dir)")
    ap.add_argument("--dir", default="neuralcore_output")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    server_holder = Server(args.dir)
    if args.brain:
        # put the requested brain last so it becomes the default
        base = os.path.basename(args.brain)
        if base in server_holder.available:
            server_holder.available.remove(base)
        server_holder.available.append(base)

    handler = type("BoundHandler", (Handler,), {"core": server_holder})
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    name, brain = server_holder.get(None)
    print(f"NeuralCore live — brain: {name}")
    print(f"  {brain.net.parameter_count():,} synapses | {len(brain.vocab)} concepts | "
          f"{os.path.getsize(os.path.join(args.dir, name)):,} B file")
    print("  no database, no retrieval — answers come from neural dynamics only")
    print(f"  http://0.0.0.0:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
