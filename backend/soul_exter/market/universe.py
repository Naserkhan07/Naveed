"""117-symbol universe: 27 FX, 24 crypto, 30 stocks, 12 indices, 12 futures, 12 options."""
from __future__ import annotations

from dataclasses import dataclass, field

CCY_BETA = {"EUR": .5, "GBP": .5, "AUD": .7, "NZD": .6, "CAD": .4, "SEK": .6, "NOK": .5,
            "MXN": .35, "ZAR": .45, "TRY": .25, "SGD": .1, "CNH": .2,
            "USD": -.4, "JPY": -.5, "CHF": -.5}
CURRENCIES = list(CCY_BETA)


@dataclass
class Instrument:
    idx: int
    sym: str
    cls: str                  # forex|crypto|stock|index|future|option
    price: float
    sigma: float              # 1-min log-return std
    spread_bps: float
    yahoo: str | None = None
    binance: str | None = None
    fx: tuple[str, str] | None = None
    loads: dict[str, float] = field(default_factory=dict)   # group -> loading
    idio: float = 0.8
    vol: float = 1000.0
    decimals: int = 4
    name: str = ""


# ---- FX (27) --------------------------------------------------------------
_FX = [
    # symbol, price, sigma(bp/bar), spread bp
    ("EURUSD", 1.0850, 1.6, .15), ("GBPUSD", 1.2700, 1.9, .25), ("USDJPY", 151.20, 2.0, .25),
    ("USDCHF", .8850, 1.7, .35), ("AUDUSD", .6550, 2.0, .30), ("USDCAD", 1.3550, 1.7, .30),
    ("NZDUSD", .6050, 2.1, .40),
    ("EURGBP", .8540, 1.2, .35), ("EURJPY", 164.0, 2.4, .35), ("EURCHF", .9600, 1.3, .55),
    ("EURAUD", 1.6560, 2.2, .60), ("EURCAD", 1.4700, 1.9, .60), ("EURNZD", 1.7930, 2.4, .90),
    ("GBPJPY", 192.0, 2.8, .50), ("GBPCHF", 1.1240, 2.0, .80), ("GBPAUD", 1.9400, 2.4, .90),
    ("GBPCAD", 1.7220, 2.2, .90), ("AUDJPY", 99.0, 2.7, .55), ("AUDCAD", .8880, 2.0, .80),
    ("NZDJPY", 91.5, 2.9, .90),
    ("USDSEK", 10.45, 3.0, 2.2), ("USDNOK", 10.70, 3.0, 2.6), ("USDMXN", 17.10, 3.6, 3.5),
    ("USDZAR", 18.60, 4.2, 6.0), ("USDTRY", 32.4, 3.4, 9.0), ("USDSGD", 1.3450, 1.3, 1.6),
    ("USDCNH", 7.2400, 1.1, 2.4),
]
_YF_FX = lambda s: f"{s}=X"

# ---- crypto (24) ------------------------------------------------------------
_CRYPTO = [
    ("BTCUSD", 67000, 6.0, .35), ("ETHUSD", 3450, 8.0, .5), ("BNBUSD", 585, 8.0, .8),
    ("SOLUSD", 165, 11.0, 1.0), ("XRPUSD", .52, 10.0, 1.2), ("ADAUSD", .44, 11.0, 1.4),
    ("DOGEUSD", .155, 13.0, 1.4), ("AVAXUSD", 36.0, 12.0, 1.6), ("DOTUSD", 6.9, 12.0, 1.8),
    ("LINKUSD", 14.2, 12.0, 1.6), ("LTCUSD", 84.0, 9.0, 1.6), ("TRXUSD", .124, 7.0, 1.4),
    ("ATOMUSD", 8.6, 12.0, 2.0), ("UNIUSD", 7.8, 13.0, 2.0), ("NEARUSD", 5.6, 13.0, 2.2),
    ("APTUSD", 8.9, 14.0, 2.4), ("ARBUSD", 1.05, 14.0, 2.2), ("OPUSD", 2.3, 14.0, 2.4),
    ("FILUSD", 5.5, 14.0, 2.6), ("INJUSD", 24.0, 16.0, 2.8), ("SUIUSD", 1.6, 16.0, 2.8),
    ("AAVEUSD", 92.0, 13.0, 2.4), ("SHIBUSD", .0000245, 14.0, 2.4), ("TONUSD", 6.3, 13.0, 2.6),
]

# ---- stocks (30) -------------------------------------------------------------
_STOCKS = [
    ("AAPL", 190, 6, 1.0, "tech"), ("MSFT", 415, 6, 1.0, "tech"), ("NVDA", 880, 10, 1.4, "tech"),
    ("AMZN", 180, 7, 1.2, "tech"), ("GOOGL", 165, 7, 1.2, "tech"), ("META", 490, 8, 1.4, "tech"),
    ("TSLA", 175, 12, 2.0, "auto"), ("AMD", 165, 10, 1.6, "tech"), ("NFLX", 610, 8, 1.8, "tech"),
    ("JPM", 195, 5, 1.2, "fin"), ("BAC", 37, 6, 1.4, "fin"), ("XOM", 118, 5, 1.4, "energy"),
    ("CVX", 158, 5, 1.4, "energy"), ("WMT", 60, 4, 1.4, "def"), ("COST", 740, 5, 1.6, "def"),
    ("DIS", 112, 6, 1.6, "cons"), ("BA", 185, 7, 2.0, "ind"), ("INTC", 43, 8, 1.8, "tech"),
    ("ORCL", 125, 6, 1.6, "tech"), ("CRM", 300, 7, 1.6, "tech"), ("ADBE", 520, 7, 1.8, "tech"),
    ("PYPL", 63, 8, 2.0, "fin"), ("UBER", 70, 8, 1.8, "tech"), ("SHOP", 78, 11, 2.2, "tech"),
    ("KO", 61, 3, 1.4, "def"), ("PEP", 170, 3, 1.6, "def"), ("MCD", 285, 4, 1.6, "cons"),
    ("NKE", 95, 6, 1.8, "cons"), ("V", 275, 4, 1.4, "fin"), ("MA", 465, 4, 1.6, "fin"),
]
_INDICES = [
    ("SPX500", 5200, 3.5, .6, "^GSPC", "us"), ("NAS100", 18200, 4.5, .8, "^NDX", "us"),
    ("US30", 39000, 3.4, .8, "^DJI", "us"), ("US2000", 2050, 5.0, 1.2, "^RUT", "us"),
    ("GER40", 18300, 3.8, .9, "^GDAXI", "eu"), ("UK100", 7900, 3.0, 1.0, "^FTSE", "eu"),
    ("FRA40", 8100, 3.6, 1.0, "^FCHI", "eu"), ("JPN225", 39500, 4.4, 1.0, "^N225", "asia"),
    ("HK50", 17000, 5.0, 1.4, "^HSI", "asia"), ("EU50", 5000, 3.8, 1.0, "^STOXX50E", "eu"),
    ("AUS200", 7800, 3.0, 1.2, "^AXJO", "asia"), ("ESP35", 10900, 4.0, 1.4, "^IBEX", "eu"),
]
_FUTURES = [
    ("WTI", 82.0, 8.0, 1.8, "CL=F", "energy"), ("BRENT", 86.0, 7.5, 1.8, "BZ=F", "energy"),
    ("GOLD", 2340, 3.6, 1.0, "GC=F", "metal"), ("SILVER", 27.5, 7.0, 2.0, "SI=F", "metal"),
    ("NATGAS", 1.85, 14.0, 4.0, "NG=F", "energy"), ("COPPER", 4.5, 6.0, 2.0, "HG=F", "metal"),
    ("CORN", 445, 5.0, 3.0, "ZC=F", "agri"), ("WHEAT", 585, 7.0, 3.5, "ZW=F", "agri"),
    ("SOYBEAN", 1180, 5.0, 3.0, "ZS=F", "agri"), ("ES_FUT", 5215, 3.5, .8, "ES=F", "us"),
    ("NQ_FUT", 18300, 4.5, .9, "NQ=F", "us"), ("TNOTE", 110.5, 1.6, .8, "ZN=F", "rates"),
]
_OPTIONS = [
    ("SPY_CALL", 6.2, 1, "SPX500"), ("SPY_PUT", 5.4, -1, "SPX500"), ("QQQ_CALL", 5.8, 1, "NAS100"),
    ("QQQ_PUT", 5.0, -1, "NAS100"), ("AAPL_CALL", 4.1, 1, "AAPL"), ("AAPL_PUT", 3.6, -1, "AAPL"),
    ("TSLA_CALL", 7.9, 1, "TSLA"), ("TSLA_PUT", 7.1, -1, "TSLA"), ("NVDA_CALL", 21.0, 1, "NVDA"),
    ("NVDA_PUT", 18.0, -1, "NVDA"), ("AMZN_CALL", 4.8, 1, "AMZN"), ("AMZN_PUT", 4.2, -1, "AMZN"),
]
_EQ_GROUP_LOAD = {"tech": {"tech": .55}, "auto": {"tech": .35}, "fin": {"fin": .5}, "energy": {"energy": .5},
                  "def": {"def": .5}, "cons": {"cons": .4}, "ind": {"ind": .4}}


def build_universe() -> list[Instrument]:
    u: list[Instrument] = []

    def add(**kw):
        u.append(Instrument(idx=len(u), **kw))

    for sym, px, sg, sp in _FX:
        b, q = sym[:3], sym[3:]
        add(sym=sym, cls="forex", price=px, sigma=sg * 1e-4, spread_bps=sp, yahoo=_YF_FX(sym), fx=(b, q),
            idio=.30, vol=1e6, decimals=2 if px > 100 else (3 if px > 9 else 5), name=f"{b}/{q}")
    for sym, px, sg, sp in _CRYPTO:
        base = sym[:-3]
        dec = 8 if px < .001 else (5 if px < 1 else (3 if px < 100 else 2))
        add(sym=sym, cls="crypto", price=px, sigma=sg * 1e-4, spread_bps=sp, binance=f"{base}USDT",
            loads={"crypto": .85, "risk": .35}, idio=.75, vol=200.0, decimals=dec, name=base)
    for sym, px, sg, sp, sector in _STOCKS:
        loads = {"us": .55, "risk": .30}
        for k, v in _EQ_GROUP_LOAD[sector].items():
            loads[k] = v
        add(sym=sym, cls="stock", price=px, sigma=sg * 1e-4, spread_bps=sp, yahoo=sym, loads=loads,
            idio=.85, vol=5e4, decimals=2, name=sym)
    for sym, px, sg, sp, yf, reg in _INDICES:
        add(sym=sym, cls="index", price=px, sigma=sg * 1e-4, spread_bps=sp, yahoo=yf,
            loads={reg: .95, "risk": .45}, idio=.30, vol=1e5, decimals=1, name=sym)
    for sym, px, sg, sp, yf, grp in _FUTURES:
        loads = {"us": .95, "risk": .45} if grp == "us" else ({"rates": .9, "risk": -.2} if grp == "rates" else {grp: .75, "risk": .12})
        add(sym=sym, cls="future", price=px, sigma=sg * 1e-4, spread_bps=sp, yahoo=yf, loads=loads,
            idio=.30 if grp == "us" else .7, vol=3e4, decimals=2, name=sym)
    by = {i.sym: i for i in u}
    for sym, px, sgn, und in _OPTIONS:
        ui = by[und]
        loads = {k: v * sgn * 1.6 for k, v in ui.loads.items()}
        add(sym=sym, cls="option", price=px, sigma=ui.sigma * 4.2, spread_bps=ui.spread_bps * 14 + 8,
            loads=loads, idio=.35, vol=8e3, decimals=2, name=sym.replace("_", " "))
    assert len(u) == 117, len(u)
    return u


UNIVERSE: list[Instrument] = build_universe()
SYM_INDEX = {i.sym: i.idx for i in UNIVERSE}
CLASS_COUNTS = {c: sum(1 for i in UNIVERSE if i.cls == c) for c in ("forex", "crypto", "stock", "index", "future", "option")}
BINANCE_TOP14 = [i.sym for i in UNIVERSE if i.cls == "crypto"][:14]
