import os
import json  
import requests
import traceback
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, render_template_string
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


def sanitize_plain_text(text_value: str) -> str:
    if not text_value:
        return ""
    return (
        text_value.replace("#", "")
        .replace("*", "")
        .replace("`", "")
        .strip()
    )


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
    description = (product.get("body_html") or "").strip()
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

    prompt = f"""
You are a world-class Shopify SEO expert and conversion copywriter.

IMPORTANT:
You MUST write EVERYTHING in {language_name}.
DO NOT use any other language.
DO NOT mix languages.
If you do, the result is INVALID.

Rewrite this product with HIGH-CONVERSION and SEO optimization.

STRICT FORMAT:
Return ONLY a valid JSON object with:
- title
- description
- meta_description
- keywords

- if "<ul>" not in new_description:
    new_description = f"""
<p>Upgrade your grooming experience with premium precision and comfort.</p>
<ul>
<li>Achieve a smooth, irritation-free shave every time</li>
<li>Designed for maximum comfort and control</li>
<li>Save time with fast, efficient performance</li>
<li>Perfect for daily grooming or professional results</li>
<li>Boost confidence with a clean, sharp look</li>
</ul>
"""

PRODUCT:
Title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Description: {description}
"""

response =     client.chat.completes.create (​​​
        model= "gpt-4o-mini" ,
        الرسائل = [
            { "role" : "system" , "content" : "أنت كاتب محتوى تسويقي محترف متخصص في تحسين محركات البحث لمنصة Shopify." } ,
            { "role" : "user" , "content" : prompt } ,
        ] ,
        درجة الحرارة = 0.7 ،
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

    template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>Veltrix AI Settings</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f6f7fb;
                margin: 0;
                padding: 24px;
                color: #111827;
            }
            .container {
                max-width: 700px;
                margin: 0 auto;
                background: white;
                padding: 24px;
                border-radius: 16px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            }
            h1 {
                margin-top: 0;
                font-size: 28px;
            }
            .muted {
                color: #6b7280;
                margin-bottom: 24px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                font-weight: bold;
            }
            select, button {
                width: 100%;
                padding: 14px;
                border-radius: 10px;
                border: 1px solid #d1d5db;
                font-size: 16px;
                margin-bottom: 16px;
            }
            button {
                background: #111827;
                color: white;
                border: none;
                cursor: pointer;
            }
            button:hover {
                background: #1f2937;
            }
            .secondary {
                background: #2563eb;
            }
            .secondary:hover {
                background: #1d4ed8;
            }
            .card {
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 16px;
                margin-top: 20px;
                background: #fafafa;
            }
            .success {
                color: green;
                margin-top: 12px;
            }
            .error {
                color: red;
                margin-top: 12px;
            }
            code {
                background: #f3f4f6;
                padding: 2px 6px;
                border-radius: 6px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Veltrix AI Language Settings</h1>
            <div class="muted">Store: <strong>{{ shop }}</strong></div>

            <div class="card">
                <label for="language">Choose your default content language</label>
                <select id="language">
                    <option value="en" {% if current_lang == "en" %}selected{% endif %}>English</option>
                    <option value="fr" {% if current_lang == "fr" %}selected{% endif %}>French</option>
                    <option value="es" {% if current_lang == "es" %}selected{% endif %}>Spanish</option>
                    <option value="ar" {% if current_lang == "ar" %}selected{% endif %}>Arabic</option>
                    <option value="de" {% if current_lang == "de" %}selected{% endif %}>German</option>
                    <option value="it" {% if current_lang == "it" %}selected{% endif %}>Italian</option>
                    <option value="pt" {% if current_lang == "pt" %}selected{% endif %}>Portuguese</option>
                    <option value="tr" {% if current_lang == "tr" %}selected{% endif %}>Turkish</option>
                </select>

                <button onclick="saveLanguage()">Save Language</button>
                <button class="secondary" onclick="optimizeProducts()">Optimize Products</button>

                <div id="message"></div>
                <div id="results" style="margin-top:20px;"></div>
            </div>

            <div class="card">
                <strong>How it works:</strong>
                <p>1. Select the language you want.</p>
                <p>2. Click <code>Save Language</code>.</p>
                <p>3. Click <code>Optimize Products</code>.</p>
            </div>
        </div>

        <script>
            const shop = {{ shop|tojson }};

            async function saveLanguage() {
                const lang = document.getElementById("language").value;
                const message = document.getElementById("message");
                message.innerHTML = "Saving...";

                try {
                    const response = await fetch(`/set-store-language?shop=${encodeURIComponent(shop)}&lang=${encodeURIComponent(lang)}`);
                    const data = await response.json();

                    if (response.ok) {
                        message.innerHTML = `<div class="success">Language saved successfully: ${data.default_language}</div>`;
                    } else {
                        message.innerHTML = `<div class="error">${data.error || "Failed to save language"}</div>`;
                    }
                } catch (error) {
                    message.innerHTML = `<div class="error">${error.message}</div>`;
                }
            }

            async function optimizeProducts() {
                const message = document.getElementById("message");
                const resultsBox = document.getElementById("results");
                const lang = document.getElementById("language").value;

                message.innerHTML = "Optimizing products...";
                resultsBox.innerHTML = "";

                try {
                    const response = await fetch(`/optimize-all-products?shop=${encodeURIComponent(shop)}&lang=${encodeURIComponent(lang)}`);
                    const data = await response.json();

                    if (!response.ok) {
                        message.innerHTML = `<div class="error">${data.error || "Optimization failed"}</div>`;
                        return;
                    }

                    message.innerHTML = `<div class="success">Optimization completed successfully. Language used: ${data.language_used}</div>`;

                    if (!data.results || !data.results.length) {
                        resultsBox.innerHTML = `<div class="card"><p>No products were processed.</p></div>`;
                        return;
                    }

                    let html = `<div class="card"><h3>Optimization Results</h3>`;

                    data.results.forEach((item, index) => {
                        html += `
                            <div style="border:1px solid #e5e7eb; border-radius:12px; padding:14px; margin-top:14px; background:#fff;">
                                <div><strong>#${index + 1}</strong></div>
                                <div><strong>Product ID:</strong> ${item.product_id ?? ""}</div>
                                <div><strong>Old Title:</strong> ${item.old_title ?? ""}</div>
                                <div><strong>New Title:</strong> ${item.new_title ?? ""}</div>
                                <div><strong>Status:</strong> ${item.success ? "Success" : "Failed"}</div>
                                <div><strong>Status Code:</strong> ${item.status_code ?? ""}</div>
                                <div><strong>Language:</strong> ${item.language_used ?? ""}</div>
                                <div><strong>Description Preview:</strong><br>${item.new_description_preview ?? ""}</div>
                                <div><strong>Meta Description:</strong><br>${item.meta_description_preview ?? ""}</div>
                                <div><strong>Keywords:</strong><br>${item.keywords ?? ""}</div>
                                ${item.error ? `<div style="color:red;"><strong>Error:</strong> ${item.error}</div>` : ""}
                            </div>
                        `;
                    });

                    html += `</div>`;
                    resultsBox.innerHTML = html;

                } catch (error) {
                    message.innerHTML = `<div class="error">${error.message}</div>`;
                }
            }
        </script>
    </body>
    </html>
    """

    return render_template_string(template, shop=shop, current_lang=current_lang)


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
