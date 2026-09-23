import httpx
import os
from dotenv import load_dotenv

load_dotenv()
url = f"https://graph.facebook.com/{os.getenv('INSTAGRAM_GRAPH_API_VERSION', 'v26.0')}/{os.getenv('FACEBOOK_PAGE_ID')}"
params = {
    "fields": "instagram_business_account",
    "access_token": os.getenv("INSTAGRAM_ACCESS_TOKEN"),
}
print(httpx.get(url, params=params).json())