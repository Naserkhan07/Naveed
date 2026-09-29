# SOUL EXTER — autonomous trading floor

    backend/   Python 3.11 · FastAPI · uvicorn · httpx · numpy   (soul_exter/…, tests/…)
    frontend/  React 18 · TypeScript · three 0.169 · vite 5

Run:

    python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
    cd backend && ../.venv/bin/python -m uvicorn soul_exter.main:app --host 0.0.0.0 --port 8000
    cd frontend && npm install && npm run dev        # http://localhost:5173  (proxies /api and /ws to :8000)

Tests / calibration (all headless + offline, from `backend/tests`):

    python smoke_engine.py 30 8      # walk order, navmesh, funnel, cooldown & pipe-cap invariants
    python track_record.py [sim_s]   # paper track record by verdict / class / emitter
    python council_study.py          # value of the 5-judge council, per judge
    python ceo_study.py              # CEO rulings on split councils
    python edge_study.py             # conviction / R:R calibration
    python deep_study.py             # rank-IC of the 29 fly-brain senses

LLM order: the seat's own endpoint (Ollama / OpenAI-compatible URL) → keyless free chain (Pollinations, LLM7) → if the server has no internet, the browser makes the call itself. No API keys anywhere. `SOUL_OFFLINE=1` is a test-only switch that disables all LLM calls.

---

## v2 — what changed

**People & floor.** Every ticket walks in through the welcome door, sits at its desk, stands up and walks *into* each cabin (navgrid paths, no clipping). People are articulated figures (walk cycle, sit/stand blend, carrying the ticket board). The asset name floats above **every** person — walking, seated or ambient. Ambient traders are labelled with the assets the fly-brain is currently hungriest for.

**Judges.** Six professional personas (ATLAS technical, QUANTA quant, MERIDIAN macro, VOLTA vol/liquidity, VECTOR risk, NAVEED CEO). Each vote carries `confidence`, `thesis` and `risk`. Judges get the floor's live win/loss record and their own notes, and calibrate (`judges.learn`) when their side was wrong. After each verdict a speech bubble appears over the judge — click it to open that desk's chat. In the debate room the six hold a real 6-turn conversation (open → challenge → question → answer → support → conclude); the conclusion becomes a rule written into every participant's notes.

**LLM routing.** Per seat: own endpoint (Ollama / any OpenAI-compatible URL) → free keyless chain → your browser. Configure in *Settings → LLM seats*.

**Markets.** *Settings → Markets & symbols* switches whole classes or single symbols; disabled assets get zero hunger and are skipped by the correlation finders.

**MetaTrader 5.** MT5's Python API is Windows-only, so the server keeps an order queue and `backend/bridge/mt5_bridge.py` (run on your PC) polls it and places the orders. Credentials live in the bridge's environment only. See *Settings → MetaTrader 5* for the exact command and the bridge token. Forex only; tickets from synthetic prices are refused unless "allow synthetic" is on; SL/TP are applied as distances to the live MT5 tick; the bridge refuses non-demo accounts unless `MT5_ALLOW_REAL=1`. Tested against a **mock** `MetaTrader5` module (`tests/mt5_bridge_test.py`) — never against a real terminal.

**Kaggle.** `kaggle/soul_exter_kaggle.ipynb` (or `python kaggle/run_kaggle.py`) installs Ollama, pulls one model per seat, builds the UI, serves everything from one FastAPI port and opens a Cloudflare tunnel. The backend serves `frontend/dist` when it exists.

**Interface.** Single tabbed side panel (Orders · Desks · Council · Brain), KPI strip, flat solid surfaces (no backdrop blur), ≤4 point lights, adaptive pixel ratio (cap 1.5) for smooth rendering.

**Tests.** `python tests/smoke_engine.py 60 8` and `python tests/mt5_bridge_test.py`.

> The UI has no login. If you expose it through a public tunnel, treat the URL as a secret (it shows the bridge token and can change the LLM settings).

## Chat: how desks always get a real model

There is no offline chat mode and no API keys. A question goes to the server, which tries the seat's own endpoint, then the keyless free chain (Pollinations, LLM7; each with its own 20 s breaker). If the server has no internet, it returns the finished prompt (persona + live floor status + history) and **your browser** sends it to the same keyless providers (`frontend/src/llm.ts`), then reports the reply back so history and the chatroom stay in sync. If neither can reach a model, the desk says so plainly and does not guess.

Cabin verdicts run on the server, so without server-side internet they use the quantitative rule-check, every such vote labelled `rules:no-LLM`. Run the backend on Kaggle / your PC (or point seats at Ollama) to have LLMs judge every trade.

`POST /api/llm/diagnose` and the *Check LLM connection* button (Settings → LLM seats) test both the server path and the browser path and show each error.
