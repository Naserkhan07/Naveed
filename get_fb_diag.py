import os

import httpx
from dotenv import load_dotenv

load_dotenv()
tok = os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("FACEBOOK_ACCESS_TOKEN")
ver = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v26.0")
base = f"https://graph.facebook.com/{ver}"

print("token starts with:", (tok or "")[:10], "...")
print("FACEBOOK_PAGE_ID in .env:", os.getenv("FACEBOOK_PAGE_ID"))

print("\n== 1) who is this token?  ==")
print(httpx.get(f"{base}/me", params={"access_token": tok}).json())

print("\n== 2) which pages can it see?  ==")
print(
    httpx.get(
        f"{base}/me/accounts",
        params={"access_token": tok, "fields": "id,name,instagram_business_account{id,username}"},
    ).json()
)