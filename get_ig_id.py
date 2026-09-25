import os

import httpx
from dotenv import load_dotenv

load_dotenv()
_graph_version = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v26.0")
_page_id = os.getenv("FACEBOOK_PAGE_ID")
url = f"https://graph.facebook.com/{_graph_version}/{_page_id}"
params = {
    "fields": "instagram_business_account",
    "access_token": os.getenv("INSTAGRAM_ACCESS_TOKEN"),
}
print(httpx.get(url, params=params).json())