import os
from datetime import datetime

import requests
from flask import Flask, jsonify, redirect, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
SHOPIFY_REDIRECT_URI = os.environ.get("SHOPIFY_REDIRECT_URI")
SHOPIFY_SCOPES = os.environ.get("SHOPIFY_SCOPES", "read_products,write_products")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class ShopifyStore(db.Model):
    __tablename__ = "shopify_stores"

    id = db.Column(db.Integer, primary_key=True)
    shop = db.Column(db.String(255), unique=True, nullable=False, index=True)
    access_token = db.Column(db.Text, nullable=False)
    scope = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
def get_store(shop):return ShopifyStore.query.filter_by(shop=shop).first()
 ai_result = build_title_and_description_with_ai(product)
new_title = ai_result["title"]
new_description = ai_result["description"]
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    system_prompt = """You are a professional e-commerce copywriter.

Write a high-converting product description in strong, clear, direct English.

Rules:
- Write in English only
- No fluff
- No poetic language
- No markdown symbols
- Focus on benefits, usability, and conversion
- Make it suitable for Shopify product pages

Output:
- 1 short headline
- 1 persuasive paragraph
- 3 concise benefit points
- 1 strong closing sentence

Return plain text only.
"""

    user_prompt = f"""Product title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Current description: {body_html}

Write a better product description for this item in English only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    raw_text = response.choices[0].message.content if response.choices else ""
    if not raw_text:
        raise RuntimeError("Empty AI response")

    clean_text = raw_text.replace("#", "").replace("*", "").replace("`", "").strip()
    return clean_text.replace("\n", "<br>")

def get_latest_store():
    return ShopifyStore.query.order_by(ShopifyStore.updated_at.desc()).first()


def save_shop_token(shop, access_token, scope=None):
    store = get_store(shop)

    if store:
        store.access_token = access_token
        store.scope = scope
        store.updated_at = datetime.utcnow()
    else:
        store = ShopifyStore(
            shop=shop,
            access_token=access_token,
            scope=scope,
        )
        db.session.add(store)

    db.session.commit()
    return store


def sanitize_plain_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("#", "").replace("*", "").replace("`", "").strip()


def build_description_with_ai(product: dict) -> str:
    if not client:
        raise RuntimeError("OpenAI is not configured")
def build_title_and_description_with_ai(product: dict) -> dict:
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    system_prompt = """You are a professional e-commerce copywriter.

Your task:
Rewrite the product title and product description for higher conversion.

Rules:
- Write in Arabic only
- Make the title stronger, clearer, and more marketable
- Keep the title realistic, not spammy
- Make the description persuasive and clean
- No markdown symbols
- No hashtags
- No emojis
- Return valid JSON only

Required JSON format:
{
  "title": "new product title here",
  "description": "new product description here"
}
"""

    user_prompt = f"""Current title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Current description: {body_html}

Rewrite both the title and the description in Arabic.
Return JSON only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    content = response.choices[0].message.content if response.choices else ""
    if not content:
        raise RuntimeError("Empty AI response")

    import json

    data = json.loads(content)

    new_title = (data.get("title") or "").strip()
    new_description = (data.get("description") or "").strip()

    if not new_title or not new_description:
        raise RuntimeError("AI response missing title or description")

    return {
        "title": new_title,
        "description": new_description.replace("\n", "<br>")
    }
    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    system_prompt = """You are a professional e-commerce copywriter.

Write a high-converting product description in strong, direct, realistic English.

Rules:
- No fluff
- No poetic language
- No weak words like maybe, might, possibly
- No markdown symbols
- Focus on real product benefits
- Keep it persuasive and practical

Structure:
- Strong headline
- Short convincing paragraph
- Clear practical benefits
- Strong closing line

Output must be plain clean text only.
"""

    user_prompt = f"""Product name: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Existing description: {body_html}

Write a better final product description in English only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    raw_text = response.choices[0].message.content if response.choices else ""
    clean_text = sanitize_plain_text(raw_text or "")
    return clean_text.replace("\n", "<br>")


@app.route("/")
def home():
    return """
    <h1>VELTRIX AI</h1>
    <p>System is running successfully.</p>
    <ul>
      <li>/health</li>
      <li>/install?shop=your-store.myshopify.com</li>
      <li>/callback</li>
      <li>/products</li>
      <li>/ai/product-description</li>
      <li>/optimize-all-products</li>
    </ul>
    """


@app.route("/health")
def health():
    latest_store = get_latest_store()

    return jsonify({
        "status": "ok",
        "openai_ready": bool(OPENAI_API_KEY),
        "shopify_api_key_ready": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_ready": bool(SHOPIFY_API_SECRET),
        "shopify_redirect_ready": bool(SHOPIFY_REDIRECT_URI),
        "shopify_token_ready": latest_store is not None,
        "saved_shop": latest_store.shop if latest_store else None,
    })


@app.route("/install")
def install():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    if not SHOPIFY_API_KEY or not SHOPIFY_REDIRECT_URI:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_REDIRECT_URI"}), 500

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={SHOPIFY_SCOPES}"
        f"&redirect_uri={SHOPIFY_REDIRECT_URI}"
    )

    return redirect(install_url)


@app.route("/callback")
def callback():
    shop = (request.args.get("shop") or "").strip()
    code = (request.args.get("code") or "").strip()

    if not shop or not code:
        return jsonify({"error": "Missing shop or code"}), 400

    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_API_SECRET"}), 500

    token_url = f"https://{shop}/admin/oauth/access_token"

    response = requests.post(
        token_url,
        json={
            "client_id": SHOPIFY_API_KEY,
            "client_secret": SHOPIFY_API_SECRET,
            "code": code,
        },
        timeout=30,
    )

    data = response.json()
    access_token = data.get("access_token")

    if not access_token:
        return jsonify({
            "error": "No access token returned",
            "shopify_response": data
        }), 500

    save_shop_token(shop, access_token, SHOPIFY_SCOPES)

    return jsonify({
        "message": "App installed successfully",
        "shop": shop
    })


@app.route("/products")
def get_products():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        latest_store = get_latest_store()
        if not latest_store:
            return jsonify({"error": "No saved Shopify token"}), 500
        shop = latest_store.shop

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "No saved Shopify token"}), 500

    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    return jsonify(response.json()), response.status_code


@app.route("/ai/product-description", methods=["POST"])
def generate_description():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.get_json(silent=True) or {}

    product_name = (data.get("product_name") or "").strip()
    brand = (data.get("brand") or "").strip()
    category = (data.get("category") or "").strip()
    audience = (data.get("audience") or "").strip()
    tone = (data.get("tone") or "professional").strip()
    features = (data.get("features") or "").strip()

    if not product_name:
        return jsonify({"error": "Missing product_name"}), 400

    system_prompt = """You are a professional e-commerce copywriter.

Write a high-converting product description in clear, strong, direct English.

Rules:
- No fluff
- No poetic language
- No weak words like maybe, might, possibly
- Focus on real benefits
- Be persuasive and realistic
- No markdown symbols like # or *

Structure:
- Strong product headline
- Short convincing paragraph
- Clear practical benefits
- Strong closing call to action

Output must be plain clean text only.
"""

    user_prompt = f"""Product name: {product_name}
Brand: {brand}
Category: {category}
Target audience: {audience}
Tone: {tone}
Key features: {features}

Write the final result in English only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
    )

    raw_text = response.choices[0].message.content if response.choices else ""
    clean_text = sanitize_plain_text(raw_text or "")

    return jsonify({
        "success": True,
        "description": clean_text
    })


@app.route("/optimize-all-products", methods=["GET", "POST"])
def optimize_all_products():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    shop = (request.args.get("shop") or "").strip()

    if not shop:
        latest_store = get_latest_store()
        if not latest_store:
            return jsonify({"error": "No saved Shopify token"}), 500
        shop = latest_store.shop

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "No saved Shopify token"}), 500

    products_response = requests.get(
        f"https://{shop}/admin/api/2024-01/products.json",
        headers={
            "X-Shopify-Access-Token": store.access_token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    products_data = products_response.json()
    products = products_data.get("products", [])

    results = []

    for product in products[:5]:
        try:
            new_description = build_description_with_ai(product)

            update_response = requests.put(
                f"https://{shop}/admin/api/2024-01/products/{product['id']}.json",
                headers={
                    "X-Shopify-Access-Token": store.access_token,
                    "Content-Type": "application/json",
                },
                json={
                    "product": {
                        "id": product["id"],
                        "body_html": new_description,
                    }
                },
                timeout=30,
            )

            results.append({
                "product_id": product["id"],
                "title": product.get("title"),
                "success": update_response.status_code == 200,
                "status_code": update_response.status_code,
                "new_description_preview": new_description[:200]
            })

        except Exception as e:
            results.append({
                "product_id": product.get("id"),
                "title": product.get("title"),
                "success": False,
                "error": str(e),
            })

    return jsonify({
        "shop": shop,
        "total_processed": len(results),
        "results": results,
    })

    shop = (request.args.get("shop") or "").strip()

    if not shop:
        latest_store = get_latest_store()
        if not latest_store:
            return jsonify({"error": "No saved Shopify token"}), 500
        shop = latest_store.shop

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "No saved Shopify token"}), 500

    products_response = requests.get(
        f"https://{shop}/admin/api/2024-01/products.json",
        headers={
            "X-Shopify-Access-Token": store.access_token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    products_data = products_response.json()
    products = products_data.get("products", [])

    results = []

    for product in products[:5]:
        try:
            new_description = build_description_with_ai(product)

            update_response = requests.put(
                f"https://{shop}/admin/api/2024-01/products/{product['id']}.json",
                headers={
                    "X-Shopify-Access-Token": store.access_token,
                    "Content-Type": "application/json",
                },
                json={
                    "product": {
                        "id": product["id"],
                        "body_html": new_description,
                    }
                },
                timeout=30,
            )

            results.append({
                "product_id": product["id"],
                "title": product.get("title"),
                "success": update_response.status_code == 200,
                "status_code": update_response.status_code,
            })

        except Exception as e:
            results.append({
                "product_id": product.get("id"),
                "title": product.get("title"),
                "success": False,
                "error": str(e),
            })

    return jsonify({
        "shop": shop,
        "total_processed": len(results),
        "results": results,
    })


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
