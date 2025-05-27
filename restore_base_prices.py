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

with open("base_price_backup.json", "r") as f:
    backup = json.load(f)

for title, base_price in backup.items():
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json?title={title}"
    response = requests.get(url, headers=HEADERS)
    time.sleep(0.5)
    if response.status_code != 200:
        print(f"Error fetching product {title}")
        continue
    products = response.json().get("products", [])
    if not products:
        print(f"Product not found: {title}")
        continue
    product = products[0]
    product_id = product["id"]
    metafield_url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    mf_response = requests.get(metafield_url, headers=HEADERS)
    time.sleep(0.5)
    if mf_response.status_code == 200:
        existing_metafield = next((m for m in mf_response.json().get("metafields", []) if m["key"] == "base_price"), None)
        if existing_metafield:
            update_url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/metafields/{existing_metafield['id']}.json"
            data = {"metafield": {"id": existing_metafield["id"], "value": str(base_price), "type": "number_decimal"}}
            requests.put(update_url, headers=HEADERS, json=data)
            time.sleep(0.5)
        else:
            post_url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/metafields.json"
            data = {
                "metafield": {
                    "namespace": "custom",
                    "key": "base_price",
                    "value": str(base_price),
                    "type": "number_decimal",
                    "owner_id": product_id,
                    "owner_resource": "product"
                }
            }
            requests.post(post_url, headers=HEADERS, json=data)
            time.sleep(0.5)
    print(f"Restored {title} to {base_price} MAD.")

print("✅ Base prices restored successfully!")
