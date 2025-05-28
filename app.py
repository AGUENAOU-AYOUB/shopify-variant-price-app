# app.py
import os
import json
import time
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)

# ──────────────────────────────────────────────────────────────────────────────
# Initialisation
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

SHOP_DOMAIN: str = os.getenv("SHOP_DOMAIN", "")
API_TOKEN: str = os.getenv("API_TOKEN", "")
API_VERSION: str = "2024-04"
SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "change_me")

app = Flask(__name__)
app.secret_key = SECRET_KEY

HEADERS: Dict[str, str] = {
    "X-Shopify-Access-Token": API_TOKEN,
    "Content-Type": "application/json",
}

VARIANT_PRICE_FILE = "variant_prices.json"
MAX_RETRIES = 5
RETRY_DELAY = 2  # seconds

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _shopify_get(url: str) -> Optional[Dict[str, Any]]:
    """GET with auto-retry on 429/5xx."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(RETRY_DELAY * attempt)
            continue
        flash(f"Shopify error {resp.status_code}: {resp.text}", "error")
        return None
    flash("Shopify rate-limit exceeded.", "error")
    return None


def _shopify_put(url: str, payload: Dict[str, Any]) -> bool:
    """PUT with the same retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.put(url, headers=HEADERS, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            return True
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(RETRY_DELAY * attempt)
            continue
        flash(f"Shopify error {resp.status_code}: {resp.text}", "error")
        return False
    flash("Shopify rate-limit exceeded (PUT).", "error")
    return False


def load_variant_prices() -> Dict[str, Dict[str, float]]:
    if not os.path.exists(VARIANT_PRICE_FILE):
        return {"bracelet": {}, "collier": {}}
    with open(VARIANT_PRICE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_variant_prices(data: Dict[str, Dict[str, float]]) -> None:
    with open(VARIANT_PRICE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_base_price(product_id: int) -> Optional[float]:
    url = (
        f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products/"
        f"{product_id}/metafields.json"
    )
    data = _shopify_get(url)
    if not data:
        return None
    for field in data.get("metafields", []):
        if field.get("key") == "base_price":
            try:
                return float(field["value"])
            except (ValueError, TypeError):
                return None
    return None


def update_variant_price(variant_id: int, new_price: float) -> None:
    url = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    _shopify_put(url, {"variant": {"id": variant_id, "price": new_price}})

# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    variant_prices = load_variant_prices()

    if request.method == "POST":
        for category, variants in variant_prices.items():
            for variant_name in variants:
                key = f"{category}_{variant_name}"
                new_price = request.form.get(key)
                if new_price:
                    try:
                        variant_prices[category][variant_name] = float(new_price)
                    except ValueError:
                        flash(
                            f"Invalid price '{new_price}' "
                            f"for '{variant_name}' in '{category}'.",
                            "error",
                        )
        save_variant_prices(variant_prices)
        flash("Local price table updated ✅", "success")
        return redirect(url_for("index"))

    return render_template("index.html", variant_prices=variant_prices)


@app.route("/update_shopify")
def update_shopify():
    variant_prices = load_variant_prices()
    url = (
        f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/products.json"
        "?limit=250"
    )
    updated = 0

    while url:
        data = _shopify_get(url)
        if not data:
            return redirect(url_for("index"))

        products = [
            p
            for p in data.get("products", [])
            if "chaine_update" in p.get("tags", "").lower()
        ]

        for product in products:
            product_id = product["id"]
            tags = [t.strip().lower() for t in product.get("tags", "").split(",")]
            base_price = get_base_price(product_id)
            if base_price is None:
                continue

            table = (
                variant_prices.get("bracelet", {}) if "bracelet" in tags
                else variant_prices.get("collier", {}) if "collier" in tags
                else {}
            )
            if not table:
                continue

            for variant in product["variants"]:
                surcharge = table.get(variant["title"], 0)
                final_price = round(base_price + surcharge, 2)
                update_variant_price(variant["id"], final_price)
                updated += 1

        link_header = requests.get(url, headers=HEADERS).headers.get("Link")
        if link_header and 'rel="next"' in link_header:
            next_url = [
                p.split(";")[0].strip("<>")
                for p in link_header.split(",")
                if 'rel="next"' in p
            ]
            url = next_url[0] if next_url else None
        else:
            url = None

    flash(f"✅ {updated} variant prices pushed to Shopify.", "success")
    return redirect(url_for("index"))

# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
