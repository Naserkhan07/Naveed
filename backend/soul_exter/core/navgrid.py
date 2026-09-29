"""NavGrid: 0.26 m cells rasterised from layout.py, 8-connected A*, string-pulled."""
from __future__ import annotations

import heapq
import math
from typing import Iterable

import numpy as np

from . import layout as L

SQRT2 = math.sqrt(2.0)


class NavGrid:
    def __init__(self, cell: float = L.NAV_CELL, bounds=L.NAV_BOUNDS, radius: float = L.AGENT_RADIUS):
        self.cell = cell
        self.x0, self.z0, x1, z1 = bounds
        self.w = int(math.ceil((x1 - self.x0) / cell))
        self.h = int(math.ceil((z1 - self.z0) / cell))
        self.radius = radius
        self.raw_free = np.zeros((self.h, self.w), dtype=bool)   # true geometry
        self._paint_floor()
        self._paint_solids()
        self.free = self._inflate(self.raw_free, radius)         # centre-walkable
        self._free_list = self.free.ravel().tolist()
        self._cache: dict[tuple, list[tuple[float, float]]] = {}
        self.wp = {k: (float(v[0]), float(v[1])) for k, v in L.waypoints().items()}

    # ---------------------------------------------------------------- raster
    def _idx(self, x: float, z: float) -> tuple[int, int]:
        return int(math.floor((z - self.z0) / self.cell)), int(math.floor((x - self.x0) / self.cell))

    def _slice(self, xa, za, xb, zb):
        iz0, ix0 = self._idx(xa, za)
        iz1, ix1 = self._idx(xb, zb)
        return (max(iz0, 0), min(iz1 + 1, self.h), max(ix0, 0), min(ix1 + 1, self.w))

    def _paint_floor(self):
        hx0, hz0, hx1, hz1 = L.HALL
        for box in ((hx0, hz0, hx1, L.SOUTH_WALL_Z), (hx0, L.SOUTH_WALL_Z, hx1, hz1), L.PLAZA):
            a, b, c, d = self._slice(*box)
            self.raw_free[a:b, c:d] = True
        # walkable strip through the gates is covered by the two boxes above (walls carve later)

    def _paint_solids(self):
        for w in L.walls():
            a, b, c, d = self._slice(w["x0"], w["z0"], w["x1"], w["z1"])
            self.raw_free[a:b, c:d] = False
        for p in L.props():
            if p["kind"] == "rect":
                a, b, c, d = self._slice(p["x0"], p["z0"], p["x1"], p["z1"])
                self.raw_free[a:b, c:d] = False
            else:
                r = p["r"]
                a, b, c, d = self._slice(p["x"] - r, p["z"] - r, p["x"] + r, p["z"] + r)
                zz, xx = np.mgrid[a:b, c:d]
                cx = self.x0 + (xx + 0.5) * self.cell
                cz = self.z0 + (zz + 0.5) * self.cell
                m = (cx - p["x"]) ** 2 + (cz - p["z"]) ** 2 <= r * r
                self.raw_free[a:b, c:d] &= ~m

    @staticmethod
    def _inflate(free: np.ndarray, radius_cells_m: float) -> np.ndarray:
        rf = radius_cells_m / L.NAV_CELL
        r = int(math.ceil(rf))
        blocked = ~free
        out = blocked.copy()
        for dz in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dz * dz > rf * rf + 0.01:
                    continue
                sh = np.zeros_like(blocked)
                zs = slice(max(dz, 0), blocked.shape[0] + min(dz, 0))
                zd = slice(max(-dz, 0), blocked.shape[0] + min(-dz, 0))
                xs = slice(max(dx, 0), blocked.shape[1] + min(dx, 0))
                xd = slice(max(-dx, 0), blocked.shape[1] + min(-dx, 0))
                sh[zd, xd] = blocked[zs, xs]
                out |= sh
        return ~out

    # ---------------------------------------------------------------- queries
    def cell_of(self, x: float, z: float) -> tuple[int, int]:
        iz, ix = self._idx(x, z)
        return min(max(iz, 0), self.h - 1), min(max(ix, 0), self.w - 1)

    def center(self, iz: int, ix: int) -> tuple[float, float]:
        return self.x0 + (ix + 0.5) * self.cell, self.z0 + (iz + 0.5) * self.cell

    def walkable(self, x: float, z: float) -> bool:
        iz, ix = self._idx(x, z)
        return 0 <= iz < self.h and 0 <= ix < self.w and bool(self.free[iz, ix])

    def solid_free(self, x: float, z: float) -> bool:
        """true-geometry (uninflated) check — used by the navmesh-safety smoke test"""
        iz, ix = self._idx(x, z)
        return 0 <= iz < self.h and 0 <= ix < self.w and bool(self.raw_free[iz, ix])

    def nearest_free(self, x: float, z: float, maxr: int = 12) -> tuple[int, int]:
        iz, ix = self.cell_of(x, z)
        if self.free[iz, ix]:
            return iz, ix
        for r in range(1, maxr + 1):
            best, bd = None, 1e18
            for dz in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dz)) != r:
                        continue
                    a, b = iz + dz, ix + dx
                    if 0 <= a < self.h and 0 <= b < self.w and self.free[a, b]:
                        d = dx * dx + dz * dz
                        if d < bd:
                            best, bd = (a, b), d
            if best:
                return best
        raise ValueError(f"no free cell near {(x, z)}")

    def los(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        dx, dz = b[0] - a[0], b[1] - a[1]
        n = max(1, int(math.hypot(dx, dz) / (self.cell * 0.4)))
        fl, w = self._free_list, self.w
        for i in range(n + 1):
            t = i / n
            iz, ix = self._idx(a[0] + dx * t, a[1] + dz * t)
            if not (0 <= iz < self.h and 0 <= ix < self.w) or not fl[iz * w + ix]:
                return False
        return True

    # ------------------------------------------------------------------- A*
    def _astar(self, s: tuple[int, int], g: tuple[int, int]):
        w, h, fl = self.w, self.h, self._free_list
        sn, gn = s[0] * w + s[1], g[0] * w + g[1]
        if sn == gn:
            return [sn]
        gz, gx = g
        openh = [(0.0, 0.0, sn)]
        came = {sn: -1}
        gsc = {sn: 0.0}
        nb = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, SQRT2), (-1, 1, SQRT2), (1, -1, SQRT2), (1, 1, SQRT2))
        while openh:
            _, gc, cur = heapq.heappop(openh)
            if cur == gn:
                out = []
                while cur != -1:
                    out.append(cur)
                    cur = came[cur]
                return out[::-1]
            if gc > gsc.get(cur, 1e18):
                continue
            cz, cx = divmod(cur, w)
            for dz, dx, cost in nb:
                nz, nx = cz + dz, cx + dx
                if nz < 0 or nx < 0 or nz >= h or nx >= w:
                    continue
                nn = nz * w + nx
                if not fl[nn]:
                    continue
                if dz and dx and not (fl[cz * w + nx] and fl[nz * w + cx]):
                    continue
                ng = gc + cost
                if ng < gsc.get(nn, 1e18):
                    gsc[nn] = ng
                    came[nn] = cur
                    ddx, ddz = abs(nx - gx), abs(nz - gz)
                    hh = (ddx + ddz) + (SQRT2 - 2.0) * min(ddx, ddz)
                    heapq.heappush(openh, (ng + 1.1 * hh, ng, nn))
        return None

    def find_path(self, a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float]] | None:
        try:
            s, g = self.nearest_free(*a), self.nearest_free(*b)
        except ValueError:
            return None
        key = (s, g)
        hit = self._cache.get(key)
        if hit is not None:
            return list(hit)
        raw = self._astar(s, g)
        if raw is None:
            return None
        pts = [self.center(n // self.w, n % self.w) for n in raw]
        pts[0] = a if self.walkable(*a) else pts[0]
        # string pulling
        path = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not self.los(pts[i], pts[j]):
                j -= 1
            path.append(pts[j])
            i = j
        if self.walkable(*b):
            path[-1] = b
        self._cache[key] = path
        return list(path)

    def route(self, names: Iterable[str | tuple[float, float]]) -> list[tuple[float, float]] | None:
        pts = [self.wp[n] if isinstance(n, str) else n for n in names]
        full: list[tuple[float, float]] = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            seg = self.find_path(a, b)
            if seg is None:
                return None
            full.extend(seg[1:] if seg[0] == full[-1] or math.dist(seg[0], full[-1]) < 1e-6 else seg)
        return full

    def check_waypoints(self) -> list[str]:
        return [k for k, (x, z) in self.wp.items() if not self.walkable(x, z)]


_GRID: NavGrid | None = None


def get_grid() -> NavGrid:
    global _GRID
    if _GRID is None:
        _GRID = NavGrid()
    return _GRID
