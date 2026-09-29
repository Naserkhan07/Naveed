"""Built-in offline reasoning: honest, deterministic, never fabricates.

Handles arithmetic, percentages, unit conversion, date/time, greetings, a glossary (whole-word
matching), small fact tables — and otherwise says plainly that it needs a language model."""
from __future__ import annotations

import ast
import math
import operator as op
import re
import time

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


def try_context(q: str, seat: str, ctx: str | None) -> str | None:
    """Offline reading of the reference line about the ticket the operator is asking about (only restates facts, never invents)."""
    if not ctx or not _CTX_WORDS.search(q):
        return None
    body = ctx.rstrip(". ")
    return f"{seat.title()} desk, reading the ticket record — {body}. I cannot add reasoning beyond these recorded numbers while the language model is unreachable."


def answer(question: str, seat: str = "ATLAS", context: str | None = None) -> str:
    q = question.strip()
    r0 = try_smalltalk(q, seat) or try_math(q)
    if r0:
        return r0
    r1 = try_context(q, seat, context)
    if r1:
        return r1
    for fn in (lambda: try_smalltalk(q, seat), lambda: try_math(q), lambda: try_units(q), lambda: try_time(q),
               lambda: try_facts(q), lambda: try_glossary(q)):
        r = fn()
        if r:
            return r
    return ("I can't reach a language model right now, so I don't want to guess at that one and risk being wrong. "
            "Offline I can do arithmetic and percentages, unit conversions, the date and time, quick definitions of common terms "
            "and capital cities. Ask again once the connection is back and I'll give it a proper answer.")
