"""MetaTrader 5 order queue.

The MetaTrader5 Python package only exists for Windows and talks to a *running MT5 terminal*, so the engine (which may run on a
Kaggle GPU) never logs in itself.  Instead it keeps a queue of orders; `bridge/mt5_bridge.py` runs on the PC that has the terminal
open, logs in with YOUR credentials (kept in that PC's environment - they never reach this server), polls the queue, places the
orders and reports the result back.  Stop distances are sent as price *distances* so the SL/TP are re-anchored to the real MT5 tick.
"""
from __future__ import annotations

import os
import secrets
import threading
import time

from .models import Ticket

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
TOKEN_PATH = os.path.join(DATA_DIR, "mt5_token.txt")
LEASE_S = 45.0


def _token() -> str:
    env = os.environ.get("MT5_BRIDGE_TOKEN", "").strip()
    if env:
        return env
    try:
        with open(TOKEN_PATH) as f:
            t = f.read().strip()
            if t:
                return t
    except OSError:
        pass
    t = secrets.token_urlsafe(18)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TOKEN_PATH, "w") as f:
            f.write(t)
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return t


class MT5Queue:
    def __init__(self):
        self.token = _token()
        self.orders: dict[str, dict] = {}
        self.bridge: dict = {"connected": False, "last_seen": 0.0, "account": None}
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ engine side
    def enqueue(self, t: Ticket, lots: float, live_ok: bool, allow_synth: bool, why: str = "manual") -> dict:
        with self.lock:
            if t.id in self.orders and self.orders[t.id]["status"] in ("queued", "sent", "filled"):
                return self.orders[t.id]
            o = {"id": t.id, "symbol": t.sym, "cls": t.cls, "side": "BUY" if t.direction > 0 else "SELL", "lots": round(float(lots), 2),
                 "entry": t.entry, "sl": t.sl, "tp": t.tp, "sl_dist": abs(t.entry - t.sl), "tp_dist": abs(t.tp - t.entry),
                 "comment": f"SOULEXTER {t.id} {t.emitter}", "status": "queued", "retcode": None, "msg": "", "mt5_ticket": None,
                 "price": None, "t_queued": time.time(), "t_update": time.time(), "lease": 0.0, "why": why}
            if t.cls != "forex":
                o.update(status="error", msg=f"{t.cls} is not routed to MT5 (forex only)")
            elif not live_ok and not allow_synth:
                o.update(status="error", msg="signal is from SYNTHETIC prices - enable 'allow synthetic (test)' in Settings > MT5 to send anyway")
            self.orders[t.id] = o
            t.mt5 = self.public(o)
            return o

    def public(self, o: dict) -> dict:
        return {k: o[k] for k in ("status", "symbol", "side", "lots", "retcode", "msg", "mt5_ticket", "price", "t_update")}

    # ------------------------------------------------------------------ bridge side
    def heartbeat(self, info: dict | None):
        with self.lock:
            self.bridge = {"connected": True, "last_seen": time.time(), "account": info or self.bridge.get("account")}

    def pending(self, limit: int = 5) -> list[dict]:
        now = time.time()
        with self.lock:
            out = []
            for o in self.orders.values():
                stale = o["status"] == "sent" and now - o["lease"] > LEASE_S
                if o["status"] == "queued" or stale:
                    o["status"], o["lease"], o["t_update"] = "sent", now, now
                    out.append(dict(o))
                    if len(out) >= limit:
                        break
            return out

    def report(self, oid: str, res: dict) -> dict | None:
        with self.lock:
            o = self.orders.get(oid)
            if not o:
                return None
            ok = bool(res.get("ok"))
            o.update(status="filled" if ok else "error", retcode=res.get("retcode"), msg=str(res.get("msg", ""))[:240],
                     mt5_ticket=res.get("ticket"), price=res.get("price"), t_update=time.time())
            return self.public(o)

    def status(self) -> dict:
        with self.lock:
            b = dict(self.bridge)
            b["connected"] = b["connected"] and time.time() - b["last_seen"] < 20
            b["age_s"] = round(time.time() - b["last_seen"], 1) if b["last_seen"] else None
            counts: dict[str, int] = {}
            for o in self.orders.values():
                counts[o["status"]] = counts.get(o["status"], 0) + 1
            recent = sorted(self.orders.values(), key=lambda o: -o["t_update"])[:12]
            return {"bridge": b, "counts": counts, "recent": [{**self.public(o), "id": o["id"]} for o in recent]}
