"""SOUL EXTER floor layout — the single source of truth.

Coordinates: x east, z SOUTH (arrival hall / plaza at +z), y up.  Everything the
NavGrid rasterises and everything the frontend draws comes from this module
(served verbatim on /api/layout).
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------- hall shell
HALL = (-46.0, -28.6, 46.0, 32.6)          # x0, z0, x1, z1
CEILING_H = 11.5
WALL_T = 0.4
SOUTH_WALL_Z = 31.6
PLAZA = (-50.0, 32.6, 50.0, 46.0)          # walkable apron
CURB_Z = 46.0
ROAD = (-60.0, 46.0, 60.0, 58.0)
NAV_BOUNDS = (-50.0, -30.0, 50.0, 46.0)    # walkable universe for the nav grid
NAV_CELL = 0.26
AGENT_RADIUS = 0.30

PALETTE = {
    "walls": 0xF4F6F9, "floor_a": "#f5f7fa", "floor_b": "#e9edf3",
    "grid": "rgba(110,140,180,0.09)", "inlay_a": 0xE2E8F1, "inlay_b": 0xE9EEF5,
    "plaza": 0xD9DEE6,
    "seat_colors": {
        "ATLAS": "#38bdf8", "QUANTA": "#a78bfa", "MERIDIAN": "#f59e0b",
        "VOLTA": "#f472b6", "VECTOR": "#22d3ee", "NAVEED": "#c084fc",
        "DROSOPHILA": "#34d399",
    },
}

# ------------------------------------------------------------------- cabins
CABIN_XS = [-30.4, -15.2, 0.0, 15.2, 30.4]
CABIN_W = 14.2
CABIN_Z0, CABIN_Z1 = -27.8, -19.4
JUDGE_DESK_Z, JUDGE_CHAIR_Z, HEAR_Z = -24.8, -26.5, -20.6
DOOR_W = 2.4
CORRIDOR_Z0, CORRIDOR_Z1 = -19.4, -12.0
CORRIDOR_MID_Z = -15.7
CABIN_SEATS = ["ATLAS", "QUANTA", "MERIDIAN", "VOLTA", "VECTOR"]
TICKER_CORRIDOR = {"y": 5.6, "w": 52.0, "x": 0.0, "z": CORRIDOR_MID_Z}
PILLARS_CORRIDOR = [(-38.0, CORRIDOR_MID_Z), (-12.0, CORRIDOR_MID_Z), (12.0, CORRIDOR_MID_Z), (38.0, CORRIDOR_MID_Z)]

# --------------------------------------------------------------- trading pit
DESK_W, DESK_D = 2.4, 1.6
POD_GAP, AISLE = 0.4, 3.3
ROW_ZS = [-8.8, -3.0, 2.8, 8.6]
BLOCK_STARTS = [-43.2, -13.8]
PODS_PER_BLOCK = 3
POD_W = 2 * DESK_W + POD_GAP
COLONNADE_X = -17.3
COLONNADE_ZS = [-10.6, -1.0, 8.6]
PIT_TICKER = {"x": -6.0, "z": -1.0, "y": 6.6, "w": 40.0}

# ---------------------------------------------------------------- east wing
CONCOURSE = (13.6, -12.0, 17.8, 31.6)
EXEC = (19.0, -12.0, 42.2, 0.4)
EXEC_DOOR_Z = -5.8
VAULT = (19.0, 2.6, 42.2, 10.6)
VAULT_DOOR_Z = 6.6
DEBATE = (18.6, 12.8, 42.2, 30.4)
DEBATE_DOOR_Z = 21.5
DEBATE_CENTER = (31.0, 21.6)
DEBATE_RADIUS = 4.9

# ------------------------------------------------------------ arrival / plaza
ENTRY_X, EXIT_X, GATE_W = -17.5, 9.5, 3.4
SECURITY_DESK = (-17.5, 24.8)
LOBBY_TICKER = {"x": -8.0, "z": 14.2, "y": 3.8, "w": 26.0}
LOBBY_CENTER = (0.0, 19.0)


def _r(v: float) -> float:
    return round(v, 3)


def desks() -> list[dict[str, Any]]:
    out = []
    idx = 0
    for r, z in enumerate(ROW_ZS):
        for b, bx in enumerate(BLOCK_STARTS):
            for p in range(PODS_PER_BLOCK):
                px = bx + p * (POD_W + AISLE)
                for k in range(2):
                    cx = px + DESK_W / 2 + k * (DESK_W + POD_GAP)
                    out.append({
                        "id": idx, "row": r, "block": b, "pod": p, "x": _r(cx), "z": z,
                        "w": DESK_W, "d": DESK_D,
                        "seat": [_r(cx), _r(z + 1.5)], "stand": [_r(cx), _r(z + 2.4)],
                    })
                    idx += 1
    return out


def cabins() -> list[dict[str, Any]]:
    out = []
    for i, cx in enumerate(CABIN_XS):
        out.append({
            "id": i + 1, "seat": CABIN_SEATS[i], "x": cx, "w": CABIN_W,
            "z0": CABIN_Z0, "z1": CABIN_Z1, "desk": [cx, JUDGE_DESK_Z], "chair": [cx, JUDGE_CHAIR_Z],
            "hear": [cx, HEAR_Z], "door": [cx, CABIN_Z1], "outside": [cx, CORRIDOR_MID_Z + 0.4],
        })
    return out


def debate_seats() -> list[list[float]]:
    cx, cz = DEBATE_CENTER
    return [[_r(cx + DEBATE_RADIUS * math.cos(a)), _r(cz + DEBATE_RADIUS * math.sin(a))]
            for a in [2 * math.pi * k / 6 + math.pi / 6 for k in range(6)]]


def waypoints() -> dict[str, list[float]]:
    wp: dict[str, list[float]] = {
        "entry_outside": [ENTRY_X, 36.5], "entry_inside": [ENTRY_X, 29.4],
        "exit_outside": [EXIT_X, 36.5], "exit_inside": [EXIT_X, 29.4],
        "lobby_center": list(LOBBY_CENTER),
        "concourse_entry": [15.7, -14.2], "concourse_lobby": [15.7, 19.0],
        "concourse_mid": [15.7, 3.0],
        "exec_outside": [15.7, EXEC_DOOR_Z], "exec_door": [EXEC[0], EXEC_DOOR_Z],
        "exec_inside": [22.4, EXEC_DOOR_Z], "exec_hear": [30.4, EXEC_DOOR_Z],
        "exec_ceo": [40.5, EXEC_DOOR_Z],
        "vault_outside": [15.7, VAULT_DOOR_Z], "vault_door": [VAULT[0], VAULT_DOOR_Z],
        "vault_inside": [22.4, VAULT_DOOR_Z], "vault_deep": [33.0, VAULT_DOOR_Z],
        "debate_outside": [15.7, DEBATE_DOOR_Z], "debate_door": [DEBATE[0], DEBATE_DOOR_Z],
        "debate_inside": [22.4, DEBATE_DOOR_Z],
        "boulevard_n": [-17.4, -13.0], "boulevard_s": [-17.4, 12.0],
    }
    for c in cabins():
        i = c["id"]
        wp[f"cabin_{i}_outside"] = c["outside"]
        wp[f"cabin_{i}_door"] = c["door"]
        wp[f"cabin_{i}_hear"] = c["hear"]
        wp[f"cabin_{i}_judge"] = c["chair"]
    for k, s in enumerate(debate_seats()):
        wp[f"debate_seat_{k}"] = s
    for d in desks():
        wp[f"desk_{d['id']}_seat"] = d["seat"]
        wp[f"desk_{d['id']}_stand"] = d["stand"]
    return wp


# --------------------------------------------------------- obstacles / walls
def _rect(x0, z0, x1, z1, tag="wall"):
    return {"kind": "rect", "x0": _r(min(x0, x1)), "z0": _r(min(z0, z1)),
            "x1": _r(max(x0, x1)), "z1": _r(max(z0, z1)), "tag": tag}


def _hwall(z, xa, xb, tag="wall", t=WALL_T):
    return _rect(xa, z - t / 2, xb, z + t / 2, tag)


def _vwall(x, za, zb, tag="wall", t=WALL_T):
    return _rect(x - t / 2, za, x + t / 2, zb, tag)


def _split_h(z, xa, xb, gaps, tag="wall", t=WALL_T):
    """horizontal wall xa..xb with door gaps [(centre, width)]"""
    segs, cur = [], xa
    for c, w in sorted(gaps):
        segs.append(_hwall(z, cur, c - w / 2, tag, t))
        cur = c + w / 2
    segs.append(_hwall(z, cur, xb, tag, t))
    return [s for s in segs if s["x1"] - s["x0"] > 0.01]


def _split_v(x, za, zb, gaps, tag="wall", t=WALL_T):
    segs, cur = [], za
    for c, w in sorted(gaps):
        segs.append(_vwall(x, cur, c - w / 2, tag, t))
        cur = c + w / 2
    segs.append(_vwall(x, cur, zb, tag, t))
    return [s for s in segs if s["z1"] - s["z0"] > 0.01]


def walls() -> list[dict[str, Any]]:
    w: list[dict[str, Any]] = []
    x0, z0, x1, _ = HALL
    # outer shell
    w.append(_hwall(z0 - WALL_T / 2 + 0.0, x0 - WALL_T, x1 + WALL_T, "shell"))
    w.append(_vwall(x0 - WALL_T / 2, z0, SOUTH_WALL_Z, "shell"))
    w.append(_vwall(x1 + WALL_T / 2, z0, SOUTH_WALL_Z, "shell"))
    w += _split_h(SOUTH_WALL_Z, x0 - WALL_T, x1 + WALL_T,
                  [(ENTRY_X, GATE_W), (EXIT_X, GATE_W)], "shell")
    # cabins: back walls, side walls, glass fronts with doors
    for cx in CABIN_XS:
        hx = CABIN_W / 2
        w.append(_hwall(CABIN_Z0, cx - hx, cx + hx, "cabin"))
        w.append(_vwall(cx - hx, CABIN_Z0, CABIN_Z1, "cabin", 0.2))
        w.append(_vwall(cx + hx, CABIN_Z0, CABIN_Z1, "cabin", 0.2))
        w += _split_h(CABIN_Z1, cx - hx, cx + hx, [(cx, DOOR_W)], "glass", 0.12)
    # east wing chambers
    for (bx0, bz0, bx1, bz1), door, tag in ((EXEC, EXEC_DOOR_Z, "exec"), (VAULT, VAULT_DOOR_Z, "vault"),
                                            (DEBATE, DEBATE_DOOR_Z, "debate")):
        w.append(_hwall(bz0, bx0, bx1, tag))
        w.append(_hwall(bz1, bx0, bx1, tag))
        w.append(_vwall(bx1, bz0, bz1, tag))
        w += _split_v(bx0, bz0, bz1, [(door, DOOR_W)], tag)
    return w


def props() -> list[dict[str, Any]]:
    """Solid furniture / fixtures (nav-blocking)."""
    p: list[dict[str, Any]] = []
    for c in cabins():
        cx = c["x"]
        p.append({**_rect(cx - 1.6, JUDGE_DESK_Z - 0.55, cx + 1.6, JUDGE_DESK_Z + 0.55), "tag": "judge_desk", "seat": c["seat"]})
    # pit desks as pods (two desks + gap is one solid block)
    ds = desks()
    for i in range(0, len(ds), 2):
        a, b = ds[i], ds[i + 1]
        p.append({**_rect(a["x"] - DESK_W / 2, a["z"] - DESK_D / 2, b["x"] + DESK_W / 2, a["z"] + DESK_D / 2), "tag": "desk_pod"})
    for z in COLONNADE_ZS:
        p.append({"kind": "circle", "x": COLONNADE_X, "z": z, "r": 0.4, "tag": "column"})
    for (x, z) in PILLARS_CORRIDOR:
        p.append({"kind": "circle", "x": x, "z": z, "r": 0.45, "tag": "pillar"})
    # executive chamber: CEO desk + side credenza
    p.append({**_rect(37.6, EXEC_DOOR_Z - 2.3, 39.4, EXEC_DOOR_Z + 2.3), "tag": "ceo_desk"})
    p.append({**_rect(41.3, -11.4, 41.9, -0.2), "tag": "credenza"})
    # vault racks
    p.append({**_rect(22.0, 3.3, 41.4, 4.1), "tag": "rack"})
    p.append({**_rect(22.0, 9.1, 41.4, 9.9), "tag": "rack"})
    # debate: round table
    p.append({"kind": "circle", "x": DEBATE_CENTER[0], "y": 0, "z": DEBATE_CENTER[1], "r": 2.6, "tag": "debate_table"})
    # arrival hall
    sx, sz = SECURITY_DESK
    p.append({**_rect(sx - 2.0, sz - 0.5, sx + 2.0, sz + 0.5), "tag": "security_desk"})
    for gx in (ENTRY_X, EXIT_X):
        for off in (-1.35, 1.35):
            p.append({**_rect(gx + off - 0.25, 27.9, gx + off + 0.25, 29.1), "tag": "turnstile"})
    for (x, z, w, d) in ((-40.0, 19.0, 1.1, 4.2), (-40.0, 25.5, 1.1, 4.2), (-8.0, 26.5, 4.4, 1.1), (4.0, 26.5, 4.4, 1.1)):
        p.append({**_rect(x - w / 2, z - d / 2, x + w / 2, z + d / 2), "tag": "sofa"})
    for (x, z) in ((-44.6, 14.0), (-44.6, 30.4), (-24.0, 30.6), (-11.0, 30.6), (2.5, 30.6), (16.0, 30.6), (-30.0, 14.0)):
        p.append({"kind": "circle", "x": x, "z": z, "r": 0.55, "tag": "planter"})
    # plaza
    p.append({"kind": "circle", "x": -4.0, "z": 40.0, "r": 3.4, "tag": "fountain"})
    for (x, z) in ((-40.0, 38.0), (-28.0, 42.0), (22.0, 38.0), (36.0, 42.0), (44.0, 36.0)):
        p.append({"kind": "circle", "x": x, "z": z, "r": 0.5, "tag": "tree"})
    for x in range(-48, 49, 12):
        p.append({"kind": "circle", "x": float(x), "z": 44.6, "r": 0.25, "tag": "lamp"})
    return p


def decor() -> dict[str, Any]:
    return {
        "video_walls": [
            {"id": "global_markets", "title": "GLOBAL MARKETS", "x": -45.75, "z": 22.0, "y": 1.4, "w": 15.0, "h": 6.6, "facing": "east"},
            {"id": "south_a", "title": "MARKET WALL A", "x": -34.0, "z": 31.35, "y": 1.6, "w": 9.0, "h": 4.6, "facing": "north"},
            {"id": "south_b", "title": "MARKET WALL B", "x": -4.0, "z": 31.35, "y": 1.6, "w": 9.0, "h": 4.6, "facing": "north"},
        ],
        "signs": [
            {"text": "SOUL EXTER", "x": -4.0, "y": 8.4, "z": 31.3, "w": 12.0, "facing": "north"},
            {"text": "TRADING PIT", "x": -17.4, "y": 8.6, "z": -13.2, "w": 9.0, "facing": "south"},
            {"text": "DESK TIER", "x": 8.0, "y": 8.6, "z": 12.2, "w": 7.0, "facing": "north"},
            {"text": "WELCOME", "x": ENTRY_X, "y": 5.6, "z": 31.3, "w": 4.0, "facing": "north"},
            {"text": "EXIT", "x": EXIT_X, "y": 5.6, "z": 31.3, "w": 3.0, "facing": "north"},
            {"text": "EXECUTIVE", "x": 18.9, "y": 5.4, "z": EXEC_DOOR_Z, "w": 4.0, "facing": "west"},
            {"text": "VAULT", "x": 18.9, "y": 5.4, "z": VAULT_DOOR_Z, "w": 3.0, "facing": "west"},
            {"text": "DEBATE", "x": 18.5, "y": 5.4, "z": DEBATE_DOOR_Z, "w": 3.4, "facing": "west"},
        ],
        "tickers": {"corridor": TICKER_CORRIDOR, "pit": PIT_TICKER, "lobby": LOBBY_TICKER},
        "curb_z": CURB_Z, "road": list(ROAD),
        "taxis": [{"x": -30.0, "z": 50.5, "rot": 0.0}, {"x": 12.0, "z": 53.5, "rot": math.pi}, {"x": 36.0, "z": 50.5, "rot": 0.0}],
        "lamps": [{"x": float(x), "z": 44.6} for x in range(-48, 49, 12)],
        "trees": [{"x": x, "z": z} for (x, z) in ((-40.0, 38.0), (-28.0, 42.0), (22.0, 38.0), (36.0, 42.0), (44.0, 36.0))],
        "fountain": {"x": -4.0, "z": 40.0, "r": 3.4},
        "sofas": [{"x": x, "z": z, "w": w, "d": d} for (x, z, w, d) in ((-40.0, 19.0, 1.1, 4.2), (-40.0, 25.5, 1.1, 4.2), (-8.0, 26.5, 4.4, 1.1), (4.0, 26.5, 4.4, 1.1))],
        "planters": [{"x": x, "z": z} for (x, z) in ((-44.6, 14.0), (-44.6, 30.4), (-24.0, 30.6), (-11.0, 30.6), (2.5, 30.6), (16.0, 30.6), (-30.0, 14.0))],
        "security_desk": list(SECURITY_DESK),
        "turnstiles": [{"x": gx + off, "z": 28.5} for gx in (ENTRY_X, EXIT_X) for off in (-1.35, 1.35)],
        "pathways": [
            # inlay strips, x0,z0,x1,z1 (tone alternates)
            [-46.0, CORRIDOR_MID_Z - 0.35, 46.0, CORRIDOR_MID_Z + 0.35],
            [-17.9, -12.0, -16.9, 32.0],
            [ENTRY_X - 1.0, 12.0, ENTRY_X + 1.0, SOUTH_WALL_Z],
            [EXIT_X - 1.0, 12.0, EXIT_X + 1.0, SOUTH_WALL_Z],
            [15.4, -12.0, 16.0, 31.6],
        ],
        "aprons": [list(PLAZA)],
    }


def openings() -> list[dict[str, Any]]:
    """gates and doors carved into the walls (frontend builds lintels / frames from these)"""
    o = [{"id": "entry_gate", "kind": "gate", "axis": "x", "x": ENTRY_X, "z": SOUTH_WALL_Z, "w": GATE_W},
         {"id": "exit_gate", "kind": "gate", "axis": "x", "x": EXIT_X, "z": SOUTH_WALL_Z, "w": GATE_W}]
    for c in cabins():
        o.append({"id": f"cabin_{c['id']}_door", "kind": "glass_door", "axis": "x", "x": c["x"], "z": CABIN_Z1, "w": DOOR_W})
    o.append({"id": "exec_door", "kind": "door", "axis": "z", "x": EXEC[0], "z": EXEC_DOOR_Z, "w": DOOR_W})
    o.append({"id": "vault_door", "kind": "door", "axis": "z", "x": VAULT[0], "z": VAULT_DOOR_Z, "w": DOOR_W})
    o.append({"id": "debate_door", "kind": "door", "axis": "z", "x": DEBATE[0], "z": DEBATE_DOOR_Z, "w": DOOR_W})
    return o


def layout() -> dict[str, Any]:
    return {
        "hall": [HALL[0], HALL[1], HALL[2], HALL[3]],
        "ceiling": CEILING_H,
        "palette": PALETTE,
        "nav": {"cell": NAV_CELL, "bounds": list(NAV_BOUNDS), "radius": AGENT_RADIUS},
        "cabins": cabins(),
        "corridor": {"z0": CORRIDOR_Z0, "z1": CORRIDOR_Z1, "mid": CORRIDOR_MID_Z},
        "desks": desks(),
        "pit": {"rows": ROW_ZS, "blocks": BLOCK_STARTS, "colonnade": {"x": COLONNADE_X, "zs": COLONNADE_ZS},
                "boulevard": [BLOCK_STARTS[0] + PODS_PER_BLOCK * POD_W + (PODS_PER_BLOCK - 1) * AISLE, BLOCK_STARTS[1]]},
        "concourse": list(CONCOURSE),
        "executive": {"box": list(EXEC), "door_z": EXEC_DOOR_Z, "ceo": [40.5, EXEC_DOOR_Z]},
        "vault": {"box": list(VAULT), "door_z": VAULT_DOOR_Z},
        "debate": {"box": list(DEBATE), "door_z": DEBATE_DOOR_Z, "center": list(DEBATE_CENTER),
                   "radius": DEBATE_RADIUS, "seats": debate_seats()},
        "gates": {"entry": {"x": ENTRY_X, "w": GATE_W, "z": SOUTH_WALL_Z}, "exit": {"x": EXIT_X, "w": GATE_W, "z": SOUTH_WALL_Z}},
        "south_wall_z": SOUTH_WALL_Z,
        "walls": walls(),
        "openings": openings(),
        "props": props(),
        "decor": decor(),
        "waypoints": waypoints(),
        "cameras": {
            "overview": {"pos": [8, 44, 82], "look": [0, 0, 0]},
            "pit": {"pos": [-14, 15, 24], "look": [-14, 0, 0.5]},
            "corridor": {"pos": [0, 5.6, -6.5], "look": [0, 3.2, -19]},
            "cabins": {"pos": [0, 9.5, -8], "look": [0, 1.2, -24]},
            "executive": {"pos": [30, 6.5, 3.5], "look": [30, 1.2, -6]},
            "debate": {"pos": [24, 7, 33], "look": [31, 1.0, 21.6]},
            "gates": {"pos": [-4, 5.5, 46], "look": [-4, 1.5, 31.6]},
            "tape": {"pos": [-34, 10, 4], "look": [-44.5, 2.6, -1.4]},
        },
    }
