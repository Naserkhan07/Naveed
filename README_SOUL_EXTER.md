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

LLM order: keyless Pollinations (`https://text.pollinations.ai/openai`) → env keys (`OPENROUTER_API_KEY`, …) → offline reasoning. `SOUL_OFFLINE=1` forces offline.
