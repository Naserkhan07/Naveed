"""Run SOUL EXTER on a Kaggle GPU notebook: Ollama (the 6 seat LLMs) + FastAPI (serving the built UI) + a public tunnel.

Usage inside a notebook cell:   !python kaggle/run_kaggle.py
Env overrides (all optional):   SEAT_MODELS='ATLAS=llama3.1:8b,QUANTA=qwen2.5:7b,...'  PORT=8000  SKIP_PULL=1
Only the *notebook* installs extras (ollama, cloudflared, node); the app backend still needs just fastapi/uvicorn/httpx/numpy.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PORT = int(os.environ.get("PORT", "8000"))
MODELS = {"ATLAS": "llama3.1:8b", "QUANTA": "qwen2.5:7b", "MERIDIAN": "mistral:7b", "VOLTA": "gemma2:9b",
          "VECTOR": "phi3:mini", "NAVEED": "qwen2.5:7b", "DROSOPHILA": "qwen2.5:7b"}
for kv in filter(None, os.environ.get("SEAT_MODELS", "").split(",")):
    k, _, v = kv.partition("=")
    MODELS[k.strip().upper()] = v.strip()


def sh(cmd: str, **kw):
    print("$", cmd)
    return subprocess.run(cmd, shell=True, cwd=kw.pop("cwd", ROOT), **kw)


def wait_http(url: str, secs: int = 90) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:       # noqa: BLE001
            time.sleep(1.5)
    return False


def main():
    sh(f"{sys.executable} -m pip install -q -r backend/requirements.txt")
    # 1. Ollama
    if not shutil.which("ollama"):
        sh("curl -fsSL https://ollama.com/install.sh | sh")
    subprocess.Popen(["ollama", "serve"], stdout=open("/tmp/ollama.log", "w"), stderr=subprocess.STDOUT)
    if not wait_http("http://127.0.0.1:11434/api/tags"):
        print("ollama did not start; see /tmp/ollama.log - the app will still run on free GPT / offline reasoning")
    elif not os.environ.get("SKIP_PULL"):
        for m in sorted(set(MODELS.values())):
            sh(f"ollama pull {m}")
    # 2. seat config -> backend/data/llm_config.json (the app reads it at start-up; the UI can change it later)
    os.makedirs(os.path.join(ROOT, "backend", "data"), exist_ok=True)
    cfg = {s: {"provider": "ollama", "base_url": "http://127.0.0.1:11434/v1", "model": m, "api_key": ""} for s, m in MODELS.items()}
    json.dump(cfg, open(os.path.join(ROOT, "backend", "data", "llm_config.json"), "w"), indent=1)
    # 3. frontend build
    if not os.path.isdir(os.path.join(ROOT, "frontend", "dist")):
        if not shutil.which("npm"):
            sh("apt-get install -y -q nodejs npm")
        sh("npm install --no-audit --no-fund && npm run build", cwd=os.path.join(ROOT, "frontend"))
    # 4. backend
    subprocess.Popen([sys.executable, "-m", "uvicorn", "soul_exter.main:app", "--host", "0.0.0.0", "--port", str(PORT)],
                     cwd=os.path.join(ROOT, "backend"))
    if not wait_http(f"http://127.0.0.1:{PORT}/api/health"):
        sys.exit("backend failed to start")
    print(f"backend up on :{PORT}")
    # 5. public tunnel
    if not shutil.which("cloudflared"):
        sh("curl -fsSL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /tmp/cloudflared")
    exe = shutil.which("cloudflared") or "/tmp/cloudflared"
    p = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:       # type: ignore[union-attr]
        m = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", line)
        if m:
            print("\n" + "=" * 60 + f"\n  SOUL EXTER is live at:  {m.group(0)}\n" + "=" * 60)
            print("  MT5 bridge (on your Windows PC):  set SOUL_URL=" + m.group(0))
            break
    p.wait()


if __name__ == "__main__":
    main()
