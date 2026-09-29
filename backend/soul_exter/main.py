"""FastAPI app: REST + a 12 Hz /ws stream, engine loop at 20 Hz."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

import os

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core import layout as L
from .engine.floor import FloorEngine, SIM_HZ
from .llm.seats import COLORS, JUDGES, SEATS, resolve_seat
from .market.live import LiveFeed
from .market.micro import MicroModule


class ChatIn(BaseModel):
    seat_id: str | int | None = "ATLAS"
    question: str
    history: list[dict] | None = None


class TradeChatIn(BaseModel):
    question: str
    seat_id: str | None = "DROSOPHILA"


class DebateIn(BaseModel):
    question: str


class MT5Report(BaseModel):
    id: str
    ok: bool
    retcode: int | None = None
    msg: str = ""
    ticket: int | None = None
    price: float | None = None


class MT5Beat(BaseModel):
    account: dict | None = None


class SayIn(BaseModel):
    name: str | None = "operator"
    text: str


ENGINE: FloorEngine | None = None


def engine() -> FloorEngine:
    assert ENGINE is not None
    return ENGINE


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE
    micro = MicroModule()
    ENGINE = FloorEngine(seed=int(time.time()) % 10000, micro=micro, persist=True)
    ENGINE.set_settings({})
    live = LiveFeed(ENGINE.tape, micro, lambda: ENGINE.settings)
    micro.start()
    live.start()
    stop = asyncio.Event()

    async def loop():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(1.0 / SIM_HZ)
            now = time.perf_counter()
            dt = min(now - last, 0.25)
            last = now
            try:
                await asyncio.to_thread(ENGINE.step, dt)
            except Exception as e:      # noqa: BLE001 - keep the floor alive, surface in events
                ENGINE.log("error", f"sim step: {type(e).__name__}: {e}")

    task = asyncio.create_task(loop())
    yield
    stop.set()
    task.cancel()
    micro.stop()
    live.stop()
    try:
        ENGINE.save_brain()
    except Exception:       # noqa: BLE001
        pass


app = FastAPI(title="SOUL EXTER trading floor", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "bars": engine().tape.nbars, "mode": engine().tape.live_mode}


@app.get("/api/layout")
def api_layout():
    return L.layout()


@app.get("/api/state")
def api_state():
    return engine().state()


@app.get("/api/seats")
def api_seats():
    return engine().seats()


@app.get("/api/orders")
def api_orders(n: int = 60):
    return engine().orders(min(n, 200))


@app.get("/api/fly")
def api_fly():
    return engine().fly()


@app.get("/api/fly/wiring")
def api_fly_wiring():
    """Real anatomy for the connectome view: glomerulus->PN weights (top 5 per PN), PN->KC fan-in indices, KC->MBON weights."""
    import numpy as np
    b = engine().hunter.brain
    W = np.asarray(b.W_gp)
    top = np.argsort(-np.abs(W), axis=1)[:, :5]
    return {"gp": [[[int(j), round(float(W[i, j]), 3)] for j in top[i]] for i in range(W.shape[0])],
            "fan": np.asarray(b.fan).astype(int).tolist(),
            "mb": np.round(np.asarray(b.W_mb), 3).tolist(),
            "instincts": np.round(np.asarray(b.instincts), 2).tolist()}


@app.get("/api/tape")
def api_tape():
    e = engine()
    return {"mode": e.tape.live_mode, "live_n": e.tape.live_n, "tape": e.tape.summary()}


@app.post("/api/chat")
def api_chat(body: ChatIn):
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    return engine().chat(body.seat_id, body.question, body.history)


@app.post("/api/trades/{tid}/chat")
def api_trade_chat(tid: str, body: TradeChatIn):
    e = engine()
    t = e.tickets.get(tid)
    if t is None:
        raise HTTPException(404, "unknown trade")
    r = e.chat(body.seat_id, body.question, history=[], context=e.trade_context(t))
    r["trade"] = tid
    return r


@app.post("/api/debate/ask")
def api_debate_ask(body: DebateIn):
    from concurrent.futures import ThreadPoolExecutor
    e = engine()
    seats = JUDGES + ["DROSOPHILA"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {s: ex.submit(e.chat, s, body.question, []) for s in seats}
    return {"question": body.question, "answers": [futs[s].result() for s in seats]}


@app.post("/api/chatroom/say")
def api_chatroom_say(body: SayIn):
    e = engine()
    msg = {"t": round(e.sim_t, 1), "name": (body.name or "operator")[:24], "text": body.text[:1000], "color": "#e2e8f0"}
    e.chatroom.append(msg)
    seat = JUDGES[len(e.chatroom) % len(JUDGES)]
    for s in JUDGES + ["NAVEED", "DROSOPHILA"]:
        if s.lower() in body.text.lower():
            seat = s
    r = e.chat(seat, body.text, [])
    rep = {"t": round(e.sim_t, 1), "name": seat, "text": r["answer"], "color": COLORS[seat], "label": r["label"]}
    if not r["ok"]:      # the browser makes the call and then posts the reply via /api/chatroom/reply
        return {"posted": msg, "reply": None, "pending": {"seat": seat, "messages": r["messages"], "color": COLORS[seat]}}
    e.chatroom.append(rep)
    return {"posted": msg, "reply": rep}


class ReplyIn(BaseModel):
    seat_id: str
    text: str
    label: str = ""
    question: str = ""
    room: bool = False


@app.post("/api/chat/remember")
def api_chat_remember(body: ReplyIn):
    """store a reply the browser obtained from a free model, so history and the chatroom stay in sync"""
    e = engine()
    seat = resolve_seat(body.seat_id)
    if body.room:
        e.chatroom.append({"t": round(e.sim_t, 1), "name": seat, "text": body.text[:2000], "color": COLORS[seat], "label": body.label})
    elif body.question:
        e.remember(seat, body.question, body.text, body.label)
    return {"ok": True}


@app.get("/api/universe")
def api_universe():
    return engine().universe()


@app.get("/api/llm/config")
def api_llm_get():
    return engine().router.get_cfg()


@app.post("/api/llm/config")
def api_llm_set(body: dict):
    e = engine()
    e.router.set_cfg(body.get("seats", body))
    return e.router.get_cfg()


@app.post("/api/llm/diagnose")
def api_llm_diagnose():
    return engine().router.diagnose()


@app.post("/api/llm/test/{seat}")
def api_llm_test(seat: str):
    return engine().router.test_seat(seat)


# ---- MetaTrader 5 bridge (the bridge script runs where the MT5 terminal is; it authenticates with the token) ----
def _bridge_auth(tok: str | None):
    if tok != engine().mt5.token:
        raise HTTPException(401, "bad bridge token")


@app.get("/api/mt5/status")
def api_mt5_status():
    st = engine().mt5.status()
    st["settings"] = {k: getattr(engine().settings, k) for k in ("mt5_auto", "mt5_lots", "mt5_allow_synth")}
    st["server"] = os.environ.get("MT5_SERVER", "MetaQuotes-Demo")
    return st


@app.get("/api/mt5/token")
def api_mt5_token():
    return {"token": engine().mt5.token}


@app.post("/api/mt5/heartbeat")
def api_mt5_beat(body: MT5Beat, x_bridge_token: str | None = Header(None)):
    _bridge_auth(x_bridge_token)
    engine().mt5.heartbeat(body.account)
    return {"ok": True}


@app.get("/api/mt5/pending")
def api_mt5_pending(x_bridge_token: str | None = Header(None)):
    _bridge_auth(x_bridge_token)
    engine().mt5.heartbeat(None)
    return {"orders": engine().mt5.pending()}


@app.post("/api/mt5/report")
def api_mt5_report(body: MT5Report, x_bridge_token: str | None = Header(None)):
    _bridge_auth(x_bridge_token)
    e = engine()
    pub = e.mt5.report(body.id, body.dict())
    t = e.tickets.get(body.id)
    if t and pub:
        t.mt5 = pub
        e.log("mt5", f"{t.id} {t.sym} MT5 {pub['status']}" + (f" #{pub['mt5_ticket']} @ {pub['price']}" if pub["status"] == "filled" else f": {pub['msg']}"), t.id)
    return {"ok": bool(pub)}


@app.get("/api/trades/{tid}/detail")
def api_trade_detail(tid: str):
    d = engine().trade_detail(tid)
    if d is None:
        raise HTTPException(404, "unknown trade")
    return d


@app.post("/api/trades/{tid}/mt5")
def api_trade_mt5(tid: str):
    e = engine()
    t = e.tickets.get(tid)
    if t is None:
        raise HTTPException(404, "unknown trade")
    o = e.send_mt5(t, "manual")
    return e.mt5.public(o) | {"id": tid}


@app.get("/api/settings")
def api_settings_get():
    return engine().state()["settings"]


@app.post("/api/settings")
def api_settings_set(body: dict):
    e = engine()
    e.set_settings(body)
    return e.state()["settings"]


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    e = engine()
    n = 0
    try:
        while True:
            msg = e.frame()
            if n % 12 == 0:
                msg["extra"] = {"fly": e.fly(), "orders": e.orders(24), "tape": e.tape.summary(), "mode": e.tape.live_mode,
                                "events": list(e.events)[-14:], "lessons": list(e.lessons)[-8:], "stats": e.kpis(),
                                "chatroom": list(e.chatroom)[-40:], "seats": e.seats(), "llm": e.router.status(),
                                "mt5": {"connected": e.mt5.status()["bridge"]["connected"], "auto": e.settings.mt5_auto},
                                "record": e.judges.record}
            await sock.send_text(json.dumps(msg))
            n += 1
            await asyncio.sleep(1 / 12)
    except (WebSocketDisconnect, RuntimeError):
        return


# ---- serve the built frontend (Kaggle / single-port deployments): `cd frontend && npm run build`
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(_DIST, path)
        if path and os.path.isfile(f) and os.path.abspath(f).startswith(os.path.abspath(_DIST)):
            return FileResponse(f)
        return FileResponse(os.path.join(_DIST, "index.html"))
