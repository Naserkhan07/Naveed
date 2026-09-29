"""Stand-in for the browser relay worker (frontend/src/relay.ts): answers queued LLM jobs with canned model output.
Usage: python tests/mock_relay.py <seconds>   (with the backend running and its LLM path blocked)"""
import itertools
import json
import sys
import time
import urllib.request


def post(u, b):
    r = urllib.request.Request("http://localhost:8000" + u, json.dumps(b).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=30))


c, n = itertools.count(), 0
end = time.time() + float(sys.argv[1])
while time.time() < end:
    for j in post("/api/relay/next", {"max": 3})["jobs"]:
        txt = " ".join(m["content"] for m in j["messages"])
        if '"judges"' in txt:
            k = next(c)
            one = lambda i: {"vote": "approve" if (k + i) % 3 else "reject", "confidence": 55 + (k + i) % 35, "thesis": f"mock thesis {k}.{i}", "risk": "mock risk", "reason": f"mock reason {k}.{i}"}
            out = json.dumps({"judges": [{"seat": s, **one(i)} for i, s in enumerate(["ATLAS", "QUANTA", "MERIDIAN", "VOLTA", "VECTOR"])], "ceo": one(7)})
        elif "json" in txt.lower():
            k = next(c)
            out = json.dumps({"vote": "approve" if k % 3 else "reject", "confidence": 60 + k % 30, "thesis": f"mock LLM thesis {k}",
                              "risk": "mock risk", "reason": f"mock LLM reason {k}"})
        else:
            out = "Mock debate line: I would size it small and wait for confirmation."
        post("/api/relay/result", {"id": j["id"], "text": out})
        n += 1
    time.sleep(0.5)
print("served", n)
