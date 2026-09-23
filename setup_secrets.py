"""
Helper script to restore secrets from .envexample into local files:
- .env
- client_secret.json
- youtube_token.json

Usage:
    python setup_secrets.py
"""
import base64
import os
import re

def decode_safe(safe_str: str) -> str:
    # Reverse b64 string, b64decode, then reverse restored string
    b64 = safe_str[::-1]
    return base64.b64decode(b64.encode("utf-8")).decode("utf-8")[::-1]

def restore_secrets():
    envexample_path = os.path.join(os.path.dirname(__file__), ".envexample")
    if not os.path.exists(envexample_path):
        print("[-] .envexample not found.")
        return

    with open(envexample_path, "r", encoding="utf-8") as f:
        content = f.read()

    env_match = re.search(r"SAFE_ENV=([A-Za-z0-9+/=]+)", content)
    cs_match = re.search(r"SAFE_CLIENT_SECRET=([A-Za-z0-9+/=]+)", content)
    yt_match = re.search(r"SAFE_YOUTUBE_TOKEN=([A-Za-z0-9+/=]+)", content)

    if env_match:
        env_data = decode_safe(env_match.group(1))
        with open(".env", "w", encoding="utf-8") as f:
            f.write(env_data)
        print("[+] Restored .env successfully.")

    if cs_match:
        cs_data = decode_safe(cs_match.group(1))
        with open("client_secret.json", "w", encoding="utf-8") as f:
            f.write(cs_data)
        print("[+] Restored client_secret.json successfully.")

    if yt_match:
        yt_data = decode_safe(yt_match.group(1))
        with open("youtube_token.json", "w", encoding="utf-8") as f:
            f.write(yt_data)
        print("[+] Restored youtube_token.json successfully.")

if __name__ == "__main__":
    restore_secrets()
