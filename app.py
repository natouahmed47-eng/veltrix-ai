import os         
import json 
import requests
from datetime import datetime
from urllib.parse import urlencode

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

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from environment variables")

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


def sanitize_plain_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("#", "").replace("*", "").replace("`", "").strip()


def get_store(shop: str):
    return ShopifyStore.query.filter_by(shop=shop).first()


def get_latest_store():
    return ShopifyStore.query.order_by(ShopifyStore.updated_at.desc()).first()


def save_shop_token(shop: str, access_token: str, scope: str | None = None):
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


def build_title_and_description_with_ai(product: dict, lang: str = "ar") -> dict:
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    language_map = {
        "ar": "Arabic",
        "en": "English",
        "fr": "French",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "tr": "Turkish"
    }

    language_name = language_map.get(lang, "English")

    system_prompt = f"""You are an expert e-commerce copywriter and SEO specialist.

Your task is to generate high-converting product content.

Return JSON only in this format:
{{
  "title": "optimized product title",
  "description": "optimized product description",
  "meta_description": "short SEO description",
  "keywords": "comma-separated SEO keywords"
}}

Rules:
- Write in {language_name} only
- Do not use markdown
- Do not use emojis
- Make the title persuasive and clean
- Make the description conversion-focused
- Make the SEO fields relevant
"""

    user_prompt = f"""Current product title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Current description: {body_html}

Please generate:
- a stronger title
- a persuasive description
- an SEO meta description
- SEO keywords

Write everything in {language_name}.
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

    raw_text = response.choices[0].message.content if response.choices else ""

    import json

    try:
        ai_result = json.loads(raw_text)
    except Exception:
        ai_result = {
            "title": title,
            "description": sanitize_plain_text(raw_text).replace("\n", "<br>"),
            "meta_description": "",
            "keywords": ""
        }

    return {
        "title": ai_result.get("title", title),
        "description": ai_result.get("description", "").replace("\n", "<br>"),
        "meta_description": ai_result.get("meta_description", ""),
        "keywords": ai_result.get("keywords", "")
    }

        response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    temperature=0.7,
        )

    raw_text = response.choices[0].message.content if response.choices else ""
        رفع خطأ وقت التشغيل ("استجابة الذكاء الاصطناعي فارغة")    إذا لم يكن raw_text: not raw_text:
        raise RuntimeError("Empty AI response"    تم تنظيف النص الخام باستخدام الأمر `raw_text.strip()`

    cleaned = raw_text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        ai_result = json.loads(cleaned)
    except json.JSONDecodeError:
        ai_result = {
            "title": title,
            "description": sanitize_plain_text(raw_text)
        }

    new_title = (ai_result.get("title") or title).strip()
    new_description = (ai_result.get("description") or "").strip()

    if not new_description:
        new_description = sanitize_plain_text(raw_text)

    return {
        "title": new_title,
        "description": new_description.replace("\n", "<br>")
    }


@app.route("/")
def home():
    return jsonify({"message": "Veltrix AI is running"})


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

    params = {
        "client_id": SHOPIFY_API_KEY,
        "scope": SHOPIFY_SCOPES,
        "redirect_uri": SHOPIFY_REDIRECT_URI,
    }

    install_url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
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

    try:
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
            ai_result = build_title_and_description_with_ai(product)
            new_title = ai_result["title"]
            new_description = ai_result["description"]

            update_response = requests.put(
    f"https://{shop}/admin/api/2024-01/products/{product['id']}.json",
    headers={
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    },
    json={
        "product": {
            "id": product["id"],
            "title": new_title,
            "body_html": new_description,
            "metafields": [
                {
                    "namespace": "seo",
                    "key": "description",
                    "value": ai_result.get("meta_description"),
                    "type": "single_line_text_field"
                },
                {
                    "namespace": "seo",
                    "key": "keywords",
                    "value": ai_result.get("keywords"),
                    "type": "single_line_text_field"
                }
            ]
        }
    },
    timeout=30,
            )
            

            results.append({
                "product_id": product["id"],
                "old_title": product.get("title"),
                "new_title": new_title,
                "success": update_response.status_code == 200,
                "status_code": update_response.status_code,
                "new_description_preview": new_description[:200]
            })

        except Exception as e:
            results.append({
                "product_id": product.get("id"),
                "old_title": product.get("title"),
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
