import os
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI

from ai_service import (
    init_ai_service,
    analyze_product_with_ai,
    optimize_product_router,
)
from shopify_service import (
    init_shopify_service,
    get_store,
    get_latest_store,
    save_shop_token,
    fetch_shopify_products,
    exchange_shopify_token,
)

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


# ---------------------------------------------------------------------------
# Initialise service modules with shared dependencies
# ---------------------------------------------------------------------------
init_ai_service(client)
init_shopify_service(db, ShopifyStore)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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

    try:
        data = exchange_shopify_token(shop, code, SHOPIFY_API_KEY, SHOPIFY_API_SECRET)
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

    response = fetch_shopify_products(shop, store.access_token)
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
                    const benefits = Array.isArray(item.key_benefits) ? item.key_benefits.map(b => `<li>${b}</li>`).join("") : "";
                    const sellingPts = Array.isArray(item.selling_points) ? item.selling_points.map(s => `<li>${s}</li>`).join("") : "";

                    let fragranceHtml = "";
                    if (item.is_fragrance) {
                        const notes = item.fragrance_notes || {};
                        const topNotes = Array.isArray(notes.top) ? notes.top.join(", ") : "";
                        const heartNotes = Array.isArray(notes.heart) ? notes.heart.join(", ") : "";
                        const baseNotes = Array.isArray(notes.base) ? notes.base.join(", ") : "";
                        const occasions = Array.isArray(item.best_occasions) ? item.best_occasions.join(", ") : "";
                        const emotions = Array.isArray(item.emotional_triggers) ? item.emotional_triggers.join(", ") : "";

                        fragranceHtml = `
                            <div style="margin-top:10px; padding:12px; background:#fdf6ec; border:1px solid #f5d89a; border-radius:10px;">
                                <div style="font-weight:bold; font-size:15px; margin-bottom:8px;">🌸 Fragrance Profile</div>
                                <div><strong>Scent Family:</strong> ${item.scent_family ?? ""}</div>
                                <div><strong>Top Notes:</strong> ${topNotes}</div>
                                <div><strong>Heart Notes:</strong> ${heartNotes}</div>
                                <div><strong>Base Notes:</strong> ${baseNotes}</div>
                                <div><strong>Projection:</strong> ${item.projection ?? ""}</div>
                                <div><strong>Longevity:</strong> ${item.longevity ?? ""}</div>
                                <div><strong>Best Season:</strong> ${item.best_season ?? ""}</div>
                                <div><strong>Best Occasions:</strong> ${occasions}</div>
                                <div><strong>Emotional Triggers:</strong> ${emotions}</div>
                                <div><strong>Scent Evolution:</strong> ${item.scent_evolution ?? ""}</div>
                                <div style="margin-top:8px;"><strong>Luxury Description:</strong><br>${item.luxury_description ?? ""}</div>
                            </div>
                        `;
                    }

                    html += `
                        <div style="border:1px solid #e5e7eb; border-radius:12px; padding:14px; margin-top:14px; background:#fff;">
                            <div><strong>#${index + 1}</strong> ${item.is_fragrance ? '<span style="background:#fbbf24;color:#000;padding:2px 8px;border-radius:6px;font-size:12px;">🌸 Fragrance</span>' : ''}</div>
                            <div><strong>Product ID:</strong> ${item.product_id ?? ""}</div>
                            <div><strong>Old Title:</strong> ${item.old_title ?? ""}</div>
                            <div><strong>New Title:</strong> ${item.new_title ?? ""}</div>
                            <div><strong>Category:</strong> ${item.category ?? ""}</div>
                            <div><strong>Short Summary:</strong> ${item.short_summary ?? ""}</div>
                            <div><strong>Technical Analysis:</strong> ${item.technical_analysis ?? ""}</div>
                            <div><strong>Target Audience:</strong> ${item.target_audience ?? ""}</div>
                            <div><strong>Ingredients / Notes:</strong> ${item.ingredients_or_notes ?? ""}</div>
                            ${benefits ? `<div><strong>Key Benefits:</strong><ul>${benefits}</ul></div>` : ""}
                            ${sellingPts ? `<div><strong>Selling Points:</strong><ul>${sellingPts}</ul></div>` : ""}
                            ${fragranceHtml}
                            <div><strong>Source:</strong> ${item.source_used ?? ""}</div>
                            <div><strong>Status:</strong> ${item.success ? "Success" : "Failed"}</div>
                            <div><strong>Language:</strong> ${item.language_used ?? ""}</div>
                            <div><strong>Description:</strong><br>${item.new_description ?? ""}</div>
                            <div style="margin-top:6px; font-size:12px; color:#555; background:#f3f4f6; padding:6px 10px; border-radius:6px;">
                                <strong>🔍 Diagnostics:</strong>
                                is_fragrance = <strong>${item.is_fragrance ?? false}</strong> &nbsp;|&nbsp;
                                has_ul = <strong>${item.has_ul}</strong> &nbsp;|&nbsp;
                                li_count = <strong>${item.li_count}</strong> &nbsp;|&nbsp;
                                contains_bullet_symbol = <strong>${item.contains_bullet_symbol}</strong>
                            </div>
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


@app.route("/api/optimize-product", methods=["POST"])
def optimize_product():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    vendor = (data.get("vendor") or "").strip()
    product_type = (data.get("product_type") or "").strip()

    if not any([title, description, vendor, product_type]):
        return jsonify({"error": "At least one of title, description, vendor, or product_type is required"}), 400

    product = {
        "title": title,
        "body_html": description,
        "vendor": vendor,
        "product_type": product_type,
        "tags": "",
    }

    result = optimize_product_router(product, lang="en")

    long_desc = result.get("long_description") or result.get("description", "")
    response_data = {
        "category": result.get("category", ""),
        "title": result.get("title"),
        "short_summary": result.get("short_summary", ""),
        "technical_analysis": result.get("technical_analysis", ""),
        "target_audience": result.get("target_audience", ""),
        "key_benefits": result.get("key_benefits", []),
        "selling_points": result.get("selling_points", []),
        "long_description": long_desc,
        "description": long_desc,
        "meta_description": result.get("meta_description"),
        "keywords": result.get("keywords"),
        "source_used": result.get("source_used"),
        "is_fragrance": result.get("is_fragrance", False),
        "has_ul": "<ul>" in long_desc.lower(),
        "li_count": long_desc.lower().count("<li>"),
        "contains_bullet_symbol": "•" in long_desc,
        "scent_family": result.get("scent_family"),
        "fragrance_notes": result.get("fragrance_notes"),
        "scent_evolution": result.get("scent_evolution"),
        "projection": result.get("projection"),
        "longevity": result.get("longevity"),
        "best_season": result.get("best_season"),
        "best_occasions": result.get("best_occasions"),
        "emotional_triggers": result.get("emotional_triggers"),
        "luxury_description": result.get("luxury_description"),
    }

    return jsonify(response_data)


@app.route("/api/analyze-product", methods=["POST"])
def analyze_product():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"error": "Field 'idea' is required"}), 400

    result = analyze_product_with_ai(idea)

    long_desc = result.get("long_description", "")
    return jsonify({
        "category": result.get("category", ""),
        "title": result.get("title", idea),
        "short_summary": result.get("short_summary", ""),
        "technical_analysis": result.get("technical_analysis", ""),
        "target_audience": result.get("target_audience", ""),
        "scent_family": result.get("scent_family", ""),
        "fragrance_notes": result.get("fragrance_notes", {"top": [], "heart": [], "base": []}),
        "scent_evolution": result.get("scent_evolution", ""),
        "projection": result.get("projection", ""),
        "longevity": result.get("longevity", ""),
        "best_season": result.get("best_season", ""),
        "best_occasions": result.get("best_occasions", []),
        "emotional_triggers": result.get("emotional_triggers", []),
        "key_benefits": result.get("key_benefits", []),
        "selling_points": result.get("selling_points", []),
        "luxury_description": result.get("luxury_description", ""),
        "long_description": long_desc,
        "meta_description": result.get("meta_description", ""),
        "keywords": result.get("keywords", ""),
        "has_ul": "<ul>" in long_desc.lower(),
        "li_count": long_desc.lower().count("<li>"),
    })


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

    products_response = fetch_shopify_products(shop, store.access_token)

    try:
        products_data = products_response.json()
    except Exception:
        return jsonify({"error": "Failed to parse Shopify products response"}), 500

    products = products_data.get("products", [])
    results = []

    for product in products[:5]:
        try:
            product_title = product.get("title", "")

            optimized = optimize_product_router(product, lang)

            long_desc = optimized.get("long_description") or optimized.get("description", "")

            result_item = {
                "product_id": product.get("id"),
                "old_title": product_title,
                "new_title": optimized.get("title", ""),
                "category": optimized.get("category", ""),
                "short_summary": optimized.get("short_summary", ""),
                "technical_analysis": optimized.get("technical_analysis", ""),
                "target_audience": optimized.get("target_audience", ""),
                "key_benefits": optimized.get("key_benefits", []),
                "selling_points": optimized.get("selling_points", []),
                "new_description": long_desc,
                "meta_description_preview": optimized.get("meta_description", ""),
                "keywords": optimized.get("keywords", ""),
                "source_used": optimized.get("source_used", "unknown"),
                "success": True,
                "status_code": 200,
                "language_used": lang,
                "error": "",
                "title_variants": [],
                "is_fragrance": optimized.get("is_fragrance", False),
                "has_ul": optimized.get("has_ul"),
                "li_count": optimized.get("li_count"),
                "contains_bullet_symbol": optimized.get("contains_bullet_symbol"),
                "scent_family": optimized.get("scent_family", ""),
                "fragrance_notes": optimized.get("fragrance_notes", {"top": [], "heart": [], "base": []}),
                "scent_evolution": optimized.get("scent_evolution", ""),
                "projection": optimized.get("projection", ""),
                "longevity": optimized.get("longevity", ""),
                "best_season": optimized.get("best_season", ""),
                "best_occasions": optimized.get("best_occasions", []),
                "emotional_triggers": optimized.get("emotional_triggers", []),
                "luxury_description": optimized.get("luxury_description", ""),
            }

            results.append(result_item)
        except Exception as e:
            results.append({
                "product_id": product.get("id"),
                "old_title": product.get("title", ""),
                "new_title": product.get("title", ""),
                "new_description": "",
                "meta_description_preview": "",
                "keywords": "",
                "source_used": "error",
                "success": False,
                "status_code": 500,
                "language_used": lang,
                "error": str(e),
                "title_variants": [],
            })

    return jsonify({
        "message": "Optimization completed",
        "language_used": lang,
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
            
