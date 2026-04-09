import os
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI

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

MAX_AI_GENERATION_RETRIES = 3


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
        str(text_value)
        .replace("#", "")
        .replace("*", "")
        .replace("`", "")
        .strip()
    )


def is_valid_html_description(html: str) -> bool:
    if not html or not isinstance(html, str):
        return False

    text = html.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    li_count = text.count("<li>")
    if li_count < 5 or li_count > 7:
        return False

    if "<p>" not in text or "</p>" not in text:
        return False

    return True


def build_fallback_description(product_title: str = "", brand: str = "", angle: str = "general") -> str:
    name = (product_title or "this product").strip()
    brand_text = f" from {brand.strip()}" if brand and brand.strip() else ""

    fallback_map = {
        "grooming": (
            f"<p>Upgrade your grooming routine with {name}{brand_text} and enjoy a cleaner, more confident result.</p>"
            "<p>Designed for comfort and convenience, this product helps make your routine feel easier and more effective.</p>"
            "<ul>"
            "<li>Enjoy a smoother grooming experience with practical everyday performance.</li>"
            "<li>Save time with a solution built for convenience and reliability.</li>"
            "<li>Feel more confident with cleaner, more polished results.</li>"
            "<li>Use a product designed to make your routine feel easier.</li>"
            "<li>Choose a dependable option that supports daily grooming needs.</li>"
            "</ul>"
            "<p>Make the switch today and enjoy the difference a better grooming essential can make.</p>"
        ),
        "beauty": (
            f"<p>Elevate your beauty routine with {name}{brand_text} and enjoy a more polished, confident look.</p>"
            "<p>This solution is designed to help your daily self-care feel smoother, easier, and more rewarding.</p>"
            "<ul>"
            "<li>Support a more radiant and put-together everyday appearance.</li>"
            "<li>Enjoy a routine that feels easier, smoother, and more effective.</li>"
            "<li>Save time while upgrading your self-care experience.</li>"
            "<li>Add comfort and convenience to your daily beauty routine.</li>"
            "<li>Choose a beauty essential that helps you feel more confident.</li>"
            "</ul>"
            "<p>Refresh your routine today with a beauty upgrade you will actually enjoy using.</p>"
        ),
        "home": (
            f"<p>Make everyday living easier with {name}{brand_text} and enjoy a more practical home routine.</p>"
            "<p>Built to simplify daily tasks, this product helps reduce hassle and improve comfort at home.</p>"
            "<ul>"
            "<li>Bring more ease and convenience into your daily routine.</li>"
            "<li>Save time with a solution built around real household needs.</li>"
            "<li>Enjoy a more organized and stress-free experience.</li>"
            "<li>Improve comfort and usability in the moments that matter most.</li>"
            "<li>Choose a dependable addition that supports everyday living.</li>"
            "</ul>"
            "<p>Simplify your routine with a home essential built for real life.</p>"
        ),
        "tech": (
            f"<p>Upgrade your setup with {name}{brand_text} and enjoy a smarter everyday experience.</p>"
            "<p>This product is designed to bring convenience, performance, and modern functionality into your routine.</p>"
            "<ul>"
            "<li>Enjoy a smoother and more efficient daily experience.</li>"
            "<li>Save time with practical functionality that fits your routine.</li>"
            "<li>Get dependable performance where it matters most.</li>"
            "<li>Add convenience and flexibility to your everyday setup.</li>"
            "<li>Choose a modern essential built to keep up with your lifestyle.</li>"
            "</ul>"
            "<p>Make the smarter choice for a more seamless everyday routine.</p>"
        ),
        "fashion": (
            f"<p>Refine your look with {name}{brand_text} and add more confidence to your style.</p>"
            "<p>Designed to feel versatile and polished, this piece helps elevate your everyday wardrobe.</p>"
            "<ul>"
            "<li>Enhance your personal style with a more elevated finish.</li>"
            "<li>Enjoy a versatile piece that works across different occasions.</li>"
            "<li>Feel more confident with a polished and put-together look.</li>"
            "<li>Bring comfort and style together in one smart choice.</li>"
            "<li>Choose an item that adds value to your everyday wardrobe.</li>"
            "</ul>"
            "<p>Step into a sharper, more confident version of your style today.</p>"
        ),
        "fitness": (
            f"<p>Support your performance with {name}{brand_text} and make your fitness routine feel more effective.</p>"
            "<p>Built for comfort and consistency, this solution helps support your training goals with less friction.</p>"
            "<ul>"
            "<li>Make your routine feel more effective and easier to maintain.</li>"
            "<li>Stay more comfortable and focused during training.</li>"
            "<li>Support better performance with a smarter fitness choice.</li>"
            "<li>Reduce friction in your routine and improve consistency.</li>"
            "<li>Choose a solution built around real performance needs.</li>"
            "</ul>"
            "<p>Upgrade your training experience with a smarter fitness essential.</p>"
        ),
        "pet": (
            f"<p>Make pet care easier with {name}{brand_text} and enjoy a calmer daily routine.</p>"
            "<p>Designed for comfort and convenience, this product helps simplify the care you provide every day.</p>"
            "<ul>"
            "<li>Enjoy a smoother and less stressful care routine.</li>"
            "<li>Save time while improving your pet care experience.</li>"
            "<li>Support better comfort for both you and your pet.</li>"
            "<li>Make daily care feel easier, cleaner, and more efficient.</li>"
            "<li>Choose a dependable pet essential built for real use.</li>"
            "</ul>"
            "<p>Simplify your routine with a pet care upgrade that makes daily life easier.</p>"
        ),
        "general": (
            f"<p>Upgrade your routine with {name}{brand_text} and enjoy a smarter, more effective experience.</p>"
            "<p>This product is designed to deliver comfort, convenience, and practical value from the start.</p>"
            "<ul>"
            "<li>Enjoy a smoother and more reliable experience every time.</li>"
            "<li>Save time with practical performance built for daily use.</li>"
            "<li>Feel more confident with cleaner and more polished results.</li>"
            "<li>Experience comfort and control designed around real needs.</li>"
            "<li>Choose a product that combines function, convenience, and value.</li>"
            "</ul>"
            "<p>Make the switch today and experience the difference for yourself.</p>"
        ),
    }

    return fallback_map.get(angle, fallback_map["general"])


def detect_product_angle(title: str, product_type: str, tags: str, description: str) -> str:
    text_blob = " ".join([
        (title or "").lower(),
        (product_type or "").lower(),
        (tags or "").lower(),
        (description or "").lower(),
    ])

    angle_map = {
        "grooming": [
            "shaver", "shave", "razor", "clipper", "beard", "groom",
            "hair trimmer", "grooming", "barber"
        ],
        "beauty": [
            "beauty", "skincare", "skin", "face", "cosmetic", "serum",
            "makeup", "cleanser", "cream", "beauty tool"
        ],
        "home": [
            "home", "kitchen", "household", "organizer", "cleaning",
            "storage", "cook", "appliance", "room"
        ],
        "tech": [
            "tech", "electronic", "device", "smart", "charger", "wireless",
            "usb", "gadget", "bluetooth"
        ],
        "fashion": [
            "fashion", "wear", "shirt", "dress", "watch", "bag", "shoe",
            "jewelry", "accessory"
        ],
        "fitness": [
            "fitness", "gym", "workout", "exercise", "training", "sport",
            "sports", "recovery", "muscle"
        ],
        "pet": [
            "pet", "dog", "cat", "animal", "pet care", "pet grooming"
        ],
    }

    for angle, keywords in angle_map.items():
        if any(keyword in text_blob for keyword in keywords):
            return angle

    return "general"


def _is_valid_ai_description(description: str) -> bool:
    import re

    if not description or not isinstance(description, str):
        return False

    text = description.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    if "<p>" not in text or "</p>" not in text:
        return False

    if "•" in description or re.search(r"(^|\n)\s*[-*]\s+", description):
        return False

    li_tags = re.findall(r"<li\b[^>]*>.*?</li>", description, re.DOTALL | re.IGNORECASE)
    if len(li_tags) < 5 or len(li_tags) > 7:
        return False

    return True


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
You are an expert Shopify SEO copywriter.

Your job is to generate SEO-OPTIMIZED, HIGH-CONVERTING product copy.

OUTPUT FORMAT (STRICT JSON ONLY)
Return ONLY valid JSON:
{{
  "title": "...",
  "description": "...",
  "meta_description": "...",
  "keywords": "..."
}}

LANGUAGE RULE
- Write ONLY in {language_name}

PRIMARY SEO KEYWORD
- {product_type}
- If the product is a shaver, use terms like: precision shaver, electric shaver, men's shaver, sensitive skin shaver when natural

TITLE REQUIREMENTS
- Must be SEO-friendly
- Must contain a real search keyword
- Must NOT use vague words like "premium product", "ultimate solution", "our product"
- Must be clear, specific, and clickable
- Keep it natural and benefit-driven
- Max 60 characters if possible

DESCRIPTION REQUIREMENTS
- Return VALID HTML ONLY
- First sentence MUST contain the main SEO keyword
- Write for both SEO and conversion
- Include practical benefits, not fluff
- Use natural search phrases shoppers may type into Google
- Avoid generic marketing language
- Include a short intro paragraph + bullet points + short closing paragraph
- Keep it around 120-180 words

META DESCRIPTION REQUIREMENTS
- 140 to 155 characters
- Must contain the main keyword
- Make it click-worthy and natural

KEYWORDS REQUIREMENTS
- Comma-separated
- Include primary + secondary + long-tail keywords
- No generic filler keywords

PRODUCT DATA
- Original title: {title}
- Brand: {vendor}
- Product type: {product_type}
- Existing description: {description}

IMPORTANT
- Do NOT use generic phrases like:
  "premium shaver"
  "ultimate grooming solution"
  "redefines your grooming routine"
  "our product"
- Use specific search-intent keywords instead.
"""












OUTPUT FORMAT (STRICT JSON ONLY)
Return ONLY valid JSON:

{
  "title": "...",
  "description": "...",
  "meta_description": "...",
  "keywords": "..."
}

TITLE REQUIREMENTS:
- Must include a real search keyword
- Avoid generic words like "premium", "ultimate"
- Keep it clear and clickable

DESCRIPTION REQUIREMENTS:
- First sentence MUST include main keyword
- Write 120-180 words
- Include benefits in bullet points
- Focus on real search intent
- Avoid generic marketing phrases

META DESCRIPTION:
- 140-155 characters
- Include main keyword

KEYWORDS:
- Comma-separated
- Include real SEO keywords (not generic)

PRODUCT DATA:
Title: {title}
Brand: {vendor}
Category: {product_type}
Description: {description}



  
  
  
  


TITLE REQUIREMENTS
- Must be DIFFERENT from the original title
- Must be more compelling and benefit-driven
- Use power words and emotional triggers
- Keep it clear and readable
- Do NOT repeat the original title wording
- Write ONLY in {language_name}

DESCRIPTION REQUIREMENTS (CRITICAL)
You MUST return VALID HTML ONLY.
- First sentence MUST include primary keyword
- Include bullet points with benefits
- Use SEO-friendly structure
- Avoid generic phrases
Structure EXACTLY like this:

<p>Hook paragraph that grabs attention and highlights the main benefit.</p>
<p>Second paragraph addressing pain points and positioning the product as the solution.</p>
<ul>
<li><strong>Benefit 1:</strong> Clear outcome-focused benefit.</li>
<li><strong>Benefit 2:</strong> Clear outcome-focused benefit.</li>
<li><strong>Benefit 3:</strong> Clear outcome-focused benefit.</li>
<li><strong>Benefit 4:</strong> Clear outcome-focused benefit.</li>
<li><strong>Benefit 5:</strong> Clear outcome-focused benefit.</li>
</ul>
<p>Close with urgency and action.</p>

STRICT RULES:
- ONLY use <p>, <ul>, <li>, <strong>
- DO NOT use "•" or "-" or "*" or any plain text bullets
- Each bullet MUST be inside <li>
- MUST include between 5 to 7 <li> items
- No broken HTML
- No short or incomplete bullets
- Each bullet must be a full persuasive sentence
- DO NOT escape HTML
- DO NOT return plain text
- DO NOT wrap output in markdown
- If you output bullet points using "•" or "-" instead of <li>, your answer is INVALID
- You MUST use <ul> and <li> or the response will be rejected

SEO:
- Meta description under 155 chars
- Keywords = buyer intent keywords

PRODUCT DATA
Title: {title}
Brand: {vendor}
Category: {product_type}
Tags: {tags}
Description: {description}
"""

    fallback_description = build_fallback_description(
        product_title=title,
        brand=vendor,
        angle=detect_product_angle(title, product_type, tags, description),
    )

    new_title = title or "Optimized Product"
    new_description = ""
    new_meta_description = ""
    new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
    source_used = "initial_fallback"

    for _ in range(MAX_AI_GENERATION_RETRIES):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an elite Shopify conversion copywriter. Return clean JSON only.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.55,
        )

        raw_text = response.choices[0].message.content if response.choices else ""
        if not raw_text:
            continue

        cleaned = raw_text.strip().replace("\u200b", "").replace("\ufeff", "")

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
            continue

        candidate_title = str(ai_result.get("title") or title).strip() or title
        candidate_description = str(ai_result.get("description") or "").strip()
        candidate_meta = str(ai_result.get("meta_description") or "").strip()
        candidate_keywords = str(ai_result.get("keywords") or "").strip()

        if not _is_valid_ai_description(candidate_description):
            continue

        new_title = candidate_title
        new_description = candidate_description
        new_meta_description = candidate_meta
        new_keywords = candidate_keywords or new_keywords
        source_used = "ai"
        break

    if not new_description or not _is_valid_ai_description(new_description):
        new_description = fallback_description
        new_title = title or "Optimized Product"
        new_meta_description = sanitize_plain_text(new_description)
        new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
        source_used = "generated_fallback"

    if not new_meta_description:
        fallback_meta = sanitize_plain_text(new_description or fallback_description or new_title)
        if len(fallback_meta) > 155:
            fallback_meta = fallback_meta[:152].rstrip() + "..."
        new_meta_description = fallback_meta

    if len(new_meta_description) > 155:
        new_meta_description = new_meta_description[:152].rstrip() + "..."

    if not new_keywords:
        fallback_keywords_parts = [title, vendor, product_type]
        fallback_keywords_parts = [k.strip() for k in fallback_keywords_parts if k and k.strip()]
        new_keywords = ", ".join(fallback_keywords_parts[:6])

    return {
        "title": new_title,
        "description": new_description,
        "meta_description": new_meta_description,
        "keywords": new_keywords,
        "source_used": source_used,
        "has_ul": "<ul>" in new_description.lower(),
        "li_count": new_description.lower().count("<li>"),
        "contains_bullet_symbol": "•" in new_description,
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
                            <div><strong>Source:</strong> ${item.source_used ?? ""}</div>
                            <div><strong>Status:</strong> ${item.success ? "Success" : "Failed"}</div>
                            <div><strong>Language:</strong> ${item.language_used ?? ""}</div>
                            <div><strong>Description:</strong><br>${item.new_description ?? ""}</div>
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

    try:
        products_data = products_response.json()
    except Exception:
        return jsonify({"error": "Failed to parse Shopify products response"}), 500

    products = products_data.get("products", [])
    results = []

    for product in products[:5]:
        try:
            optimized = build_title_and_description_with_ai(product, lang=lang)

            results.append({
                "product_id": product.get("id"),
                "old_title": product.get("title", ""),
                "new_title": optimized.get("title", ""),
                "new_description": optimized.get("description", ""),
                "meta_description_preview": optimized.get("meta_description", ""),
                "keywords": optimized.get("keywords", ""),
                "source_used": optimized.get("source_used", "unknown"),
                "success": True,
                "status_code": 200,
                "language_used": lang,
                "error": "",
                "title_variants": [],
            })
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
            
