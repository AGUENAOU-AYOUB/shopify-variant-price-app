import requests
import json
import os
from dotenv import load_dotenv
import time

load_dotenv()
SHOP_DOMAIN = os.getenv("SHOP_DOMAIN")
API_TOKEN = os.getenv("API_TOKEN")
API_VERSION = "2024-04"

HEADERS = {
    "X-Shopify-Access-Token": API_TOKEN,
    "Content-Type": "application/json"
}

backup = {}

url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
while url:
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        break

    data = response.json()
    for product in data.get("products", []):
        product_id = product["id"]
        product_title = product["title"]
        metafield_url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
        mf_response = requests.get(metafield_url, headers=HEADERS)
        time.sleep(0.5)
        if mf_response.status_code == 200:
            for metafield in mf_response.json().get("metafields", []):
                if metafield["key"] == "base_price":
                    backup[product_title] = float(metafield["value"])
    link = response.headers.get("Link")
    if link and 'rel="next"' in link:
        url = [l.split(";")[0].strip("<>") for l in link.split(",") if 'rel="next"' in l][0]
    else:
        url = None

with open("base_price_backup.json", "w") as f:
    json.dump(backup, f, indent=4)

print("✅ Base prices backed up successfully!")
