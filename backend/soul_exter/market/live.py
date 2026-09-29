"""Optional live merge (no API keys): Binance 1m klines for crypto + Yahoo 1m charts for the rest.
Falls back silently to the synthetic tape; the tape footer shows which mode is active."""
from __future__ import annotations

import threading
import time

from .micro import MicroModule
from .tape import Tape
from .universe import UNIVERSE

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
FRESH_S = 600.0


class LiveFeed:
    def __init__(self, tape: Tape, micro: MicroModule, get_settings):
        self.tape, self.micro, self.get_settings = tape, micro, get_settings
        self.seen: dict[int, float] = {}
        self.binance_ok = False
        self.yahoo_ok = False
        self.errors = 0
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    def start(self):
        self._th = threading.Thread(target=self._run, name="live-feed", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    def _update_mode(self):
        now = time.time()
        live = [i for i, t in self.seen.items() if now - t < FRESH_S]
        self.tape.live_idx = set(live)
        self.tape.live_n = len(live)
        self.tape.live_mode = (f"LIVE {len(live)}/{len(UNIVERSE)} + SYNTHETIC" if live else "SYNTHETIC (offline)")

    def _run(self):
        import httpx
        crypto = [i for i in UNIVERSE if i.binance]
        yahoo = [i for i in UNIVERSE if i.yahoo]
        yi = 0
        with httpx.Client(timeout=6.0, headers={"User-Agent": "Mozilla/5.0 soul-exter"}) as cli:
            while not self._stop.is_set():
                s = self.get_settings()
                if not s.live:
                    self.tape.live_mode, self.tape.live_n = "SYNTHETIC (live off)", 0
                    self._stop.wait(5)
                    continue
                # ---- binance (crypto): one full sweep per ~30 s
                ok = 0
                for inst in crypto:
                    if self._stop.is_set():
                        break
                    try:
                        r = cli.get(BINANCE_KLINES, params={"symbol": inst.binance, "interval": "1m", "limit": 3})
                        r.raise_for_status()
                        k = r.json()[-2]                 # last CLOSED 1m kline
                        o, h, l, c, v = (float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
                        tb = float(k[9])
                        self.tape.apply_live_bar(inst.idx, k[0] / 1000 + 60, o, h, l, c, v, tb)
                        if v > 0:
                            self.micro.ingest_taker(inst.sym, tb / v)
                        self.seen[inst.idx] = time.time()
                        ok += 1
                    except Exception:       # noqa: BLE001
                        self.errors += 1
                        break                           # unreachable -> stop the sweep early
                    self._stop.wait(0.15)
                self.binance_ok = ok > 0
                # ---- yahoo: a handful per cycle
                for _ in range(8):
                    if self._stop.is_set():
                        break
                    inst = yahoo[yi % len(yahoo)]
                    yi += 1
                    try:
                        r = cli.get(YAHOO_CHART.format(sym=inst.yahoo), params={"interval": "1m", "range": "1d"})
                        r.raise_for_status()
                        res = r.json()["chart"]["result"][0]
                        q = res["indicators"]["quote"][0]
                        ts = res["timestamp"]
                        for j in range(len(ts) - 2, -1, -1):
                            if q["close"][j] is not None:
                                self.tape.apply_live_bar(inst.idx, ts[j] + 60, q["open"][j] or q["close"][j], q["high"][j] or q["close"][j],
                                                         q["low"][j] or q["close"][j], q["close"][j], q["volume"][j] or 0.0, 0.0)
                                if time.time() - ts[j] < 240:
                                    self.seen[inst.idx] = time.time()
                                break
                        self.yahoo_ok = True
                    except Exception:       # noqa: BLE001
                        self.errors += 1
                        self.yahoo_ok = False
                        break
                    self._stop.wait(1.5)
                self._update_mode()
                self._stop.wait(30 if (self.binance_ok or self.yahoo_ok) else 90)
