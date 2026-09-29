"""Compact text view of the live floor, handed to the language model as grounding (no answers are generated here)."""
from __future__ import annotations


def _fmt_order(o: dict) -> str:
    v = o.get("verdict") or o.get("status", "").replace("_", " ")
    r = f", {o['r']:+.2f}R" if o.get("r") is not None else (f", paper {o['paper']}" if o.get("paper") not in (None, "pending") else "")
    return f"{o['id']} {o['dir']} {o['sym']} ({v}{r})"


def _votes_line(o: dict) -> str:
    parts = [f"{v['seat']} {'approved' if v['vote'] == 'approve' else 'rejected'} {v.get('confidence', '')}%".replace(" %", "%") for v in o.get("votes", [])]
    if o.get("ceo"):
        parts.append(f"CEO NAVEED {'approved' if o['ceo']['vote'] == 'approve' else 'rejected'} {o['ceo'].get('confidence', '')}%".replace(" %", "%"))
    return "; ".join(parts) or "no judge has ruled yet"


def floor_brief(F: dict) -> str:
    S = F.get("stats", {})
    n = S.get("wins", 0) + S.get("losses", 0)
    lines = [f"{S.get('tickets', 0)} tickets, {S.get('entry', 0)} entry / {S.get('exit', 0)} exit, {n} resolved paper trades, total {S.get('sumR', 0):+.1f}R, {S.get('in_pipe', 0)}/9 in pipe."]
    lines += [_fmt_order(o) + f" votes: {_votes_line(o)}" for o in F.get("orders", [])[:4]]
    f = F.get("fly", {})
    fo = f.get("focus") or {}
    lines.append(f"Fly: {f.get('state', '?')} on {fo.get('s', '?')}, hunger {fo.get('hunger', 0):.2f}.")
    return " ".join(lines)[:1500]
