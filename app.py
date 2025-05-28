import os
import json
import requests
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")

SHOP_DOMAIN = os.getenv("SHOP_DOMAIN")
API_TOKEN = os.getenv("API_TOKEN")
API_VERSION = "2024-04"
HEADERS = {
    "X-Shopify-Access-Token": API_TOKEN,
    "Content-Type": "application/json"
}

GRAPHQL_URL = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}/graphql.json"

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
    print("✅ Starting bulk price update...")

    # 1️⃣ Fetch product and variant IDs
    print("Fetching products from Shopify...")
    product_variants = []
    cursor = None

    while True:
        query = """
        {
            products(first: 50%s) {
                edges {
                    node {
                        title
                        tags
                        variants(first: 100) {
                            edges {
                                node {
                                    id
                                    title
                                    product {
                                        metafields(first: 5, namespace: "custom") {
                                            edges {
                                                node {
                                                    key
                                                    value
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    cursor
                }
                pageInfo {
                    hasNextPage
                }
            }
        }
        """ % (f', after: "{cursor}"' if cursor else '')

        response = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": query}, timeout=30)

        if response.status_code != 200:
            print(f"❌ Shopify GraphQL Error: {response.status_code} - {response.text}")
            flash("❌ Shopify API error. Please try again later.", "error")
            return redirect(url_for("index"))

        data = response.json()

        if "errors" in data:
            print(f"❌ Shopify GraphQL Query Error: {data['errors']}")
            flash(f"❌ Shopify GraphQL Error: {data['errors']}", "error")
            return redirect(url_for("index"))

        try:
            edges = data["data"]["products"]["edges"]
        except KeyError:
            print(f"❌ Unexpected response: {data}")
            flash("❌ Error fetching products from Shopify. Please check logs.", "error")
            return redirect(url_for("index"))

        for edge in edges:
            product = edge["node"]
            product_tags = [t.lower() for t in product["tags"]]
            variants = product["variants"]["edges"]

            base_price = None
            for meta in variants[0]["node"]["product"]["metafields"]["edges"]:
                if meta["node"]["key"] == "base_price":
                    base_price = float(meta["node"]["value"])
                    break

            if base_price is None:
                continue

            if "bracelet" in product_tags:
                table = variant_prices.get("bracelet", {})
            elif "collier" in product_tags:
                table = variant_prices.get("collier", {})
            else:
                continue

            for v in variants:
                variant = v["node"]
                surcharge = table.get(variant["title"], 0)
                final_price = base_price + surcharge
                product_variants.append({
                    "variantId": variant["id"],
                    "price": round(final_price, 2)
                })
                print(f"Prepared {variant['id']} for {final_price} MAD")

        if data["data"]["products"]["pageInfo"]["hasNextPage"]:
            cursor = edges[-1]["cursor"]
        else:
            break

    if not product_variants:
        flash("❌ No variants found for update. Check product tags and metafields.", "error")
        return redirect(url_for("index"))

    # 2️⃣ Build the JSONL file
    jsonl_content = ""
    for v in product_variants:
        jsonl_content += json.dumps({
            "id": v["variantId"],
            "price": str(v["price"])
        }) + "\n"

    with open("bulk_update.jsonl", "w") as f:
        f.write(jsonl_content)

    # 3️⃣ Upload the JSONL to Shopify
    mutation = """
    mutation {
        stagedUploadsCreate(input: [{resource: BULK_MUTATION_VARIABLES, filename: "bulk_update.jsonl", mimeType: "text/jsonl"}]) {
            stagedTargets {
                url
                resourceUrl
                parameters {
                    name
                    value
                }
            }
            userErrors {
                field
                message
            }
        }
    }
    """
    response = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": mutation}, timeout=30)
    upload_data = response.json()["data"]["stagedUploadsCreate"]["stagedTargets"][0]

    form_data = {p["name"]: p["value"] for p in upload_data["parameters"]}
    files = {"file": open("bulk_update.jsonl", "rb")}

    upload_response = requests.post(upload_data["url"], data=form_data, files=files, timeout=60)
    if upload_response.status_code != 204:
        flash("❌ Upload to Shopify failed.", "error")
        return redirect(url_for("index"))

    # 4️⃣ Start the bulk operation
    mutation = """
    mutation {
      bulkOperationRunMutation(
        mutation: "mutation call($input: BulkProductVariantInput!) { productVariantUpdate(input: $input) { userErrors { field message } } }"
        stagedUploadPath: "%s"
      ) {
        bulkOperation {
          id
          status
        }
        userErrors {
          field
          message
        }
      }
    }
    """ % upload_data["resourceUrl"]

    response = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": mutation}, timeout=30)
    result = response.json()
    print(result)
    flash("✅ Bulk price update started. Check Shopify Admin > Bulk Operations.", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
