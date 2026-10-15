# The browser front end

Naveed is a desktop overlay: a mascot that floats over your other windows and does
the task on your screen. This document is about the *other* way to use the very
same bot — over HTTP, in a browser.

```bash
python -m naveed                 # mascot on screen, page at http://127.0.0.1:8765
python -m naveed --serve         # the page only; no Qt needed at all
python main.py                   # same as `python -m naveed`: both halves
naveed-web                       # the same as --serve, as a console script
naveed-web --open-browser        # …and open it for me
naveed-web --check               # the environment report, then exit
```

Why it exists: the mascot is perfect for "look at this and do it", and a browser
is better for typing a long instruction, reading back what happened, and using the
bot from another device. Since both front ends share one agent, they are not two
products — just two windows onto the same one.

## One bot, two windows

| Running | What you get |
|---|---|
| `python main.py` · `python -m naveed` | mascot **and** the page, together, sharing one `AgentBridge` (one screen watcher, one task queue) |
| `python -m naveed --serve` · `naveed-web` | the page only, blocking in the terminal; events are echoed there too (stdout, `Ctrl+C` stops it) |
| `python -m naveed --no-serve` | the mascot only, no HTTP listener |

In the first case a task typed in the browser moves the mascot: the panel shows
`thinking`, the mascot's expression changes, and its answer appears in both. That
is the point of sharing the bridge — two windows, one bot, no double capturing of
your screen.

## The page

Served from `/` as one self-contained HTML document (see `naveed/webui.py`):

* **What is happening** — a live log: what you asked, what it said, each action it
  performed and whether that worked, and the questions it needs answered (with a
  box to answer them in).
* **This bot** — the model and whether it *answers*, the capture and input
  backends, the mascot's availability, how many routines it has been taught, and
  the home directory it is using.
* **Quick actions** — the same shortcut grid as the panel, as chips.
* **Listen** — dictation through the browser's speech recognition, when the
  browser has one. Nothing is uploaded by Naveed itself; that microphone belongs
  to the browser.
* **Show mascot** — starts the floating mascot as its own process (`python -m
  naveed --no-serve`). Qt wants the main thread for its event loop, and that
  thread is busy serving HTTP here, so a separate process is the honest way to do
  it. Disabled when PySide6 is not installed, with the install command shown.
* **Quit** — stops the server (and the mascot it started). The mascot keeps
  running if it was started some other way.

No frameworks, no CDN, no build step: the page is one string, fetched with
relative URLs only, which is what lets it work offline and behind any proxy or
tunnel.

## The HTTP API

Small on purpose. Everything is JSON; errors carry a human sentence in `error` and,
where there is one, the fix in `hint`.

| Method | Path | Body | What it does |
|---|---|---|---|
| `GET` | `/` | — | the page |
| `GET` | `/api/health` | — | `{"ok": true, "version": …, "busy": …}` — for scripts and health checks |
| `GET` | `/api/state?since=N` | — | everything the page needs, including only the events *after* sequence `N` |
| `GET` | `/api/screen` | — | the newest capture as an image, or 404 with a sentence |
| `POST` | `/api/task` | `{"prompt": "…"}` | queue a task. 400 empty, 409 busy, 503 model unreachable (with the reason) |
| `POST` | `/api/answer` | `{"text": "…"}` | answer the question it asked |
| `POST` | `/api/cancel` | — | stop the current task |
| `POST` | `/api/recipe` | `{"name": "…", "args": {…}}` | run a taught routine without the model |
| `POST` | `/api/overlay` | — | start the floating mascot |
| `POST` | `/api/quit` | — | stop the server |

The whole surface is deliberately the *same* code path as the CLI, so a task cannot
"succeed" in the browser while failing at the prompt: `/api/task` performs the same
reachability check `python -m naveed -p "…"` does, and refuses with the same
sentence when the model is not answering.

```bash
# ask it something
curl -s -X POST localhost:8765/api/task -H 'Content-Type: application/json' \
     -d '{"prompt": "summarise what is on my screen"}'

# watch what it is doing (only what you have not seen yet)
curl -s "localhost:8765/api/state?since=0" | python3 -m json.tool

# run a routine you taught
curl -s -X POST localhost:8765/api/recipe -H 'Content-Type: application/json' \
     -d '{"name": "polarion-set-status", "args": {"status": "Verified"}}'
```

`events[]` entries are `{seq, kind, text, at}` with `kind` one of `say`, `you`,
`status`, `action`, `question`, `error`, `task`. `seq` only ever increases, so a
dashboard can poll cheaply and never render twice.

## Who can reach it

| Bind | Token | When to use it |
|---|---|---|
| `127.0.0.1` (default) | not needed | your own machine |
| `0.0.0.0` | **required** (printed at startup, `?token=…` or `X-Naveed-Token`) | another device on your LAN |
| `0.0.0.0 --no-token` | none | a container port, a tunnel that authenticates, a network you control |

The token exists because this API can type into your windows. It is compared with
`hmac.compare_digest`, and it is only ever demanded for requests that are not from
loopback.

`X-Frame-Options` is **not** sent: embedding the local bot in your own dashboard is
a feature. That is safe for the same reason the token exists — the default bind is
loopback-only.

## When it does not come up

| Symptom | Cause |
|---|---|
| `the page will still open — it will simply refuse tasks…` | No model is answering. That is on purpose: the page opens, and every task is refused with the real reason instead of failing 45 seconds later. Fix the model, not the server. |
| The printed port is not the one you asked for | Something already had it (another Naveed?). The bot falls back to a free port rather than refusing to start; the URL printed is the one that works. |
| `lost the connection to the bot` in the page | The server stopped (`Ctrl+C`, or Quit). The page reconnects by itself when it comes back on the same URL. |
| Every request is `401` | You bound wider than loopback: append the token from the startup line, `http://host:8765/?token=…`. |
| *Show mascot* says PySide6 is not installed | That half needs `pip install "naveed[ui]"`; the browser half deliberately does not. |
| The mascot button does nothing on Windows/macOS | It spawns a separate process; check that `python -m naveed --no-serve` runs from the same interpreter by hand. |
