"""The browser front end: one self-contained page, no build step, no CDN.

Naveed is a desktop overlay first — that has not changed — but the same brain is
also reachable over HTTP, so it can be opened at ``http://127.0.0.1:8765`` in a
browser (or on another machine on your LAN with ``--host 0.0.0.0``).  Everything
the page needs is in this string: the markup, the glass styling that matches the
mascot, and the small amount of JavaScript that talks to :mod:`naveed.server`.

Two rules the page obeys, and one it deliberately does not:

* it only ever fetches **relative** URLs, so it works unchanged behind a proxy
  or a tunnel (and never reaches for ``localhost`` from the browser's side);
* it never loads anything from the internet — an offline machine renders it
  exactly the same;
* it does *not* send ``X-Frame-Options``: embedding the bot in a local dashboard
  or an iframe is a feature, not a hole, because the server binds to the loopback
  interface unless you explicitly ask for more.
"""

from __future__ import annotations

__all__ = ["PAGE", "FAVICON"]

#: Inline SVG favicon (the mascot's head), so an offline page still has an icon.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='9' fill='%23ff8a3d'/%3E"
    "%3Ccircle cx='11' cy='15' r='2.4' fill='%231b1220'/%3E"
    "%3Ccircle cx='21' cy='15' r='2.4' fill='%231b1220'/%3E"
    "%3Cpath d='M13 21q3 2.6 6 0' stroke='%23ff5f8f' stroke-width='2' fill='none' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Naveed</title>
<link rel="icon" href="__FAVICON__">
<style>
  :root {
    --bg0: #12101a; --bg1: #191527; --glass: rgba(28, 24, 42, .78);
    --line: rgba(255, 255, 255, .09); --ink: #f3eefb; --dim: #a79fc0;
    --orange: #ff9a3d; --coral: #ff6f61; --pink: #ff5f8f; --mint: #6fe3c4;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font: 15px/1.5 "Segoe UI", Inter, system-ui, -apple-system, sans-serif;
    color: var(--ink); background:
      radial-gradient(900px 620px at 12% -8%, #2b1f3d 0%, transparent 60%),
      radial-gradient(760px 520px at 100% 0%, #17303a 0%, transparent 55%),
      linear-gradient(160deg, var(--bg0), var(--bg1));
    background-attachment: fixed;
    display: flex; flex-direction: column; min-height: 100%;
  }
  a { color: var(--mint); }
  .wrap { width: min(1080px, 100%); margin: 0 auto; padding: 22px 20px 26px; flex: 1;
          display: flex; flex-direction: column; gap: 16px; }
  header { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .who { display: flex; align-items: center; gap: 14px; min-width: 0; }
  h1 { font-size: 20px; margin: 0; letter-spacing: .2px; }
  .sub { color: var(--dim); font-size: 12.5px; }
  .spacer { flex: 1 1 auto; }
  .badge { display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px; font-size: 12px;
           border: 1px solid var(--line); border-radius: 999px; background: var(--glass); color: var(--dim); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); }
  .dot.ok { background: var(--mint); box-shadow: 0 0 10px rgba(111, 227, 196, .8); }
  .dot.bad { background: #ff7b7b; box-shadow: 0 0 10px rgba(255, 123, 123, .7); }
  .dot.busy { background: var(--orange); animation: pulse 1.1s infinite; }
  @keyframes pulse { 50% { opacity: .25; } }

  /* the mascot, drawn with the same palette as the desktop one */
  .mascot { width: 58px; height: 58px; position: relative; flex: none; }
  .body-s { position: absolute; inset: 4px; border-radius: 18px 18px 16px 16px;
            background: linear-gradient(180deg, var(--orange), var(--coral)); overflow: hidden;
            box-shadow: 0 10px 22px rgba(255, 111, 97, .28), inset 0 2px 6px rgba(255, 255, 255, .5); }
  .body-s::after { content: ""; position: absolute; left: 8%; right: 45%; top: 6%; height: 34%;
            background: linear-gradient(180deg, rgba(255, 255, 255, .55), transparent);
            border-radius: 40px; transform: rotate(-14deg); }
  .face { position: absolute; left: 21%; right: 21%; top: 30%; bottom: 14%;
          background: #fff; border-radius: 46% 46% 44% 44%; box-shadow: inset 0 -3px 7px rgba(0, 0, 0, .08); }
  .eye { position: absolute; top: 34%; width: 7px; height: 8px; border-radius: 50%; background: #1b1220;
         animation: blink 5.4s infinite; }
  .eye.l { left: 26%; } .eye.r { right: 26%; }
  @keyframes blink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(.12); } }
  .mouth { position: absolute; left: 50%; top: 60%; width: 12px; height: 7px; margin-left: -6px;
           border-bottom: 2.4px solid var(--pink); border-radius: 0 0 12px 12px; }
  .blush { position: absolute; top: 54%; width: 9px; height: 5px; border-radius: 50%;
           background: rgba(255, 120, 150, .5); }
  .blush.l { left: 16%; } .blush.r { right: 16%; }

  .btns { display: flex; gap: 8px; flex-wrap: wrap; }
  button { font: inherit; color: var(--ink); background: var(--glass); border: 1px solid var(--line);
           border-radius: 11px; padding: 8px 13px; cursor: pointer; transition: .16s transform, .16s border-color; }
  button:hover:not(:disabled) { border-color: rgba(255, 255, 255, .26); transform: translateY(-1px); }
  button:disabled { opacity: .45; cursor: default; }
  button.primary { background: linear-gradient(180deg, var(--orange), var(--coral)); border-color: transparent;
                   color: #241224; font-weight: 650; }
  button.ghost { background: transparent; }
  button.chip { font-size: 12.5px; padding: 6px 11px; border-radius: 999px; color: var(--dim); }

  .grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; flex: 1; align-items: start; }
  @media (max-width: 860px) { .grid { grid-template-columns: minmax(0, 1fr); } }
  .card { background: var(--glass); border: 1px solid var(--line); border-radius: 16px;
          backdrop-filter: blur(12px); padding: 14px; }
  .card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .11em; color: var(--dim);
             margin: 0 0 10px; font-weight: 600; }

  #log { height: min(46vh, 380px); overflow-y: auto; display: flex; flex-direction: column; gap: 9px;
         scroll-behavior: smooth; }
  .row { display: flex; flex-direction: column; gap: 3px; padding: 9px 11px; border-radius: 12px;
         background: rgba(255, 255, 255, .035); border: 1px solid transparent; }
  .row .k { font-size: 10.5px; text-transform: uppercase; letter-spacing: .1em; color: var(--dim); }
  .row.say { background: rgba(255, 154, 61, .10); border-color: rgba(255, 154, 61, .22); }
  .row.you { background: rgba(111, 227, 196, .10); border-color: rgba(111, 227, 196, .22); }
  .row.bad { background: rgba(255, 123, 123, .10); border-color: rgba(255, 123, 123, .25); }
  .row pre { margin: 0; font: 12.5px/1.5 ui-monospace, "Cascadia Mono", Menlo, monospace;
             white-space: pre-wrap; word-break: break-word; }
  .empty { color: var(--dim); font-size: 13.5px; padding: 6px 2px; }
  .kv { display: flex; justify-content: space-between; gap: 10px; padding: 5px 0; font-size: 13px;
        border-bottom: 1px dashed rgba(255, 255, 255, .07); }
  .kv:last-child { border-bottom: 0; }
  .kv span:first-child { color: var(--dim); }
  .kv span:last-child { text-align: right; word-break: break-word; }
  footer { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
  textarea { font: inherit; color: var(--ink); background: rgba(12, 10, 20, .55); border: 1px solid var(--line);
             border-radius: 13px; padding: 10px 12px; resize: vertical; min-height: 46px; width: 100%; }
  textarea:focus { outline: none; border-color: rgba(255, 154, 61, .55); }
  .composer { flex: 1 1 340px; display: flex; flex-direction: column; gap: 8px; }
  #question { display: none; }
  #question.on { display: flex; gap: 8px; align-items: center; }
  .note { color: var(--dim); font-size: 12px; }
  .toast { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
           background: rgba(20, 16, 30, .95); border: 1px solid var(--line); border-radius: 12px;
           padding: 10px 15px; font-size: 13px; opacity: 0; pointer-events: none; transition: .25s opacity; }
  .toast.on { opacity: 1; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="who">
      <div class="mascot" aria-hidden="true">
        <div class="body-s"></div>
        <div class="face"></div>
        <div class="eye l"></div><div class="eye r"></div>
        <div class="blush l"></div><div class="blush r"></div>
        <div class="mouth"></div>
      </div>
      <div>
        <h1>Naveed</h1>
        <div class="sub" id="sub">connecting…</div>
      </div>
    </div>
    <div class="spacer"></div>
    <span class="badge"><span class="dot" id="dot"></span><span id="state">idle</span></span>
    <div class="btns">
      <button class="ghost" id="mascot-btn" title="Open the floating mascot on this machine">Show mascot</button>
      <button class="ghost" id="quit-btn" title="Stop the local Naveed server">Quit</button>
    </div>
  </header>

  <div class="grid">
    <section class="card" style="display:flex;flex-direction:column;gap:12px">
      <h2>What is happening</h2>
      <div id="log"><div class="empty">Ask for something — Naveed looks at your screen, plans, and does it.</div></div>
      <div id="question">
        <span class="note">Naveed asked:</span><span id="question-text"></span>
        <input id="answer" placeholder="your answer" style="flex:1;min-width:120px;background:rgba(12,10,20,.55);
               border:1px solid var(--line);border-radius:11px;color:var(--ink);padding:8px 11px;font:inherit">
        <button class="primary" id="answer-btn">Send</button>
      </div>
    </section>

    <aside class="card">
      <h2>This bot</h2>
      <div class="kv"><span>model</span><span id="model">—</span></div>
      <div class="kv"><span>reachable</span><span id="reach">—</span></div>
      <div class="kv"><span>screen</span><span id="screen">—</span></div>
      <div class="kv"><span>input</span><span id="input">—</span></div>
      <div class="kv"><span>mascot</span><span id="overlay">—</span></div>
      <div class="kv"><span>routines</span><span id="skills">—</span></div>
      <div class="kv"><span>home</span><span id="home">—</span></div>
    </aside>
  </div>

  <footer>
    <div class="composer">
      <div class="btns" id="chips"></div>
      <textarea id="prompt" rows="2" placeholder="What should I do?   (Enter to send · Shift+Enter for a new line)"></textarea>
    </div>
    <div class="btns">
      <button class="ghost" id="listen" title="Dictate with the browser's speech recognition">🎙 Listen</button>
      <button id="stop">Stop</button>
      <button class="primary" id="send">Send</button>
    </div>
  </footer>
</div>
<div class="toast" id="toast"></div>

<script>
(function () {
  "use strict";
  var token = new URLSearchParams(location.search).get("token") || "";
  var cursor = 0, busy = false, listening = false, asked = "";

  function $(id) { return document.getElementById(id); }
  function toast(text) {
    var t = $("toast"); t.textContent = text; t.classList.add("on");
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); }, 2600);
  }
  async function api(path, options) {
    var opts = options || {};
    var headers = { "Content-Type": "application/json" };
    if (token) headers["X-Naveed-Token"] = token;
    var url = path + (token ? (path.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(token) : "");
    var response = await fetch(url, { method: opts.method || "GET", headers: headers, body: opts.body });
    var data = null;
    try { data = await response.json(); } catch (e) { data = { error: "the bot sent nothing readable" }; }
    return { ok: response.ok, status: response.status, data: data };
  }

  var LABELS = { say: "naveed", you: "you", status: "state", action: "action", question: "question", error: "problem" };
  function addEvent(event) {
    var log = $("log");
    var empty = log.querySelector(".empty");
    if (empty) empty.remove();
    var row = document.createElement("div");
    var cls = event.kind === "say" ? "say" : (event.kind === "you" ? "you" : (event.kind === "error" ? "bad" : ""));
    if (event.kind === "action" && event.ok === false) cls = "bad";
    row.className = "row " + cls;
    var k = document.createElement("div");
    k.className = "k"; k.textContent = LABELS[event.kind] || event.kind;
    var body = document.createElement("pre");
    body.textContent = event.text;
    row.appendChild(k); row.appendChild(body); log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    if (event.kind === "question") showQuestion(event.text);
  }
  function showQuestion(text) {
    asked = text; $("question").classList.add("on"); $("question-text").textContent = text; $("answer").focus();
  }
  function hideQuestion() { asked = ""; $("question").classList.remove("on"); }

  function paint(state) {
    $("state").textContent = state.busy ? (state.status || "working") : (state.status || "idle");
    var dot = $("dot");
    dot.className = "dot " + (state.busy ? "busy" : (state.model_reachable === false ? "bad" : (state.model_reachable ? "ok" : "")));
    $("model").textContent = state.model || "—";
    $("reach").textContent = state.model_reachable === true ? "yes" : (state.model_reachable === false ? "no — " + (state.probe || "") : "not checked");
    $("screen").textContent = (state.capture || []).join(", ") || "none";
    $("input").textContent = (state.input || []).join(", ") || "none";
    $("overlay").textContent = state.overlay_running ? "on screen" : (state.overlay_available ? "available" : "not installed");
    $("skills").textContent = state.skills || "—";
    $("home").textContent = state.home || "—";
    $("sub").textContent = (state.version ? "v" + state.version + " · " : "") + (state.url || "");
    busy = !!state.busy;
    $("send").disabled = busy;
    $("prompt").placeholder = busy
      ? "working — press Stop to drop it"
      : "What should I do?   (Enter to send · Shift+Enter for a new line)";
    if (!state.question) hideQuestion();
  }

  function paintChips(chips) {
    var box = $("chips");
    if (box.childElementCount) return;
    chips.forEach(function (chip) {
      var b = document.createElement("button");
      b.className = "chip"; b.textContent = chip.label;
      b.onclick = function () { send(chip.prompt); };
      box.appendChild(b);
    });
  }

  async function tick() {
    try {
      var res = await api("/api/state?since=" + cursor);
      if (!res.ok) throw new Error(res.data.error || ("HTTP " + res.status));
      (res.data.events || []).forEach(function (event) { cursor = Math.max(cursor, event.seq); addEvent(event); });
      paint(res.data);
      paintChips(res.data.chips || []);
      $("mascot-btn").disabled = !res.data.overlay_available || res.data.overlay_running;
    } catch (error) {
      $("dot").className = "dot bad";
      $("state").textContent = "offline";
      $("sub").textContent = "lost the connection to the bot — is it still running?";
    }
  }

  async function send(text) {
    var prompt = (text || $("prompt").value || "").trim();
    if (!prompt || busy) return;
    addEvent({ seq: -1, kind: "you", text: prompt });
    if (!text) $("prompt").value = "";
    var res = await api("/api/task", { method: "POST", body: JSON.stringify({ prompt: prompt }) });
    if (!res.ok) {
      addEvent({ seq: -1, kind: "error", text: res.data.error || ("the bot refused the task (" + res.status + ")") });
      if (res.data.hint) addEvent({ seq: -1, kind: "error", text: res.data.hint });
    }
    tick();
  }

  $("send").onclick = function () { send(); };
  $("prompt").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("stop").onclick = async function () { await api("/api/cancel", { method: "POST", body: "{}" }); tick(); };
  $("answer-btn").onclick = async function () {
    var text = $("answer").value.trim();
    if (!text) return;
    await api("/api/answer", { method: "POST", body: JSON.stringify({ text: text }) });
    $("answer").value = ""; hideQuestion(); tick();
  };
  $("answer").addEventListener("keydown", function (e) { if (e.key === "Enter") $("answer-btn").click(); });
  $("quit-btn").onclick = async function () {
    if (!confirm("Stop the Naveed server? The desktop mascot, if it is showing, keeps running.")) return;
    await api("/api/quit", { method: "POST", body: "{}" });
    document.body.innerHTML = "<div class='wrap'><h1>Naveed stopped</h1>" +
      "<p class='note'>Close this tab, or start it again with <code>python main.py</code>.</p></div>";
  };
  $("mascot-btn").onclick = async function () {
    var res = await api("/api/overlay", { method: "POST", body: "{}" });
    toast(res.data.message || res.data.error || "…");
    tick();
  };

  var Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) {
    $("listen").style.display = "none";
  } else {
    var recognition = new Speech();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = true;
    recognition.onresult = function (event) {
      var text = "";
      for (var i = event.resultIndex; i < event.results.length; i++) text += event.results[i][0].transcript;
      $("prompt").value = text.trim();
    };
    recognition.onend = function () { listening = false; $("listen").classList.remove("primary"); };
    recognition.onerror = function (e) { toast("microphone: " + (e.error || "unavailable")); };
    $("listen").onclick = function () {
      if (listening) { recognition.stop(); return; }
      listening = true; $("listen").classList.add("primary"); recognition.start();
    };
  }

  tick();
  setInterval(tick, 1000);
})();
</script>
</body>
</html>
"""

PAGE = PAGE.replace("__FAVICON__", FAVICON)
