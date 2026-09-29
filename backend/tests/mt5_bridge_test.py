"""End-to-end check of queue + bridge against a MOCK MetaTrader5 module (the real package is Windows-only)."""
import os, sys, types, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import uvicorn
from soul_exter.engine.floor import FloorEngine
from soul_exter import main as M

port = 8765
M.ENGINE = eng = FloorEngine(seed=5)
eng.settings.mt5_allow_synth = True
import contextlib
# skip lifespan (we manage the engine ourselves)
import contextlib
@contextlib.asynccontextmanager
async def _noop(app):
    yield
M.app.router.lifespan_context = _noop
srv = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=port, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start(); time.sleep(1.5)

for _ in range(1200):
    eng.step(0.25)
    if any(t.cls == "forex" for t in eng.tickets.values()): break
fx = [t for t in eng.tickets.values() if t.cls == "forex"]
assert fx, "no forex ticket emitted"
t = fx[0]; o = eng.send_mt5(t, "test"); assert o["status"] == "queued", o

class Obj:
    def __init__(s, **k): s.__dict__.update(k)
placed = []
mt5 = types.SimpleNamespace(
    TRADE_ACTION_DEAL=1, ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, ORDER_TIME_GTC=0, ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, ORDER_FILLING_RETURN=2,
    TRADE_RETCODE_DONE=10009, TRADE_RETCODE_PLACED=10008, ACCOUNT_TRADE_MODE_DEMO=0,
    initialize=lambda **k: True, last_error=lambda: (0, "ok"),
    account_info=lambda: Obj(login=1, server="MetaQuotes-Demo", balance=10000., equity=10000., currency="USD", trade_mode=0),
    symbol_info=lambda s: Obj(digits=5, point=1e-5, trade_stops_level=10, volume_min=.01, volume_max=100, volume_step=.01, filling_mode=2) if s == t.sym + "m" else None,
    symbols_get=lambda: [], symbol_select=lambda s, b: True,
    symbol_info_tick=lambda s: Obj(bid=1.1, ask=1.10002),
    positions_get=lambda: [], order_send=lambda r: (placed.append(r), Obj(retcode=10009, order=777, price=r["price"], comment="Request executed"))[1])
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bridge"))
import mt5_bridge
os.environ.update(SOUL_URL=f"http://127.0.0.1:{port}", MT5_BRIDGE_TOKEN=eng.mt5.token, BRIDGE_MAX_LOOPS="1")
assert mt5_bridge.main(mt5) == 0
assert placed and placed[0]["symbol"] == t.sym + "m", placed
r = placed[0]
buy = t.direction > 0
assert (r["sl"] < r["price"]) == buy and (r["tp"] > r["price"]) == buy
print("placed:", r["symbol"], r["type"], r["volume"], "sl", r["sl"], "tp", r["tp"])
assert eng.mt5.orders[t.id]["status"] == "filled" and eng.mt5.orders[t.id]["mt5_ticket"] == 777
assert t.mt5["status"] == "filled", t.mt5
# bad token rejected
import urllib.request, urllib.error
try:
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/mt5/pending", headers={"X-Bridge-Token": "nope"})); raise SystemExit("auth hole")
except urllib.error.HTTPError as e:
    assert e.code == 401
print("[mt5] OK: queued -> bridge placed -> reported filled; bad token 401")
