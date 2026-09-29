"""FastAPI app: REST + a 12 Hz /ws stream, engine loop at 20 Hz."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core import layout as L
from .engine.floor import FloorEngine, SIM_HZ
from .llm.seats import COLORS, JUDGES, SEATS
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
    e.chatroom.append(rep)
    return {"posted": msg, "reply": rep}


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
                                "events": list(e.events)[-14:], "lessons": list(e.lessons)[-6:], "stats": e.stats,
                                "chatroom": list(e.chatroom)[-12:], "seats": e.seats()}
            await sock.send_text(json.dumps(msg))
            n += 1
            await asyncio.sleep(1 / 12)
    except (WebSocketDisconnect, RuntimeError):
        return
