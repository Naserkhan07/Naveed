"""Built-in offline reasoning: honest, deterministic, never fabricates.

Handles arithmetic, percentages, unit conversion, date/time, greetings, a glossary (whole-word
matching), small fact tables — and otherwise says plainly that it needs a language model."""
from __future__ import annotations

import ast
import math
import operator as op
import re
import time

from . import kb
from .humanize import GLOSSARY, glossary_hits

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod,
        ast.FloorDiv: op.floordiv}
_UN = {ast.USub: op.neg, ast.UAdd: op.pos}
_FN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log, "ln": math.log,
       "log10": math.log10, "abs": abs, "round": round, "exp": math.exp, "floor": math.floor, "ceil": math.ceil}
_CONST = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(b) > 64 or abs(a) > 1e6):
            raise ValueError("too large")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONST:
        return _CONST[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FN and len(node.args) == 1:
        return _FN[node.func.id](_eval(node.args[0]))
    raise ValueError("unsupported")


def _fmt(x: float) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.10g}"


def try_math(q: str) -> str | None:
    s = q.lower().replace("×", "*").replace("÷", "/").replace("^", "**").replace("−", "-")
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", s)
    if m:
        return f"{m.group(1)}% of {m.group(2)} is {_fmt(float(m.group(1)) * float(m.group(2)) / 100)}."
    s = re.sub(r"\b(what is|what's|whats|calculate|compute|evaluate|solve|how much is|equals?|=|\?)\b|[?=]", " ", s)
    s = re.sub(r"\b(plus)\b", "+", s); s = re.sub(r"\b(minus)\b", "-", s)
    s = re.sub(r"\b(times|multiplied by)\b", "*", s); s = re.sub(r"\b(divided by|over)\b", "/", s)
    s = re.sub(r"\b(the|is|of the)\b", " ", s) if "square root" in s else s
    s = re.sub(r"\bsquare root of\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", s)
    s = s.replace("squared", "**2").replace("cubed", "**3").strip().rstrip(".")
    if not re.search(r"\d", s) or re.search(r"[a-z]{2,}", re.sub(r"\b(sqrt|sin|cos|tan|log10|log|ln|abs|round|exp|floor|ceil|pi)\b", "", s)):
        return None
    if not re.fullmatch(r"[\d\s.+\-*/()%,a-z]+", s):
        return None
    try:
        v = _eval(ast.parse(s, mode="eval"))
    except Exception:       # noqa: BLE001
        return None
    expr = re.sub(r"\s+", " ", s)
    return f"{expr} = {_fmt(float(v) if not isinstance(v, int) else v)}."


_UNITS = {("km", "mi"): 0.621371, ("mi", "km"): 1.609344, ("kg", "lb"): 2.204623, ("lb", "kg"): 0.453592,
          ("m", "ft"): 3.28084, ("ft", "m"): 0.3048, ("cm", "in"): 0.393701, ("in", "cm"): 2.54, ("l", "gal"): 0.264172,
          ("gal", "l"): 3.785412}


def try_units(q: str) -> str | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*°?\s*(c|f|celsius|fahrenheit)\s*(?:to|in|into)\s*(c|f|celsius|fahrenheit)\b", q, re.I)
    if m:
        v, a, b = float(m.group(1)), m.group(2)[0].lower(), m.group(3)[0].lower()
        if a != b:
            r = v * 9 / 5 + 32 if a == "c" else (v - 32) * 5 / 9
            return f"{_fmt(v)}°{a.upper()} is {r:.1f}°{b.upper()}."
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(km|mi|miles?|kg|lbs?|pounds?|m|meters?|ft|feet|cm|in|inch(?:es)?|l|liters?|gal)\s*(?:to|in|into)\s*(km|mi|miles?|kg|lbs?|pounds?|m|meters?|ft|feet|cm|in|inch(?:es)?|l|liters?|gal)\b", q, re.I)
    if m:
        norm = lambda u: {"miles": "mi", "mile": "mi", "lbs": "lb", "pounds": "lb", "pound": "lb", "meters": "m", "meter": "m", "feet": "ft",
                          "inches": "in", "inch": "in", "liters": "l", "liter": "l"}.get(u.lower(), u.lower())
        a, b = norm(m.group(2)), norm(m.group(3))
        k = _UNITS.get((a, b))
        if k:
            return f"{m.group(1)} {a} ≈ {float(m.group(1)) * k:.4g} {b}."
    return None


CAPITALS = {"france": "Paris", "germany": "Berlin", "italy": "Rome", "spain": "Madrid", "japan": "Tokyo", "china": "Beijing",
            "india": "New Delhi", "pakistan": "Islamabad", "united kingdom": "London", "uk": "London", "canada": "Ottawa",
            "australia": "Canberra", "brazil": "Brasília", "russia": "Moscow", "egypt": "Cairo", "turkey": "Ankara",
            "united states": "Washington, D.C.", "usa": "Washington, D.C.", "mexico": "Mexico City", "argentina": "Buenos Aires",
            "south korea": "Seoul", "saudi arabia": "Riyadh", "uae": "Abu Dhabi", "nigeria": "Abuja", "kenya": "Nairobi",
            "south africa": "Pretoria (executive capital)", "switzerland": "Bern", "sweden": "Stockholm", "norway": "Oslo"}


def try_facts(q: str) -> str | None:
    m = re.search(r"capital (?:city )?of ([a-z .]+?)\s*[?.!]*$", q.lower().strip())
    if m and m.group(1).strip() in CAPITALS:
        return f"The capital of {m.group(1).strip().title()} is {CAPITALS[m.group(1).strip()]}."
    return None


def try_time(q: str) -> str | None:
    s = q.lower()
    if re.search(r"\b(what|tell me)\b.*\b(time)\b", s) and "timeline" not in s:
        return time.strftime("It's %H:%M UTC right now.", time.gmtime())
    if re.search(r"\b(today'?s? date|what('?s| is) (the )?date|what day is (it|today))\b", s):
        return time.strftime("Today is %A, %d %B %Y (UTC).", time.gmtime())
    return None


def try_smalltalk(q: str, seat: str) -> str | None:
    s = q.lower().strip()
    if len(s) < 45 and re.match(r"(hi|hello|hey|yo|good (morning|afternoon|evening))\b", s):
        return f"Hello! I'm the assistant at the {seat} desk. What would you like to ask?"
    if re.search(r"\b(thanks|thank you|cheers)\b", s):
        return "You're welcome!"
    if re.search(r"how are you", s):
        return "Doing well, thanks for asking — ready when you are."
    if re.search(r"\bwho are you\b|\bwhat are you\b|\byour name\b", s):
        return f"I'm the assistant at the {seat} desk of the Soul Exter floor. Ask me anything and I'll answer as directly as I can."
    if re.search(r"\b(reveal|show|print|repeat)\b.*\b(system prompt|instructions|rules)\b", s):
        return "I can't share my internal instructions, but I'm happy to help with your actual question."
    return None


def try_glossary(q: str) -> str | None:
    if not re.search(r"\b(what|who|define|explain|meaning|mean|tell me about|describe)\b", q, re.I):
        return None
    hits = glossary_hits(q)
    if not hits:
        return None
    hits.sort(key=lambda k: -len(k))          # 'machine learning' beats 'learning'
    k = hits[0]
    return f"{k.upper() if len(k) <= 4 else k.capitalize()} is {GLOSSARY[k]}"


_CTX_WORDS = re.compile(r"\b(why|trade|ticket|this|it|explain|verdict|vote|votes|approve|reject|result|stop|target|sl|tp|risk|entry|status|what happened|how)\b", re.I)


_CTX_WORDS = re.compile(r"\b(why|trade|ticket|this|it|explain|verdict|vote|votes|approve|reject|result|stop|target|sl|tp|risk|entry|status|what happened|how)\b", re.I)


def try_context(q: str, seat: str, ctx: str | None) -> str | None:
    """Offline reading of the reference line about the ticket the operator is asking about (only restates recorded facts)."""
    if not ctx or not _CTX_WORDS.search(q):
        return None
    body = ctx.rstrip(". ")
    return f"{seat.title()} desk, reading the ticket record — {body}."


# --------------------------------------------------------------------------------------------- live-floor intents
SEAT_TAIL = {
    "ATLAS": "From the chart desk: I read this through trend structure and momentum.",
    "QUANTA": "From the quant desk: judge it by expectancy and sample size, not by any single result.",
    "MERIDIAN": "From the macro desk: watch the currency blocs and correlation — one bloc can hide several 'different' trades.",
    "VOLTA": "From the volatility desk: costs and liquidity decide whether an edge survives.",
    "VECTOR": "From the risk desk: total open risk and correlated exposure matter more than any single idea.",
    "NAVEED": "From the CEO's chair: I weigh the panel, the record and the correlated risk before I rule.",
    "DROSOPHILA": "From the hunter: my hunger is only a hint until I have enough realised outcomes.",
}


def _fmt_order(o: dict) -> str:
    v = o.get("verdict") or o.get("status", "").replace("_", " ")
    r = f", {o['r']:+.2f}R" if o.get("r") is not None else (f", paper {o['paper']}" if o.get("paper") not in (None, "pending") else "")
    return f"{o['id']} {o['dir']} {o['sym']} ({v}{r})"


def _votes_line(o: dict) -> str:
    parts = [f"{v['seat']} {'approved' if v['vote'] == 'approve' else 'rejected'} {v.get('confidence', '')}%".replace(" %", "%") for v in o.get("votes", [])]
    if o.get("ceo"):
        parts.append(f"CEO NAVEED {'approved' if o['ceo']['vote'] == 'approve' else 'rejected'} {o['ceo'].get('confidence', '')}%".replace(" %", "%"))
    return "; ".join(parts) or "no judge has ruled yet"


def try_floor(q: str, seat: str, F: dict | None) -> str | None:
    if not F:
        return None
    s = q.lower()
    S, orders, tape = F.get("stats", {}), F.get("orders", []), F.get("tape", {})
    tail = " " + SEAT_TAIL.get(seat, "")
    # a specific symbol asked about
    syms = [k for k in tape if len(k) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(k.lower()) + r"(?![a-z0-9])", s)]
    if syms and not re.search(r"\b(capital|currency of)\b", s):
        k = max(syms, key=len)
        t = tape[k]
        mine = [o for o in orders if o["sym"] == k]
        extra = (" Tickets on it: " + "; ".join(_fmt_order(o) for o in mine[:3]) + ".") if mine else " No ticket on it right now."
        return f"{k} ({t['c']}) is at {t['p']} ({t['ch']:+.2f}% recently), regime {t['r']}.{extra} (Prices here are {F.get('mode', 'synthetic')}.)"
    if re.search(r"\b(what can you do|help me|what do you know|capabilit)", s):
        return ("I can explain trading and market concepts (indicators, risk, order types, FX/crypto/stocks), report on the live floor "
                "(performance, open trades, the last verdict and who decided it, what the fly is hunting, prices), and do maths, conversions, "
                "dates and country facts. For open-ended questions beyond that I need the language model connection — Settings → LLM seats → Diagnose shows why it is offline.")
    if re.search(r"\b(mt5|metatrader|bridge)\b", s):
        m = F.get("mt5", {})
        return f"MT5 bridge is {'connected' if m.get('connected') else 'not connected'}; auto-send is {'on' if m.get('auto') else 'off'}. Open Settings → MetaTrader 5 for the token and the bridge command."
    if re.search(r"\b(best|worst|top|most accurate|most reliable|smartest)\b.*\b(judge|seat|desk|analyst)\b|\bwhich judge\b|\bcalibrat|\bbias\b", s):
        J = F.get("judges", {})
        if J:
            rk = sorted(J.items(), key=lambda kv: -kv[1]["bias"])
            return ("Judge calibration (positive = has been leaning right, negative = has been approving losers or rejecting winners): "
                    + ", ".join(f"{k} {v['bias']:+.2f}" for k, v in rk) + f". {F.get('record', '')}")
    if re.search(r"\b(last|latest|recent|newest|previous)\b.*\b(trade|ticket|verdict|decision|ruling)\b|\bwhy\b.*\b(reject|accept|approv|exit|entry|declin|turn)", s):
        decided = [o for o in orders if o.get("verdict")]
        if decided:
            o = decided[0]
            what = "ACCEPTED (entry gate)" if o["verdict"] == "ENTRY" else "REJECTED (exit gate)"
            return (f"The latest decided trade is {_fmt_order(o)} — {what}, path '{o.get('path') or 'n/a'}'. Who decided: {_votes_line(o)}. "
                    f"Conviction {o['conviction']:.2f}, R:R {o['rr']:.2f}, regime {o.get('regime', '?')}. Click the trader in the hall or 'Full details' on the order card for every judge's reasoning." + tail)
        return "No trade has been decided yet — tickets are still walking the cabins."
    if re.search(r"\b(how are we|how('s| is) (it|the floor|everything) going|how('s| is) (the )?(desk|floor|team)|are we (winning|losing|profitable|making)|p ?& ?l|pnl|profit and loss|(our|total|net|overall) (profit|loss|results?|performance)|(our|current|floor.s|the floor.s) win rate|track record|so far today)\b", s):
        n = S.get("wins", 0) + S.get("losses", 0)
        wr = f"{100 * S['wins'] / n:.0f}%" if n else "n/a"
        return (f"So far: {S.get('tickets', 0)} tickets, {S.get('entry', 0)} sent to entry, {S.get('exit', 0)} to exit; {n} resolved paper trades with win rate {wr} "
                f"and total {S.get('sumR', 0):+.1f}R; {S.get('in_pipe', 0)}/9 pipe slots in use. {F.get('record', '')} (Paper results on {F.get('mode', 'synthetic')} prices — not real money.)" + tail)
    if re.search(r"\b(open|active|current|pipeline|in progress|running|live)\b.*\b(trade|trades|ticket|tickets|orders?|positions?)\b|\bwhat trades\b", s):
        act = [o for o in orders if not o.get("verdict") or o.get("paper") in ("pending", "filled")][:6]
        return ("Right now: " + "; ".join(_fmt_order(o) for o in act) + ".") if act else "There are no active trades at the moment."
    if re.search(r"\b(fly|drosophila|hunter|hunt|hunting|hunger|looking at|watching|scouting)\b", s):
        f = F.get("fly", {})
        fo = f.get("focus") or {}
        wl = ", ".join(f"{w['s']} {w['h']:.2f}" for w in (f.get("watch") or [])[:4])
        return (f"The fly-brain is in state {f.get('state', '?')}, focused on {fo.get('s', '?')} ({'long' if fo.get('dir', 0) > 0 else 'short'}, hunger {fo.get('hunger', 0):.2f} "
                f"vs threshold {f.get('threshold', 0):.2f}); watchlist {wl or 'empty'}; dopamine {f.get('dopamine', 0):+.2f} after {f.get('updates', 0)} outcome updates." + tail)
    if re.search(r"\b(should we trade|good time|market (mood|today|now|regime)|regimes?|what'?s the market)\b", s):
        rg = F.get("regimes", {})
        txt = ", ".join(f"{k} {v}" for k, v in sorted(rg.items(), key=lambda kv: -kv[1])[:4])
        return f"Regime mix across the watched universe: {txt}. The floor only trades when the hunter's conviction, cost, trend, R:R and correlation gates all pass, so 'should we trade' is answered scan by scan, not by the mood of the day." + tail
    if re.search(r"\b(debate|lesson|lessons|learned|learnt|doctrine|rule)\b", s):
        L = F.get("lessons", [])
        return ("Latest debate takeaways: " + " | ".join(L[-3:])) if L else "The judges have not finished a debate yet."
    return None


def floor_brief(F: dict) -> str:
    S = F.get("stats", {})
    n = S.get("wins", 0) + S.get("losses", 0)
    lines = [f"{S.get('tickets', 0)} tickets, {S.get('entry', 0)} entry / {S.get('exit', 0)} exit, {n} resolved paper trades, total {S.get('sumR', 0):+.1f}R, {S.get('in_pipe', 0)}/9 in pipe."]
    lines += [_fmt_order(o) + f" votes: {_votes_line(o)}" for o in F.get("orders", [])[:4]]
    f = F.get("fly", {})
    fo = f.get("focus") or {}
    lines.append(f"Fly: {f.get('state', '?')} on {fo.get('s', '?')}, hunger {fo.get('hunger', 0):.2f}.")
    return " ".join(lines)[:1500]


# --------------------------------------------------------------------------------------------- catch-all
def _keywords(q: str) -> list[str]:
    stop = set("the a an is are was were be to of in on for and or but if then so do does did can could would should will what why how when where who whom which whose i you we it this that these those with about tell me please give explain show".split())
    return [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-']{2,}", q) if w.lower() not in stop][:6]


def try_more_smalltalk(q: str, seat: str) -> str | None:
    s = q.lower().strip()
    if re.search(r"\b(joke|funny|make me laugh)\b", s):
        return kb.JOKES[sum(map(ord, s)) % len(kb.JOKES)]
    if re.search(r"\b(good night|goodnight|bye|goodbye|see you)\b", s):
        return "Good night — the floor keeps running. Come back any time."
    if re.search(r"\b(i love you|you are (great|awesome|amazing|the best)|good job|well done)\b", s):
        return "Thank you — that's kind. The credit belongs to the whole floor: the fly, the five judges and the CEO."
    if re.search(r"\b(sorry|my bad)\b", s) and len(s) < 30:
        return "No problem at all."
    if re.search(r"\b(are you (a )?(bot|ai|robot|human|real)|are you chatgpt)\b", s):
        return f"I'm the {seat} desk of the Soul Exter trading floor — a program, not a person. When a language model is reachable I answer with it; otherwise I use my built-in knowledge."
    if re.search(r"\b(favou?rite|opinion|do you like|do you think)\b", s):
        return "I'm a trading-floor assistant, so my 'opinions' are tied to the data: ask me about a symbol, a strategy or the day's results and I'll give you a reasoned view."
    return None


def smart_fallback(q: str, seat: str) -> str:
    """Never a bare refusal: say precisely what is missing and give the most useful next step."""
    kw = _keywords(q)
    s = q.lower()
    about = f" (\"{' '.join(kw[:4])}\")" if kw else ""
    if re.search(r"\b(write|code|script|program|function|essay|poem|story|email|letter|translate|summari[sz]e)\b", s):
        kind = "writing / coding / translation"
        why = "that needs a real language model to compose"
    elif re.search(r"\b(latest|news|today|current|right now|this week|score|weather|stock price of|who won)\b", s):
        kind = "live or recent information"
        why = "that needs internet access to fetch"
    elif re.search(r"\b(should i|which is better|recommend|best way|advice)\b", s):
        kind = "a personal recommendation"
        why = "that depends on details a language model would weigh with you"
    else:
        kind = "an open-ended question"
        why = "my built-in knowledge doesn't cover it"
    return (f"That looks like {kind}{about} — {why}. I'm running on built-in knowledge right now because no language model is reachable from this server, "
            "so I'd rather not guess. I can still answer: trading and market concepts (try 'what is RSI', 'how to size a position'), the live floor "
            "('how are we doing', 'why was the last trade rejected', 'what is the fly hunting', a symbol like 'EURUSD'), maths, unit conversions, "
            "dates and country facts. To get full ChatGPT-style answers to anything: open Settings → LLM seats → Diagnose (it shows exactly what is blocked), "
            "or run the app somewhere with internet access such as the Kaggle notebook.")


def _one(q: str, seat: str, context: str | None, floor: dict | None) -> str | None:
    r0 = try_smalltalk(q, seat) or try_math(q)
    if r0:
        return r0
    r1 = try_context(q, seat, context)
    if r1:
        return r1
    for fn in (lambda: try_units(q), lambda: try_time(q), lambda: try_floor(q, seat, floor), lambda: kb.country(q), lambda: try_facts(q),
               lambda: try_more_smalltalk(q, seat), lambda: kb.topic(q), lambda: try_glossary(q)):
        r = fn()
        if r:
            return r
    return None


_SPLIT = re.compile(r"\?+\s+|;\s+|\s+and\s+(?=(?:what|who|how|when|where|why|tell|explain|calculate|convert|define|which)\b)|\.\s+(?=[A-Z])", re.I)


def answer(question: str, seat: str = "ATLAS", context: str | None = None, floor: dict | None = None) -> str:
    q = question.strip()
    parts = [p.strip(" ?.") for p in _SPLIT.split(q) if p and p.strip(" ?.")]
    if len(parts) >= 2:      # a multi-part question: answer every part we can, say which ones we could not
        got, miss = [], []
        for p in parts[:5]:
            r = _one(p, seat, context, floor)
            (got if r else miss).append(r or p)
        if got and not miss:
            return " ".join(got)
        if got:
            return " ".join(got) + f" (I could not answer offline: \"{'; '.join(miss)}\".)"
    return _answer_single(q, seat, context, floor)


def _answer_single(q: str, seat: str, context: str | None, floor: dict | None) -> str:
    r0 = try_smalltalk(q, seat) or try_math(q)
    if r0:
        return r0
    r1 = try_context(q, seat, context)
    if r1:
        return r1
    for fn in (lambda: try_units(q), lambda: try_time(q), lambda: try_floor(q, seat, floor), lambda: kb.country(q), lambda: try_facts(q),
               lambda: try_more_smalltalk(q, seat), lambda: kb.topic(q), lambda: try_glossary(q)):
        r = fn()
        if r:
            return r
    return smart_fallback(q, seat)
