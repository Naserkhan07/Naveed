"""Tiny factual lookup used only when no language model is reachable: Wikipedia summary, then DuckDuckGo instant answer.
Both are keyless. Tight timeouts + a breaker so an offline server never waits on them."""
from __future__ import annotations

import re
import time
from urllib.parse import quote

import httpx

UA = {"User-Agent": "SoulExterFloor/2.0 (trading-floor assistant)"}
_FACT_Q = re.compile(r"^\s*(what('s| is| are| was| were)|who('s| is| was| were)|define|tell me about|explain|meaning of|where is|when (was|did)|how (many|much|tall|far|old|big|long))\b", re.I)
_STRIP = re.compile(r"^\s*(what('s| is| are| was| were)|who('s| is| was| were)|define|tell me about|explain|meaning of|where is|when (was|did))\s+(a |an |the )?", re.I)


class Lookup:
    def __init__(self):
        self.cli = httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0), headers=UA, follow_redirects=True)
        self.fails = 0
        self.open_until = 0.0
        self.last_error = ""

    def wanted(self, q: str) -> bool:
        return bool(_FACT_Q.search(q)) and len(q) < 200

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def _bad(self, e: Exception):
        self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
        self.fails += 1
        if self.fails >= 2:
            self.open_until = time.monotonic() + 30.0
            self.fails = 0

    def wikipedia(self, q: str) -> tuple[str, str] | None:
        term = _STRIP.sub("", q).strip(" ?.!")
        if not term:
            return None
        r = self.cli.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": term, "srlimit": 1, "format": "json"})
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        r = self.cli.get("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(title.replace(" ", "_")))
        r.raise_for_status()
        j = r.json()
        txt = (j.get("extract") or "").strip()
        if not txt or j.get("type") == "disambiguation":
            return None
        sents = re.split(r"(?<=[.!?])\s+", txt)
        return " ".join(sents[:3]), f"web:wikipedia — {title}"

    def duck(self, q: str) -> tuple[str, str] | None:
        r = self.cli.get("https://api.duckduckgo.com/", params={"q": _STRIP.sub("", q).strip(" ?.!"), "format": "json", "no_html": 1, "skip_disambig": 1})
        r.raise_for_status()
        j = r.json()
        txt = (j.get("AbstractText") or j.get("Answer") or "").strip()
        return (txt, "web:duckduckgo") if txt else None

    def answer(self, q: str) -> tuple[str, str] | None:
        if not self.wanted(q) or not self.allow():
            return None
        for fn in (self.wikipedia, self.duck):
            try:
                r = fn(q)
                if r:
                    self.fails = 0
                    return r
            except Exception as e:     # noqa: BLE001
                self._bad(e)
                if not self.allow():
                    break
        return None
