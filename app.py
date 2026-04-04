import os
import json
import requests
import traceback
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI
from sqlalchemy import text

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

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
    default_language = db.Column(db.String(10), default="en")
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


def save_shop_token(
    shop: str,
    access_token: str,
    scope: str | None = None,
    default_language: str = "en",
):
    store = get_store(shop)

    if store:
        store.access_token = access_token
        store.scope = scope
        if not store.default_language:
            store.default_language = default_language
        store.updated_at = datetime.utcnow()
    else:
        store = ShopifyStore(
            shop=shop,
            access_token=access_token,
            scope=scope,
            default_language=default_language,
        )
        db.session.add(store)

    db.session.commit()
    return store


def build_title_and_description_with_ai(product: dict, lang: str = "en") -> dict:
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
        "tr": "Turkish",
    }
    language_name = language_map.get(lang, "English")

    system_prompt = f"""You are an expert e-commerce copywriter and SEO specialist.

Your task is to generate high-converting product content for Shopify stores.

Return JSON only in this exact format:
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
- Make the title strong, clear, and persuasive
- Make the description conversion-focused
- Make the meta description concise and SEO-friendly
- Make the keywords relevant to the product
"""

    user_prompt = f"""Current product title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Current description: {body_html}

Please do all of the following:
- identify the likely target customer
- identify the problem this product solves
- create a stronger title
- create a persuasive description focused on benefits
- create a short SEO meta description
- create SEO keywords

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
    if not raw_text:
        raise RuntimeError("Empty AI response")

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
    except Exception:
        ai_result = {
            "title": title,
            "description": sanitize_plain_text(raw_text),
            "meta_description": "",
            "keywords": "",
        }

    new_title = (ai_result.get("title") or title).strip()
    new_description = (ai_result.get("description") or "").strip()
    new_meta_description = (ai_result.get("meta_description") or "").strip()
    new_keywords = (ai_result.get("keywords") or "").strip()

    if not new_description:
        new_description = sanitize_plain_text(raw_text)

    return {
        "title": new_title,
        "description": new_description.replace("\n", "<br>"),
        "meta_description": new_meta_description,
        "keywords": new_keywords,
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
        "saved_shop": latest_store.shop if latest_store else None,
        "shopify_api_key_ready": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_ready": bool(SHOPIFY_API_SECRET),
        "shopify_redirect_ready": bool(SHOPIFY_REDIRECT_URI),
        "shopify_token_ready": latest_store is not None,
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
            "shopify_response": data,
        }), 500

    save_shop_token(shop, access_token, SHOPIFY_SCOPES, default_language="en")

    return jsonify({
        "message": "App installed successfully",
        "shop": shop,
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


@app.route("/set-store-language", methods=["GET", "POST"])
def set_store_language():
    shop = (request.args.get("shop") or "").strip()
    lang = (request.args.get("lang") or "").strip().lower()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    allowed_languages = {"ar", "en", "fr", "es", "de", "it", "pt", "tr"}
    if lang not in allowed_languages:
        return jsonify({
            "error": "Unsupported language",
            "allowed_languages": sorted(list(allowed_languages)),
        }), 400

    store = get_store(shop)
    if not store:
        return jsonify({"error": "Store not found"}), 404

    store.default_language = lang
    db.session.commit()

    return jsonify({
        "message": "Store language updated successfully",
        "shop": shop,
        "default_language": lang,
    })

@app.route("/settings", methods=["GET"])
def settings_page():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"

    store = get_store(shop)
    if not store:
        return jsonify({"error": "Store not found"}), 404

    current_lang = store.default_language or "en"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Veltrix AI Settings</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f6f7fb;
                margin: 0;
                padding: 24px;
                color: #111827;
            }}
            .container {{
                max-width: 700px;
                margin: 0 auto;
                background: white;
                padding: 24px;
                border-radius: 16px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            }}
            h1 {{
                margin-top: 0;
                font-size: 28px;
            }}
            .muted {{
                color: #6b7280;
                margin-bottom: 24px;
            }}
            label {{
                display: block;
                margin-bottom: 8px;
                font-weight: bold;
            }}
            select, button {{
                width: 100%;
                padding: 14px;
                border-radius: 10px;
                border: 1px solid #d1d5db;
                font-size: 16px;
                margin-bottom: 16px;
            }}
            button {{
                background: #111827;
                color: white;
                border: none;
                cursor: pointer;
            }}
            button:hover {{
                background: #1f2937;
            }}
            .secondary {{
                background: #2563eb;
            }}
            .secondary:hover {{
                background: #1d4ed8;
            }}
            .card {{
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 16px;
                margin-top: 20px;
                background: #fafafa;
            }}
            .success {{
                color: green;
                margin-top: 12px;
            }}
            .error {{
                color: red;
                margin-top: 12px;
            }}
            code {{
                background: #f3f4f6;
                padding: 2px 6px;
                border-radius: 6px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Veltrix AI Language Settings</h1>
            <div class="muted">Store: <strong>{shop}</strong></div>

            <div class="card">
                <label for="language">Choose your default content language</label>
                <select id="language">
                    <option value="en" {"selected" if current_lang == "en" else ""}>English</option>
                    <option value="fr" {"selected" if current_lang == "fr" else ""}>French</option>
                    <option value="es" {"selected" if current_lang == "es" else ""}>Spanish</option>
                    <option value="ar" {"selected" if current_lang == "ar" else ""}>Arabic</option>
                    <option value="de" {"selected" if current_lang == "de" else ""}>German</option>
                    <option value="it" {"selected" if current_lang == "it" else ""}>Italian</option>
                    <option value="pt" {"selected" if current_lang == "pt" else ""}>Portuguese</option>
                    <option value="tr" {"selected" if current_lang == "tr" else ""}>Turkish</option>
                </select>

                <button onclick="saveLanguage()">Save Language</button>
                <button class="secondary" onclick="optimizeProducts()">Optimize Products</button>

                <div id="message"></div>
            </div>

            <div class="card">
                <strong>How it works:</strong>
                <p>1. Select the language you want.</p>
                <p>2. Click <code>Save Language</code>.</p>
                <p>3. Click <code>Optimize Products</code>.</p>
            </div>
        </div>

        <script>
            const shop = "{shop}";

            async function saveLanguage() {{
                const lang = document.getElementById("language").value;
                const message = document.getElementById("message");
                message.innerHTML = "Saving...";

                try {{
                    const response = await fetch(`/set-store-language?shop=${{encodeURIComponent(shop)}}&lang=${{encodeURIComponent(lang)}}`);
                    const data = await response.json();

                    if (response.ok) {{
                        message.innerHTML = `<div class="success">Language saved successfully: ${{data.default_language}}</div>`;
                    }} else {{
                        message.innerHTML = `<div class="error">${{data.error || "Failed to save language"}}</div>`;
                    }}
                }} catch (error) {{
                    message.innerHTML = `<div class="error">${{error.message}}</div>`;
                }}
            }}

            function optimizeProducts() {{
                window.location.href = `/optimize-all-products?shop=${{encodeURIComponent(shop)}}`;
            }}
        </script>
    </body>
    </html>
    """

    return Response(html, mimetype="text/html")



@app.route("/optimize-all-products", methods=["GET", "POST"])
def optimize_all_products():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    shop = (request.args.get("shop") or "").strip()
    requested_lang = (request.args.get("lang") or "").strip().lower()

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

    lang = requested_lang or (store.default_language or "en")

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
            ai_result = build_title_and_description_with_ai(product, lang=lang)
            new_title = ai_result["title"]
            new_description = ai_result["description"]
            new_meta_description = ai_result["meta_description"]
            new_keywords = ai_result["keywords"]

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
                "language_used": lang,
                "new_description_preview": new_description[:200],
                "meta_description_preview": new_meta_description[:160],
                "keywords": new_keywords,
            })

        except Exception as e:
            print("ERROR:", str(e))
            print(traceback.format_exc())
            results.append({
                "product_id": product.get("id"),
                "old_title": product.get("title"),
                "success": False,
                "error": str(e),
            })

    return jsonify({
        "shop": shop,
        "language_used": lang,
        "total_processed": len(results),
        "results": results,
    })


@app.route("/run-migration", methods=["GET"])
def run_migration():
    try:
        with db.engine.connect() as connection:
            inspector_query = text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'shopify_stores'
            """)
            result = connection.execute(inspector_query)
            columns = [row[0] for row in result.fetchall()]

            changes = []

            if "default_language" not in columns:
                connection.execute(
                    text("ALTER TABLE shopify_stores ADD COLUMN default_language VARCHAR(10) DEFAULT 'en'")
                )
                connection.commit()
                changes.append("Added default_language column")

        return jsonify({
            "message": "Migration completed successfully",
            "changes": changes
        })
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
