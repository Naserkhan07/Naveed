"""SOUL EXTER -> MetaTrader 5 bridge.  Run this on the machine where the MT5 terminal is installed (Windows).

    pip install MetaTrader5
    set SOUL_URL=https://<your-tunnel>.trycloudflare.com     (or http://127.0.0.1:8000)
    set MT5_BRIDGE_TOKEN=<token shown in Settings > MT5>
    set MT5_LOGIN=12345678   MT5_PASSWORD=...   MT5_SERVER=MetaQuotes-Demo
    python mt5_bridge.py

Credentials are read from environment variables ONLY - they are never stored in the repo or sent to the floor server.
The bridge polls /api/mt5/pending, places a MARKET order with SL/TP built from the ticket's *distances* applied to
the live MT5 tick (so synthetic/other-feed price differences do not matter), and reports the result back.
It refuses to trade a non-demo account unless MT5_ALLOW_REAL=1.  Orders are idempotent by comment (SOULEXTER <id>).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

POLL_S = float(os.environ.get("BRIDGE_POLL_S", "2"))
DEVIATION = int(os.environ.get("MT5_DEVIATION", "20"))
MAGIC = 26092026


class Api:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, path: str, body: dict | None = None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Bridge-Token": self.token},
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())


def resolve_symbol(mt5, name: str) -> str | None:
    """EURUSD -> EURUSD / EURUSDm / EURUSD.a / EURUSD# ... whatever this broker calls it."""
    for cand in (name, name + "m", name + ".a", name + ".r", name + "#", name + "+", name + ".pro", name + "_i"):
        if mt5.symbol_info(cand) is not None:
            return cand
    for s in mt5.symbols_get() or []:
        if s.name.upper().startswith(name.upper()):
            return s.name
    return None


def already_placed(mt5, comment: str) -> int | None:
    for pos in mt5.positions_get() or []:
        if pos.comment == comment[:31] or pos.comment.startswith(comment[:31]):
            return pos.ticket
    return None


def place(mt5, o: dict) -> dict:
    comment = o["comment"][:31]
    dup = already_placed(mt5, comment)
    if dup:
        return {"ok": True, "ticket": dup, "msg": "already open (idempotent)", "retcode": 10009}
    sym = resolve_symbol(mt5, o["symbol"])
    if not sym:
        return {"ok": False, "msg": f"symbol {o['symbol']} not found at this broker"}
    if not mt5.symbol_select(sym, True):
        return {"ok": False, "msg": f"cannot select {sym}"}
    info, tick = mt5.symbol_info(sym), mt5.symbol_info_tick(sym)
    if tick is None or info is None:
        return {"ok": False, "msg": f"no tick for {sym} (market closed?)"}
    buy = o["side"] == "BUY"
    px = tick.ask if buy else tick.bid
    d = info.digits
    min_stop = max(info.trade_stops_level, 0) * info.point
    sl_d, tp_d = max(o["sl_dist"], min_stop * 1.1), max(o["tp_dist"], min_stop * 1.1)
    sl = round(px - sl_d if buy else px + sl_d, d)
    tp = round(px + tp_d if buy else px - tp_d, d)
    lots = max(info.volume_min, min(info.volume_max, round(o["lots"] / info.volume_step) * info.volume_step))
    fill = mt5.ORDER_FILLING_IOC
    fm = getattr(info, "filling_mode", 0)
    if fm & 1:
        fill = mt5.ORDER_FILLING_FOK
    elif fm & 2:
        fill = mt5.ORDER_FILLING_IOC
    else:
        fill = mt5.ORDER_FILLING_RETURN
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(lots),
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, "price": px, "sl": sl, "tp": tp,
           "deviation": DEVIATION, "magic": MAGIC, "comment": comment, "type_time": mt5.ORDER_TIME_GTC, "type_filling": fill}
    res = mt5.order_send(req)
    if res is None:
        return {"ok": False, "msg": f"order_send returned None: {mt5.last_error()}"}
    ok = res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    return {"ok": ok, "retcode": int(res.retcode), "ticket": int(getattr(res, "order", 0) or 0), "price": float(getattr(res, "price", px) or px),
            "msg": f"{sym} {o['side']} {lots} sl {sl} tp {tp}: {getattr(res, 'comment', '')}"}


def main(mt5=None) -> int:
    url, token = os.environ.get("SOUL_URL", "http://127.0.0.1:8000"), os.environ.get("MT5_BRIDGE_TOKEN", "")
    if not token:
        print("set MT5_BRIDGE_TOKEN (see Settings > MT5 in the app)")
        return 2
    if mt5 is None:
        import MetaTrader5 as mt5       # type: ignore  # noqa: N813  (Windows only)
    login, pw, server = os.environ.get("MT5_LOGIN"), os.environ.get("MT5_PASSWORD"), os.environ.get("MT5_SERVER", "MetaQuotes-Demo")
    ok = mt5.initialize(login=int(login), password=pw, server=server) if login and pw else mt5.initialize()
    if not ok:
        print("MT5 initialize failed:", mt5.last_error())
        return 3
    acc = mt5.account_info()
    if acc is None:
        print("no account info")
        return 3
    demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    if not demo and os.environ.get("MT5_ALLOW_REAL") != "1":
        print(f"account {acc.login} is NOT a demo account; refusing (set MT5_ALLOW_REAL=1 to override)")
        return 4
    print(f"connected: {acc.login} @ {acc.server} balance {acc.balance} {acc.currency} ({'DEMO' if demo else 'REAL'})")
    api = Api(url, token)
    loops = int(os.environ.get("BRIDGE_MAX_LOOPS", "0"))
    n = 0
    while True:
        try:
            a = mt5.account_info()
            api.call("/api/mt5/heartbeat", {"account": {"login": acc.login, "server": acc.server, "demo": demo,
                                                         "balance": a.balance, "equity": a.equity, "currency": a.currency}})
            for o in api.call("/api/mt5/pending")["orders"]:
                r = place(mt5, o)
                print(o["id"], o["symbol"], o["side"], "->", r)
                api.call("/api/mt5/report", {"id": o["id"], **r})
        except Exception as e:      # noqa: BLE001 - keep polling
            print("bridge error:", type(e).__name__, e, file=sys.stderr)
        n += 1
        if loops and n >= loops:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
