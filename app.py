import json
import requests
import time
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
import os

load_dotenv()

SHOP_DOMAIN = os.getenv("SHOP_DOMAIN")
API_TOKEN = os.getenv("API_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
API_VERSION = "2024-04"
HEADERS = {
    "X-Shopify-Access-Token": API_TOKEN,
    "Content-Type": "application/json"
}

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Load variant prices from JSON
def load_variant_prices():
    with open("variant_prices.json", "r") as file:
        return json.load(file)

def save_variant_prices(data):
    with open("variant_prices.json", "w") as file:
        json.dump(data, file, indent=4)

@app.route("/", methods=["GET", "POST"])
def index():
    variant_prices = load_variant_prices()
    if request.method == "POST":
        for category in variant_prices:
            for variant_name in variant_prices[category]:
                new_price = request.form.get(f"{category}_{variant_name}")
                if new_price is not None:
                    try:
                        variant_prices[category][variant_name] = float(new_price)
                    except ValueError:
                        flash(f"Invalid price for {variant_name} in {category}")
        save_variant_prices(variant_prices)
        flash("Prices updated successfully!")
        return redirect(url_for("index"))
    return render_template("index.html", variant_prices=variant_prices)

@app.route("/update_shopify")
def update_shopify():
    variant_prices = load_variant_prices()
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
    updated_count = 0

    while url:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            flash(f"API error: {response.status_code} - {response.text}", "error")
            return redirect(url_for("index"))

        data = response.json()
        products = [p for p in data.get("products", []) if "chaine_update" in p.get("tags", "").lower()]

        for product in products:
            product_id = product["id"]
            tags = [t.strip().lower() for t in product.get("tags", "").split(",")]
            base_price = get_base_price(product_id)

            if base_price is None:
                continue

            if "bracelet" in tags:
                table = variant_prices.get("bracelet", {})
            elif "collier" in tags:
                table = variant_prices.get("collier", {})
            else:
                continue

            for variant in product["variants"]:
                surcharge = table.get(variant["title"], 0)
                final_price = base_price + surcharge
                update_variant_price(variant["id"], final_price)
                updated_count += 1

        link_header = response.headers.get("Link")
        if link_header and 'rel="next"' in link_header:
            next_url = [part.split(";")[0].strip("<>") for part in link_header.split(",") if 'rel="next"' in part]
            url = next_url[0] if next_url else None
        else:
            url = None

    flash(f"✅ Updated {updated_count} variants on Shopify.")
    return redirect(url_for("index"))

def get_base_price(product_id):
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    response = requests.get(url, headers=HEADERS, timeout=10)
    if response.status_code != 200:
        return None
    for field in response.json().get("metafields", []):
        if field["key"] == "base_price":
            return float(field["value"])
    return None

def update_variant_price(variant_id, new_price):
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    data = {"variant": {"id": variant_id, "price": new_price}}
    response = requests.put(url, headers=HEADERS, json=data, timeout=10)

    if response.status_code != 200:
        print(f"Error updating variant {variant_id}: {response.status_code} - {response.text}")

    time.sleep(0.6)  # Prevent Shopify 429 API rate limit errors

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
