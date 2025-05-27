import os
import json
import requests
import time
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
SHOP_DOMAIN = os.getenv("SHOP_DOMAIN")
API_TOKEN = os.getenv("API_TOKEN")
API_VERSION = "2024-04"

HEADERS = {
    "X-Shopify-Access-Token": API_TOKEN,
    "Content-Type": "application/json"
}

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# === Variant Price Logic ===
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
        flash("✅ Variant prices updated successfully!")
        return redirect(url_for("index"))
    return render_template("index.html", variant_prices=variant_prices)

@app.route("/update_variants")
def update_variants():
    variant_prices = load_variant_prices()
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
    updated_count = 0

    while url:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            flash(f"API error: {response.status_code} - {response.text}", "error")
            return redirect(url_for("index"))
        data = response.json()
        products = data.get("products", [])

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
                time.sleep(0.5)  # Rate limit

        link = response.headers.get("Link")
        if link and 'rel="next"' in link:
            url = [l.split(";")[0].strip("<>") for l in link.split(",") if 'rel="next"' in l][0]
        else:
            url = None

    flash(f"✅ Updated {updated_count} variants on Shopify.")
    return redirect(url_for("index"))

def get_base_price(product_id):
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    response = requests.get(url, headers=HEADERS)
    time.sleep(0.5)  # Rate limit
    if response.status_code != 200:
        return None
    for field in response.json().get("metafields", []):
        if field["key"] == "base_price":
            return float(field["value"])
    return None

def update_variant_price(variant_id, new_price):
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    data = {"variant": {"id": variant_id, "price": new_price}}
    requests.put(url, headers=HEADERS, json=data)
    time.sleep(0.5)  # Rate limit

# === Product Price Adjustment Logic ===
def nice_round(price):
    price = int(price)
    remainder = price % 100
    if remainder <= 40:
        return price - remainder + 0
    elif remainder <= 90:
        return price - remainder + 90
    else:
        return price - remainder + 100

@app.route("/adjust-prices", methods=["GET", "POST"])
def adjust_prices():
    if request.method == "POST":
        try:
            percentage = float(request.form.get("percentage"))
        except (TypeError, ValueError):
            flash("❌ Invalid percentage value.", "error")
            return redirect(url_for("adjust_prices"))

        url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250"
        updated_count = 0

        while url:
            response = requests.get(url, headers=HEADERS)
            if response.status_code != 200:
                flash(f"API error: {response.status_code} - {response.text}", "error")
                return redirect(url_for("adjust_prices"))

            data = response.json()
            products = data.get("products", [])

            for product in products:
                product_id = product["id"]
                product_title = product["title"]
                original_price = float(product["variants"][0]["price"])
                new_price = original_price * (1 + percentage / 100)
                rounded_price = nice_round(new_price)
                update_base_price(product_id, rounded_price)
                updated_count += 1
                time.sleep(0.5)  # Rate limit

            link = response.headers.get("Link")
            if link and 'rel="next"' in link:
                url = [l.split(";")[0].strip("<>") for l in link.split(",") if 'rel="next"' in l][0]
            else:
                url = None

        flash(f"✅ Updated base_price for {updated_count} products by {percentage}%.")
        return redirect(url_for("adjust_prices"))

    return render_template("adjust_prices.html")

def update_base_price(product_id, base_price):
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}/metafields.json"
    response = requests.get(url, headers=HEADERS)
    time.sleep(0.5)  # Rate limit
    if response.status_code != 200:
        return
    existing_metafield = next((m for m in response.json().get("metafields", []) if m["key"] == "base_price"), None)
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

if __name__ == "__main__":
    app.run(debug=True)
