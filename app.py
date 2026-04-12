import html
import os
import re
import json
import requests
from datetime import datetime
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from openai import OpenAI, OpenAIError

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

# Category-specific fields that may be present in AI analysis results.
# Used by API endpoints to dynamically pass through category data.
CATEGORY_SPECIFIC_FIELDS = [
    "scent_family", "fragrance_notes", "scent_evolution", "projection",
    "longevity", "best_season", "best_occasions", "emotional_triggers",
    "luxury_description",
    "specs", "performance", "use_cases", "pros", "cons",
    "style", "materials", "fit", "occasions", "care_instructions",
    "platform", "features", "integrations", "pricing_model",
    "problem", "solution", "monetization", "competitive_advantage", "market_size",
    "specifications",
]


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
    if not description or not isinstance(description, str):
        return False

    text = description.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    if "<p>" not in text or "</p>" not in text:
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


def _convert_bullets_to_html(text: str) -> str:
    """Convert plain-text bullet lines (• or -) to <ul><li> HTML if no <ul> is present."""
    if "<ul>" in text.lower():
        return text

    lines = text.splitlines()
    bullet_pattern = re.compile(r"^\s*[-•*]\s+(\S[^\r\n]*)$")
    result = []
    ul_items = []

    def flush_ul():
        if ul_items:
            result.append("<ul>")
            for item in ul_items:
                # Bold the label before the first colon, if present
                if ":" in item:
                    label, _, rest = item.partition(":")
                    result.append(
                        f"<li><strong>{html.escape(label.strip())}:</strong>{html.escape(rest)}</li>"
                    )
                else:
                    result.append(f"<li>{html.escape(item.strip())}</li>")
            result.append("</ul>")
            ul_items.clear()

    for line in lines:
        m = bullet_pattern.match(line)
        if m:
            ul_items.append(m.group(1))
        else:
            flush_ul()
            if line.strip():
                result.append(line)

    flush_ul()
    return "\n".join(result)


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
You are a senior ecommerce product strategist, technical product analyst, and conversion copywriter.
You write expert-level, highly specific, conversion-focused product content — NOT generic marketing text.

---
STEP 1 — IDENTIFY PRODUCT CATEGORY
Classify the product into exactly one of these categories:
- perfume / fragrance
- skincare / beauty
- grooming
- electronics
- fashion
- home product
- supplement
- general ecommerce product

---
STEP 2 — DEEP PRODUCT ANALYSIS (based on category)

For "perfume / fragrance":
- Identify the scent family (floral, oriental, woody, fresh, citrus, gourmand, etc.)
- Infer top notes, heart notes, and base notes when the input supports it
- Describe mood, occasion, season, and target audience
- Highlight luxury selling angles that drive conversion

For "skincare / beauty":
- Identify likely active ingredients when the input supports it
- Describe skin type fit, benefits, usage instructions, and concerns addressed
- Avoid unsafe medical claims — use phrases like "may help", "formulated to", "designed to"

For "grooming" or "electronics":
- Explain function, use case, target customer, pain points solved, and key differentiators

For "supplement":
- Describe the intended benefit, key ingredients or compounds (if supported), usage, and target user
- Avoid guaranteed health claims — use "formulated to support", "may aid", etc.

For "fashion":
- Describe style, material hints, fit, occasions, and target buyer persona

For "home product":
- Explain practical function, daily use case, convenience benefits, and who it is for

For any category:
- If ingredients, notes, or components are NOT in the input, infer carefully and prefix uncertain details with "Likely:"
- Never present inferred details as guaranteed facts

---
STEP 3 — OUTPUT
Return ONLY valid JSON. No markdown. No code fences. No extra text.

The JSON must have EXACTLY these fields:

{{
  "category": "detected category from the list above",
  "title": "optimized SEO title — must be compelling, benefit-driven, and different from the original",
  "short_summary": "2–3 sentence persuasive hook for the product",
  "technical_analysis": "expert-level analysis of what makes this product distinctive — ingredients, mechanism, design, or sensory profile",
  "target_audience": "specific description of who this product is for and why it fits their needs",
  "ingredients_or_notes": "ingredients, fragrance notes, or key components — infer carefully when not in the input and prefix uncertain items with Likely:",
  "key_benefits": ["benefit 1", "benefit 2", "benefit 3", "benefit 4", "benefit 5"],
  "selling_points": ["conversion angle 1", "conversion angle 2", "conversion angle 3"],
  "long_description": "<valid HTML — see structure below>",
  "meta_description": "under 155 characters, buyer-intent focused",
  "keywords": "comma-separated buyer-intent keywords"
}}

long_description HTML structure (STRICT):
<p>Opening hook paragraph that grabs attention and highlights the primary benefit or sensory appeal.</p>
<p>Second paragraph that addresses the buyer's pain point or desire and positions this product as the ideal solution.</p>
<ul>
<li><strong>Benefit 1:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 2:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 3:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 4:</strong> Specific, outcome-focused explanation.</li>
<li><strong>Benefit 5:</strong> Specific, outcome-focused explanation.</li>
</ul>
<p>Closing persuasive call to action that creates urgency or desire.</p>

STRICT RULES for long_description:
- Use ONLY <p>, <ul>, <li>, <strong> tags
- MUST have exactly 5 <li> items
- Each <li> MUST follow the format <li><strong>Label:</strong> explanation</li>
- DO NOT use "•" or "-" or "*" or plain text bullets
- DO NOT escape HTML characters
- DO NOT break the HTML structure

GLOBAL RULES:
- DO NOT use vague words like "ultimate", "premium", "our product", "amazing"
- Use real, specific search keywords naturally throughout
- All text content must be written entirely in {language_name}
- key_benefits and selling_points must be JSON arrays
- meta_description must be under 155 characters
- DO NOT wrap output in markdown or code fences

---
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
    new_long_description = ""
    new_meta_description = ""
    new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
    new_category = ""
    new_short_summary = ""
    new_technical_analysis = ""
    new_target_audience = ""
    new_ingredients_or_notes = ""
    new_key_benefits = []
    new_selling_points = []
    source_used = "initial_fallback"

    for _ in range(MAX_AI_GENERATION_RETRIES):
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior ecommerce product strategist and conversion copywriter. "
                        "You return clean, structured JSON only — no markdown, no code fences, no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
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
        candidate_long_description = str(ai_result.get("long_description") or "").strip()
        candidate_meta = str(ai_result.get("meta_description") or "").strip()
        candidate_keywords = str(ai_result.get("keywords") or "").strip()
        candidate_category = str(ai_result.get("category") or "").strip()
        candidate_short_summary = str(ai_result.get("short_summary") or "").strip()
        candidate_technical_analysis = str(ai_result.get("technical_analysis") or "").strip()
        candidate_target_audience = str(ai_result.get("target_audience") or "").strip()
        candidate_ingredients_or_notes = str(ai_result.get("ingredients_or_notes") or "").strip()

        raw_benefits = ai_result.get("key_benefits") or []
        candidate_key_benefits = (
            list(raw_benefits) if isinstance(raw_benefits, list)
            else [str(raw_benefits)]
        )

        raw_selling = ai_result.get("selling_points") or []
        candidate_selling_points = (
            list(raw_selling) if isinstance(raw_selling, list)
            else [str(raw_selling)]
        )

        candidate_long_description = _convert_bullets_to_html(candidate_long_description)

        if not _is_valid_ai_description(candidate_long_description):
            continue

        new_title = candidate_title
        new_long_description = candidate_long_description
        if "<ul>" not in new_long_description:
            new_long_description = _convert_bullets_to_html(new_long_description)
        new_meta_description = candidate_meta
        new_keywords = candidate_keywords or new_keywords
        new_category = candidate_category
        new_short_summary = candidate_short_summary
        new_technical_analysis = candidate_technical_analysis
        new_target_audience = candidate_target_audience
        new_ingredients_or_notes = candidate_ingredients_or_notes
        new_key_benefits = candidate_key_benefits
        new_selling_points = candidate_selling_points
        source_used = "ai"
        break

    if not new_long_description or not _is_valid_ai_description(new_long_description):
        new_long_description = fallback_description
        new_title = title or "Optimized Product"
        new_meta_description = sanitize_plain_text(new_long_description)
        new_keywords = f"{title}, {vendor}, {product_type}" if product_type else f"{title}, {vendor}"
        source_used = "generated_fallback"

    if not new_meta_description:
        fallback_meta = sanitize_plain_text(new_long_description or fallback_description or new_title)
        if len(fallback_meta) > 155:
            fallback_meta = fallback_meta[:152].rstrip() + "..."
        new_meta_description = fallback_meta

    if len(new_meta_description) > 155:
        new_meta_description = new_meta_description[:152].rstrip() + "..."

    if not new_keywords:
        fallback_keywords_parts = [title, vendor, product_type]
        fallback_keywords_parts = [k.strip() for k in fallback_keywords_parts if k and k.strip()]
        new_keywords = ", ".join(fallback_keywords_parts[:6])

    if "<ul>" not in new_long_description:
        new_long_description = _convert_bullets_to_html(new_long_description)

    return {
        "category": new_category,
        "title": new_title,
        "short_summary": new_short_summary,
        "technical_analysis": new_technical_analysis,
        "target_audience": new_target_audience,
        "ingredients_or_notes": new_ingredients_or_notes,
        "key_benefits": new_key_benefits,
        "selling_points": new_selling_points,
        "long_description": new_long_description,
        "description": new_long_description,
        "meta_description": new_meta_description,
        "keywords": new_keywords,
        "source_used": source_used,
        "has_ul": "<ul>" in new_long_description.lower(),
        "li_count": new_long_description.lower().count("<li>"),
        "contains_bullet_symbol": "•" in new_long_description,
    }


def enforce_no_empty_fields(data: dict, idea: str = "") -> dict:
    """Fill any missing, empty, or weak values with inferred expert-level content.

    Category-aware: applies fragrance-specific defaults only when the detected
    category is fragrance.  For all other categories the defaults are generic
    and product-appropriate.

    Ensures zero empty strings, zero empty arrays, and zero forbidden phrases
    in the final output.
    """
    idea_lower = idea.lower()
    category = (data.get("category") or "").lower()

    # --- Detect whether this is a fragrance product ---
    fragrance_keywords = ["perfume", "parfum", "fragrance", "cologne", "oud", "eau de"]
    is_fragrance = category == "fragrance" or any(k in idea_lower for k in fragrance_keywords)

    # --- Always-required string fields (universal) ---
    string_defaults = {
        "short_summary": f"Likely an expertly crafted product with distinctive character — {idea[:80]}",
        "technical_analysis": f"Likely a well-structured product with strong market positioning — {idea[:80]}",
        "target_audience": "Likely discerning individuals who value quality and distinction",
        "meta_description": idea[:150] if idea else "Expertly crafted product",
        "keywords": idea[:100] if idea else "quality, premium, product",
        "category": category or ("fragrance" if is_fragrance else "generic_product"),
    }

    for field, fallback in string_defaults.items():
        val = data.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            data[field] = fallback

    # --- Always-required list fields (universal) ---
    list_defaults = {
        "key_benefits": ["Likely premium quality", "Likely distinctive character", "Likely strong value proposition"],
        "selling_points": ["Likely expert craftsmanship", "Likely unique positioning", "Likely compelling value"],
    }

    for field, fallback in list_defaults.items():
        val = data.get(field)
        if not val or (isinstance(val, list) and len(val) == 0):
            data[field] = fallback

    # --- Fragrance-specific defaults (only when category is fragrance) ---
    if is_fragrance:
        has_oud = "oud" in idea_lower
        has_spicy = "spicy" in idea_lower or "spice" in idea_lower
        has_parfum = "parfum" in idea_lower
        luxury_brands = [
            "tom ford", "dior", "chanel", "creed", "maison francis kurkdjian",
            "byredo", "le labo", "amouage", "xerjoff", "roja", "clive christian",
            "initio", "parfums de marly", "nishane", "tiziana terenzi",
        ]
        is_luxury = any(b in idea_lower for b in luxury_brands)

        if has_oud:
            default_family = "Likely woody-oriental"
            default_top = ["Likely: saffron", "Likely: bergamot"]
            default_heart = ["Likely: oud", "Likely: rose"]
            default_base = ["Likely: sandalwood", "Likely: musk", "Likely: amber"]
            default_projection = "Likely strong projection given oud concentration"
            default_longevity = "Likely long-lasting (8–12 hours) due to oud and resinous base"
        elif has_spicy:
            default_family = "Likely warm spicy"
            default_top = ["Likely: black pepper", "Likely: cardamom"]
            default_heart = ["Likely: cinnamon", "Likely: nutmeg"]
            default_base = ["Likely: vanilla", "Likely: tonka bean", "Likely: amber"]
            default_projection = "Likely moderate to strong projection"
            default_longevity = "Likely moderate to long-lasting (6–10 hours)"
        elif has_parfum:
            default_family = "Likely a concentrated fragrance composition"
            default_top = ["Likely: citrus accord", "Likely: aromatic opening"]
            default_heart = ["Likely: floral or woody heart"]
            default_base = ["Likely: musk", "Likely: amber", "Likely: woods"]
            default_projection = "Likely strong projection due to parfum concentration"
            default_longevity = "Likely long-lasting (10+ hours) — parfum concentration ensures endurance"
        elif is_luxury:
            default_family = "Likely a complex, artisan fragrance composition"
            default_top = ["Likely: refined citrus or spice opening"]
            default_heart = ["Likely: rare florals or precious woods"]
            default_base = ["Likely: ambergris", "Likely: musk", "Likely: precious woods"]
            default_projection = "Likely moderate to strong — crafted for presence"
            default_longevity = "Likely long-lasting (8+ hours) — luxury formulation ensures endurance"
        else:
            default_family = "Likely a balanced fragrance composition"
            default_top = ["Likely: fresh aromatic opening"]
            default_heart = ["Likely: floral or woody heart accord"]
            default_base = ["Likely: musk", "Likely: cedarwood"]
            default_projection = "Likely moderate projection"
            default_longevity = "Likely moderate longevity (4–6 hours)"

        frag_string_defaults = {
            "scent_family": default_family,
            "projection": default_projection,
            "longevity": default_longevity,
        }
        for field, fallback in frag_string_defaults.items():
            val = data.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                data[field] = fallback

        notes = data.get("fragrance_notes")
        if not isinstance(notes, dict):
            notes = {"top": [], "heart": [], "base": []}
            data["fragrance_notes"] = notes
        if not notes.get("top"):
            notes["top"] = default_top
        if not notes.get("heart"):
            notes["heart"] = default_heart
        if not notes.get("base"):
            notes["base"] = default_base
        data["fragrance_notes"] = notes

    # --- Ensure long_description is non-empty ---
    if not data.get("long_description") or not data["long_description"].strip():
        data["long_description"] = f"<p>{idea}</p>"

    # --- Ensure title is non-empty ---
    if not data.get("title") or not data["title"].strip():
        data["title"] = idea

    # --- Final pass: scan all string fields for any remaining forbidden phrases ---
    _final_banned_re = re.compile(
        r"\b(not specified|not provided|unavailable|cannot be determined|no data)\b",
        re.IGNORECASE,
    )

    def _final_scrub(value):
        if isinstance(value, str):
            if _final_banned_re.search(value):
                cleaned = _final_banned_re.sub("inferred from product positioning", value)
                while "  " in cleaned:
                    cleaned = cleaned.replace("  ", " ")
                return cleaned.strip()
            return value
        if isinstance(value, list):
            result = [_final_scrub(v) for v in value]
            return result if result else ["Likely relevant based on product context"]
        if isinstance(value, dict):
            return {k: _final_scrub(v) for k, v in value.items()}
        return value

    data = _final_scrub(data)

    return data


def analyze_product_with_ai(idea: str):
    prompt = f"""
You are a universal product intelligence analyst and domain expert.
You analyze ANY type of product or business idea with professional expertise.

You must strictly respect the provided product content.
If information is explicitly present, use it exactly.
If information is missing, infer only when there is a strong logical signal.
Use realistic domain knowledge, not fantasy.
NEVER say "not specified", "not provided", "unavailable", "cannot be determined", or "no data".
If something is unknown, infer it with domain expertise and prefix with "Likely".

---
INPUT:
{idea}

---
CRITICAL RULES:

1) DO NOT ignore the input content.
2) DO NOT replace it with generic marketing text.
3) DO NOT fully invent product details with no basis in the input.
4) You MUST:
   - reorganize the text
   - improve clarity
   - upgrade language to premium level
   - extract structured data
   - use explicit product information exactly as given
   - infer missing details only when there is a strong logical signal
   - prefix inferred values with "Likely"
5) You MUST NOT:
   - EVER use "not specified", "not provided", "unavailable", "cannot be determined", or "no data"
   - produce empty or placeholder analysis
   - use generic marketing filler
6) Balance accuracy with expert reasoning.

---
STEP 1 — DETECT CATEGORY
Classify the input into EXACTLY ONE of these categories:
- fragrance
- electronics
- fashion
- software
- business_idea
- generic_product

---
STEP 2 — GENERATE CATEGORY-SPECIFIC ANALYSIS

ALWAYS include these universal fields:
- title
- short_summary (2–3 sentence expert summary)
- category (from Step 1)
- key_benefits (array of 3–5 benefits)
- target_audience (specific description of who this is for)
- technical_analysis (expert-level analysis)
- long_description (HTML)
- meta_description (under 155 chars)
- keywords (comma-separated)
- selling_points (array of 3 conversion angles)

ADDITIONALLY, include category-specific fields:

IF category is "fragrance":
- scent_family: the fragrance family (e.g. "woody-oriental", "fresh citrus")
- fragrance_notes: {{ "top": [...], "heart": [...], "base": [...] }}
- projection: "soft" / "moderate" / "strong"
- longevity: "short" / "moderate" / "long-lasting" with hour estimates

IF category is "electronics":
- specs: key technical specifications as an object (e.g. {{"processor": "...", "ram": "...", "storage": "..."}})
- performance: performance analysis string
- use_cases: array of ideal use cases
- pros: array of advantages
- cons: array of disadvantages or limitations

IF category is "fashion":
- style: style description (e.g. "casual streetwear", "formal business")
- materials: array of materials or fabrics
- fit: fit description
- occasions: array of suitable occasions
- care_instructions: care/maintenance tips

IF category is "software":
- platform: target platform(s)
- features: array of key features
- integrations: array of integrations or compatible tools
- pricing_model: pricing structure description
- use_cases: array of ideal use cases

IF category is "business_idea":
- problem: the problem being solved
- solution: the proposed solution
- monetization: how it makes money
- competitive_advantage: what sets it apart
- market_size: estimated market opportunity

IF category is "generic_product":
- specifications: key product specs as an object
- use_cases: array of use cases
- pros: array of advantages
- cons: array of limitations

---
STEP 3 — OUTPUT
Return ONLY valid JSON. No markdown. No code fences. No extra text.

long_description HTML structure (STRICT):
<p>Opening hook paragraph referencing specific product elements.</p>
<p>Second paragraph addressing the buyer's need and positioning this product.</p>
<ul>
<li><strong>Label:</strong> Specific explanation.</li>
<li><strong>Label:</strong> Specific explanation.</li>
<li><strong>Label:</strong> Specific explanation.</li>
<li><strong>Label:</strong> Specific explanation.</li>
<li><strong>Label:</strong> Specific explanation.</li>
</ul>
<p>Closing paragraph — expert recommendation.</p>

RULES:
- Detect the correct category FIRST, then include the matching category-specific fields
- Be specific to THIS product — never produce generic content
- DO NOT include category-specific fields that don't match the detected category
- Prefix inferred items with "Likely" or "Likely:"
- NEVER use "not specified", "not provided", "unavailable", "cannot be determined", "no data"
- long_description must use only <p>, <ul>, <li>, <strong> tags and contain exactly 5 <li> items
- Return ONLY valid JSON — no markdown, no code fences, no extra text
"""

    for _ in range(MAX_AI_GENERATION_RETRIES):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a universal product intelligence analyst and domain expert. "
                            "You analyze ANY product or business idea — fragrances, electronics, fashion, software, business ideas, and more. "
                            "You must strictly respect the provided content. "
                            "If information is explicitly present, use it exactly. "
                            "If information is missing, infer only when there is a strong logical signal — use realistic domain knowledge, not fantasy. "
                            "NEVER output 'not specified', 'not provided', 'unavailable', 'cannot be determined', or 'no data' — always infer with 'Likely' prefix instead. "
                            "Produce useful expert analysis — zero-insight output is wrong, fully-invented output is wrong. "
                            "You return clean, structured JSON only — no markdown, no code fences, no extra text."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
            )
        except (OpenAIError, ConnectionError, TimeoutError) as exc:
            print(f"analyze_product_with_ai: API call failed, retrying: {exc}")
            continue

        content = response.choices[0].message.content
        if not content:
            continue

        cleaned = content.strip()

        # Remove code block markers if present
        cleaned = re.sub(r"^```json", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except Exception as e:
            print("JSON PARSE ERROR:", str(e))
            print("RAW OUTPUT:", content)

            # fallback safe structure
            data = {
                "title": idea,
                "short_summary": cleaned[:200],
                "category": "generic_product",
                "key_benefits": [],
                "selling_points": [],
                "target_audience": "",
                "technical_analysis": "",
                "long_description": cleaned,
                "meta_description": cleaned[:150],
                "keywords": idea,
            }

        if not isinstance(data, dict):
            continue

        # --- Process the parsed dict and build the structured output --------
        try:
            # --- Bullet handling: convert dash/bullet lines in
            # long_description to proper <ul><li> HTML. ---
            ld = data.get("long_description", "")
            if ld:
                def _bullets_to_html(text: str) -> str:
                    _bullet_re = re.compile(r"^[-•–]\s+")
                    lines = text.split("\n")
                    result: list[str] = []
                    in_list = False
                    for line in lines:
                        stripped = line.strip()
                        is_bullet = bool(
                            _bullet_re.match(stripped)
                        ) and "<li>" not in stripped
                        if is_bullet:
                            if not in_list:
                                result.append("<ul>")
                                in_list = True
                            content = _bullet_re.sub("", stripped)
                            result.append(f"<li>{content}</li>")
                        else:
                            if in_list:
                                result.append("</ul>")
                                in_list = False
                            result.append(line)
                    if in_list:
                        result.append("</ul>")
                    return "\n".join(result)

                data["long_description"] = _bullets_to_html(ld)

            # --- Strip banned phrases from ALL string values ---------------
            _banned_re = re.compile(
                r"\b(not specified|not provided|unavailable|cannot be determined|no data)\b",
                re.IGNORECASE,
            )

            def _infer_replacement(field_context: str = "") -> str:
                """Generate an intelligent inference replacement based on product context."""
                return "Likely a well-crafted product based on market positioning"

            def _scrub(value, field_name=""):
                """Recursively replace banned phrases with intelligent inferences."""
                if isinstance(value, str):
                    if _banned_re.search(value):
                        stripped_check = _banned_re.sub("", value).strip(" .,;:-–—")
                        if not stripped_check or len(stripped_check) < 5:
                            return _infer_replacement(field_name)
                        scrubbed = _banned_re.sub("inferred from product context", value)
                        while "  " in scrubbed:
                            scrubbed = scrubbed.replace("  ", " ")
                        return scrubbed.strip()
                    return value
                if isinstance(value, list):
                    return [_scrub(v, field_name) for v in value]
                if isinstance(value, dict):
                    return {k: _scrub(v, k) for k, v in value.items()}
                return value

            data = _scrub(data)

            # Flatten nested AI response fields that may have been returned
            # under alternate keys.
            insights = data.pop("extracted_insights", None) or {}
            frag = data.pop("fragrance_analysis", None) or {}

            # clean_summary → short_summary
            if "clean_summary" in data and "short_summary" not in data:
                data["short_summary"] = data.pop("clean_summary")

            # luxury_upgrade_text → luxury_description
            if "luxury_upgrade_text" in data and "luxury_description" not in data:
                data["luxury_description"] = data.pop("luxury_upgrade_text")

            # extracted_insights → flat fields
            data.setdefault("key_benefits", insights.get("benefits", []))
            data.setdefault("selling_points", insights.get("key_features", []))
            data.setdefault("target_audience", insights.get("positioning", ""))

            # fragrance_analysis → flat fields (only if present)
            if frag:
                data.setdefault("scent_family", frag.get("scent_family", ""))
                data.setdefault("fragrance_notes", {
                    "top": frag.get("top_notes", []),
                    "heart": frag.get("heart_notes", []),
                    "base": frag.get("base_notes", []),
                })
                data.setdefault("projection", frag.get("projection", ""))
                data.setdefault("longevity", frag.get("longevity", ""))

            # --- Build the output dict with universal + category fields ---
            output = {
                "title": data.get("title", idea),
                "short_summary": data.get("short_summary", ""),
                "category": data.get("category", "generic_product"),
                "key_benefits": data.get("key_benefits", []),
                "target_audience": data.get("target_audience", ""),
                "technical_analysis": data.get("technical_analysis", ""),
                "selling_points": data.get("selling_points", []),
                "long_description": data.get("long_description", ""),
                "meta_description": data.get("meta_description", ""),
                "keywords": data.get("keywords", ""),
            }

            # Include any category-specific fields the AI returned
            category = (data.get("category") or "generic_product").lower()

            if category == "fragrance":
                output["scent_family"] = data.get("scent_family", "")
                output["fragrance_notes"] = data.get("fragrance_notes", {"top": [], "heart": [], "base": []})
                output["projection"] = data.get("projection", "")
                output["longevity"] = data.get("longevity", "")
                output["scent_evolution"] = data.get("scent_evolution", "")
                output["best_season"] = data.get("best_season", "")
                output["best_occasions"] = data.get("best_occasions", [])
                output["emotional_triggers"] = data.get("emotional_triggers", [])
                output["luxury_description"] = data.get("luxury_description", "")
            elif category == "electronics":
                output["specs"] = data.get("specs", {})
                output["performance"] = data.get("performance", "")
                output["use_cases"] = data.get("use_cases", [])
                output["pros"] = data.get("pros", [])
                output["cons"] = data.get("cons", [])
            elif category == "fashion":
                output["style"] = data.get("style", "")
                output["materials"] = data.get("materials", [])
                output["fit"] = data.get("fit", "")
                output["occasions"] = data.get("occasions", [])
                output["care_instructions"] = data.get("care_instructions", "")
            elif category == "software":
                output["platform"] = data.get("platform", "")
                output["features"] = data.get("features", [])
                output["integrations"] = data.get("integrations", [])
                output["pricing_model"] = data.get("pricing_model", "")
                output["use_cases"] = data.get("use_cases", [])
            elif category == "business_idea":
                output["problem"] = data.get("problem", "")
                output["solution"] = data.get("solution", "")
                output["monetization"] = data.get("monetization", "")
                output["competitive_advantage"] = data.get("competitive_advantage", "")
                output["market_size"] = data.get("market_size", "")
            else:  # generic_product
                output["specifications"] = data.get("specifications", {})
                output["use_cases"] = data.get("use_cases", [])
                output["pros"] = data.get("pros", [])
                output["cons"] = data.get("cons", [])

            return enforce_no_empty_fields(output, idea)
        except Exception as exc:
            print("ANALYZE ERROR:", str(exc))
            continue

    fallback = {
        "title": idea,
        "short_summary": "",
        "category": "generic_product",
        "key_benefits": [],
        "target_audience": "",
        "technical_analysis": "",
        "selling_points": [],
        "long_description": f"<p>{idea}</p>",
        "meta_description": "",
        "keywords": idea,
    }
    try:
        return enforce_no_empty_fields(fallback, idea)
    except Exception as e:
        print("ANALYZE ERROR:", str(e))
        return fallback


def looks_like_fragrance(product):
    text = " ".join([
        str(product.get("title", "")).lower(),
        str(product.get("product_type", "")).lower(),
        str(product.get("tags", "")).lower(),
        str(product.get("body_html", "")).lower(),
    ])

    keywords = [
        "perfume", "parfum", "fragrance", "cologne",
        "eau de parfum", "eau de toilette",
        "oud", "tom ford", "dior", "chanel",
        "\u0639\u0637\u0631", "\u0628\u0627\u0631\u0641\u0627\u0646"
    ]

    return any(k in text for k in keywords)


def looks_like_fragrance_product(product: dict) -> bool:
    text = " ".join([
        (product.get("title") or "").lower(),
        (product.get("product_type") or "").lower(),
        (product.get("tags") or "").lower(),
        (product.get("body_html") or "").lower(),
    ])

    keywords = [
        "perfume", "parfum", "fragrance", "cologne",
        "oud", "eau de parfum", "eau de toilette",
        "tom ford", "dior", "chanel",
        "\u0639\u0637\u0631", "\u0628\u0627\u0631\u0641\u0627\u0646",
    ]

    matched = [k for k in keywords if k in text]
    is_frag = len(matched) > 0
    print(f"[FRAGRANCE DEBUG] title={product.get('title')!r} | is_fragrance={is_frag} | matched_keywords={matched}")
    return is_frag


def optimize_product_router(product, lang="en"):
    """Route any product through the universal product intelligence engine.

    Builds a rich input string from the product's fields and sends it through
    analyze_product_with_ai() which auto-detects the category and returns
    category-specific structured data.
    """
    title = product.get("title", "")
    brand = product.get("vendor", "")
    product_type = product.get("product_type", "")
    tags = product.get("tags", "")
    body_html = product.get("body_html", "")

    idea = (
        f"[PRODUCT TO ANALYZE]\n"
        f"This is a real product currently listed for sale. "
        f"Analyze it as a specific, existing product — do NOT generate generic content.\n"
        f"\n"
        f"Full Product Title: {title}\n"
        f"Brand / Vendor: {brand}\n"
        f"Product Type: {product_type}\n"
        f"Tags: {tags}\n"
        f"Product Description / Body HTML:\n{body_html}"
    ).strip()

    result = analyze_product_with_ai(idea)
    print("PRODUCT ROUTER RESULT:", result.get("category"), result.get("title"))

    result.setdefault("title", product.get("title", ""))
    result.setdefault("category", "generic_product")
    result.setdefault("short_summary", "")
    result.setdefault("technical_analysis", "")
    result.setdefault("target_audience", "")
    result.setdefault("key_benefits", [])
    result.setdefault("selling_points", [])
    result.setdefault("long_description", "")
    result.setdefault("meta_description", "")
    result.setdefault("keywords", "")

    # Backward compatibility: set is_fragrance flag
    result["is_fragrance"] = (result.get("category", "").lower() == "fragrance")

    return result


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
        /* ── Result card styles ── */
        .result-card {
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 20px;
            margin-top: 18px;
            background: #fff;
        }
        .result-card .product-title {
            font-size: 22px;
            font-weight: 700;
            margin: 6px 0 10px;
            color: #1e293b;
        }
        .result-card .badge {
            display: inline-block;
            background: #fbbf24;
            color: #000;
            padding: 3px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 6px;
            vertical-align: middle;
        }
        .result-card .summary-text {
            font-size: 15px;
            color: #374151;
            line-height: 1.6;
            margin: 8px 0 14px;
        }
        .result-card .meta-row {
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 4px;
        }
        .result-card .meta-row strong {
            color: #374151;
        }
        .section-box {
            margin-top: 14px;
            padding: 14px 16px;
            border-radius: 12px;
        }
        .section-box h4 {
            margin: 0 0 10px;
            font-size: 15px;
        }
        .fragrance-box {
            background: #fdf6ec;
            border: 1px solid #f5d89a;
        }
        .fragrance-box h4 { color: #92400e; }
        .notes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin: 10px 0;
        }
        .note-card {
            background: #fff;
            border: 1px solid #fde68a;
            border-radius: 10px;
            padding: 10px 12px;
        }
        .note-card .note-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #92400e;
            margin-bottom: 4px;
        }
        .note-card .note-value {
            font-size: 13px;
            color: #1e293b;
        }
        .detail-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 8px;
        }
        .detail-chip {
            background: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }
        .detail-chip .chip-label {
            font-weight: 700;
            color: #92400e;
            font-size: 11px;
            text-transform: uppercase;
            display: block;
            margin-bottom: 2px;
        }
        .tag-list {
            list-style: none;
            padding: 0;
            margin: 6px 0 0;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .tag-list li {
            background: #fef3c7;
            border: 1px solid #fde68a;
            border-radius: 20px;
            padding: 4px 12px;
            font-size: 13px;
            color: #78350f;
        }
        .scent-family-value {
            font-size: 16px;
            font-weight: 600;
            color: #78350f;
        }
        .description-box {
            background: #f9fafb;
            border: 1px solid #e5e7eb;
        }
        .description-box h4 { color: #1e293b; }
        .description-html {
            font-size: 14px;
            line-height: 1.7;
            color: #374151;
        }
        .description-html ul {
            padding-left: 20px;
            margin: 10px 0;
        }
        .description-html li {
            margin-bottom: 6px;
        }
        .diagnostics-row {
            margin-top: 10px;
            font-size: 11px;
            color: #9ca3af;
            background: #f9fafb;
            padding: 6px 10px;
            border-radius: 6px;
        }
        .seo-box {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
        }
        .seo-box h4 { color: #166534; }
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
                    const category = (item.category || "").toLowerCase();

                    /* ── Category badge ── */
                    const categoryBadgeColors = {
                        fragrance: { bg: "#fbbf24", icon: "🌸" },
                        electronics: { bg: "#60a5fa", icon: "💻" },
                        fashion: { bg: "#f472b6", icon: "👗" },
                        software: { bg: "#a78bfa", icon: "🖥️" },
                        business_idea: { bg: "#34d399", icon: "💡" },
                        generic_product: { bg: "#9ca3af", icon: "📦" },
                    };
                    const badgeInfo = categoryBadgeColors[category] || categoryBadgeColors.generic_product;
                    const categoryBadge = `<span class="badge" style="background:${badgeInfo.bg};">${badgeInfo.icon} ${item.category || "Product"}</span>`;

                    /* ── FRAGRANCE sections (only if category is fragrance) ── */
                    let scentFamilyHtml = "";
                    if (item.scent_family) {
                        scentFamilyHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🌿 Scent Family</h4>
                                <div class="scent-family-value">${item.scent_family}</div>
                            </div>
                        `;
                    }

                    let fragranceNotesHtml = "";
                    const notes = item.fragrance_notes || {};
                    const hasNotes = (Array.isArray(notes.top) && notes.top.length) ||
                                     (Array.isArray(notes.heart) && notes.heart.length) ||
                                     (Array.isArray(notes.base) && notes.base.length);
                    if (hasNotes) {
                        const topNotes = Array.isArray(notes.top) ? notes.top.join(", ") : "";
                        const heartNotes = Array.isArray(notes.heart) ? notes.heart.join(", ") : "";
                        const baseNotes = Array.isArray(notes.base) ? notes.base.join(", ") : "";
                        fragranceNotesHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🎵 Fragrance Notes</h4>
                                <div class="notes-grid">
                                    ${topNotes ? `<div class="note-card"><div class="note-label">Top Notes</div><div class="note-value">${topNotes}</div></div>` : ""}
                                    ${heartNotes ? `<div class="note-card"><div class="note-label">Heart Notes</div><div class="note-value">${heartNotes}</div></div>` : ""}
                                    ${baseNotes ? `<div class="note-card"><div class="note-label">Base Notes</div><div class="note-value">${baseNotes}</div></div>` : ""}
                                </div>
                                ${item.scent_evolution ? `<div style="margin-top:10px;font-size:13px;"><strong style="color:#92400e;">Scent Evolution:</strong> ${item.scent_evolution}</div>` : ""}
                            </div>
                        `;
                    }

                    let fragrancePerformanceHtml = "";
                    if (item.projection || item.longevity) {
                        fragrancePerformanceHtml = `
                            <div class="section-box fragrance-box">
                                <h4>📊 Performance</h4>
                                <div class="detail-row">
                                    ${item.projection ? `<div class="detail-chip"><span class="chip-label">Projection</span>${item.projection}</div>` : ""}
                                    ${item.longevity ? `<div class="detail-chip"><span class="chip-label">Longevity</span>${item.longevity}</div>` : ""}
                                </div>
                            </div>
                        `;
                    }

                    let usageHtml = "";
                    if (item.best_season || (Array.isArray(item.best_occasions) && item.best_occasions.length)) {
                        usageHtml = `
                            <div class="section-box fragrance-box">
                                <h4>🗓️ Usage</h4>
                                ${item.best_season ? `<div style="margin-bottom:8px;"><strong style="font-size:13px;color:#92400e;">Best Season:</strong> <span style="font-size:13px;">${item.best_season}</span></div>` : ""}
                                ${Array.isArray(item.best_occasions) && item.best_occasions.length ? `<div><strong style="font-size:13px;color:#92400e;">Best Occasions</strong><ul class="tag-list">${item.best_occasions.map(o => `<li>${o}</li>`).join("")}</ul></div>` : ""}
                            </div>
                        `;
                    }

                    let emotionalHtml = "";
                    if (Array.isArray(item.emotional_triggers) && item.emotional_triggers.length) {
                        emotionalHtml = `
                            <div class="section-box fragrance-box">
                                <h4>💫 Emotional Profile</h4>
                                <ul class="tag-list">${item.emotional_triggers.map(e => `<li>${e}</li>`).join("")}</ul>
                            </div>
                        `;
                    }

                    let luxuryHtml = "";
                    if (item.luxury_description) {
                        luxuryHtml = `<div style="margin-top:10px;font-size:13px;font-style:italic;color:#78350f;padding:10px 14px;background:#fffbeb;border-radius:8px;border:1px solid #fde68a;">${item.luxury_description}</div>`;
                    }

                    /* ── ELECTRONICS sections ── */
                    let specsHtml = "";
                    if (item.specs && typeof item.specs === "object" && Object.keys(item.specs).length) {
                        const specRows = Object.entries(item.specs).map(([k, v]) => `<div class="detail-chip"><span class="chip-label">${k}</span>${v}</div>`).join("");
                        specsHtml = `
                            <div class="section-box" style="background:#eff6ff;border:1px solid #bfdbfe;">
                                <h4 style="color:#1e40af;">⚙️ Specifications</h4>
                                <div class="detail-row">${specRows}</div>
                            </div>
                        `;
                    }

                    let electronicsPerformanceHtml = "";
                    if (item.performance && category === "electronics") {
                        electronicsPerformanceHtml = `<div class="meta-row"><strong>Performance:</strong> ${item.performance}</div>`;
                    }

                    let prosHtml = "";
                    if (Array.isArray(item.pros) && item.pros.length) {
                        prosHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;color:#166534;">✅ Pros</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.pros.map(p => `<li>${p}</li>`).join("")}</ul></div>`;
                    }

                    let consHtml = "";
                    if (Array.isArray(item.cons) && item.cons.length) {
                        consHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;color:#991b1b;">⚠️ Cons</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.cons.map(c => `<li>${c}</li>`).join("")}</ul></div>`;
                    }

                    /* ── FASHION sections ── */
                    let fashionHtml = "";
                    if (item.style || item.fit || (Array.isArray(item.materials) && item.materials.length)) {
                        fashionHtml = `
                            <div class="section-box" style="background:#fdf2f8;border:1px solid #fbcfe8;">
                                <h4 style="color:#9d174d;">👗 Fashion Details</h4>
                                ${item.style ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Style:</strong> ${item.style}</div>` : ""}
                                ${item.fit ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Fit:</strong> ${item.fit}</div>` : ""}
                                ${Array.isArray(item.materials) && item.materials.length ? `<div style="font-size:13px;"><strong>Materials:</strong> ${item.materials.join(", ")}</div>` : ""}
                            </div>
                        `;
                    }

                    let fashionOccasionsHtml = "";
                    if (Array.isArray(item.occasions) && item.occasions.length) {
                        fashionOccasionsHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Occasions</strong><ul class="tag-list">${item.occasions.map(o => `<li>${o}</li>`).join("")}</ul></div>`;
                    }

                    let careHtml = "";
                    if (item.care_instructions) {
                        careHtml = `<div class="meta-row"><strong>Care:</strong> ${item.care_instructions}</div>`;
                    }

                    /* ── SOFTWARE sections ── */
                    let softwareHtml = "";
                    if (item.platform || (Array.isArray(item.features) && item.features.length)) {
                        softwareHtml = `
                            <div class="section-box" style="background:#f5f3ff;border:1px solid #ddd6fe;">
                                <h4 style="color:#5b21b6;">🖥️ Software Details</h4>
                                ${item.platform ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Platform:</strong> ${item.platform}</div>` : ""}
                                ${item.pricing_model ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Pricing:</strong> ${item.pricing_model}</div>` : ""}
                                ${Array.isArray(item.features) && item.features.length ? `<div style="font-size:13px;"><strong>Features:</strong><ul style="margin:4px 0 0;padding-left:20px;">${item.features.map(f => `<li>${f}</li>`).join("")}</ul></div>` : ""}
                            </div>
                        `;
                    }

                    let integrationsHtml = "";
                    if (Array.isArray(item.integrations) && item.integrations.length) {
                        integrationsHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Integrations</strong><ul class="tag-list">${item.integrations.map(i => `<li>${i}</li>`).join("")}</ul></div>`;
                    }

                    /* ── BUSINESS IDEA sections ── */
                    let businessHtml = "";
                    if (item.problem || item.solution || item.monetization) {
                        businessHtml = `
                            <div class="section-box" style="background:#ecfdf5;border:1px solid #a7f3d0;">
                                <h4 style="color:#065f46;">💡 Business Analysis</h4>
                                ${item.problem ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Problem:</strong> ${item.problem}</div>` : ""}
                                ${item.solution ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Solution:</strong> ${item.solution}</div>` : ""}
                                ${item.monetization ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Monetization:</strong> ${item.monetization}</div>` : ""}
                                ${item.competitive_advantage ? `<div style="margin-bottom:6px;font-size:13px;"><strong>Competitive Advantage:</strong> ${item.competitive_advantage}</div>` : ""}
                                ${item.market_size ? `<div style="font-size:13px;"><strong>Market Size:</strong> ${item.market_size}</div>` : ""}
                            </div>
                        `;
                    }

                    /* ── GENERIC PRODUCT specifications ── */
                    let genericSpecsHtml = "";
                    if (item.specifications && typeof item.specifications === "object" && Object.keys(item.specifications).length) {
                        const rows = Object.entries(item.specifications).map(([k, v]) => `<div class="detail-chip"><span class="chip-label">${k}</span>${v}</div>`).join("");
                        genericSpecsHtml = `
                            <div class="section-box" style="background:#f9fafb;border:1px solid #e5e7eb;">
                                <h4 style="color:#374151;">📋 Specifications</h4>
                                <div class="detail-row">${rows}</div>
                            </div>
                        `;
                    }

                    /* ── USE CASES (shared by electronics, software, generic) ── */
                    let useCasesHtml = "";
                    if (Array.isArray(item.use_cases) && item.use_cases.length) {
                        useCasesHtml = `<div style="margin-top:8px;"><strong style="font-size:13px;">Use Cases</strong><ul class="tag-list">${item.use_cases.map(u => `<li>${u}</li>`).join("")}</ul></div>`;
                    }

                    /* ── DESCRIPTION section (rendered as HTML) ── */
                    let descriptionHtml = "";
                    if (item.new_description) {
                        descriptionHtml = `
                            <div class="section-box description-box">
                                <h4>📝 Description</h4>
                                <div class="description-html">${item.new_description}</div>
                            </div>
                        `;
                    }

                    /* ── SEO section ── */
                    let seoHtml = "";
                    if (item.meta_description_preview || item.keywords) {
                        seoHtml = `
                            <div class="section-box seo-box">
                                <h4>🔎 SEO</h4>
                                ${item.meta_description_preview ? `<div style="font-size:13px;margin-bottom:6px;"><strong>Meta Description:</strong> ${item.meta_description_preview}</div>` : ""}
                                ${item.keywords ? `<div style="font-size:13px;"><strong>Keywords:</strong> ${item.keywords}</div>` : ""}
                            </div>
                        `;
                    }

                    html += `
                        <div class="result-card">
                            <div class="meta-row">
                                <strong>#${index + 1}</strong>
                                ${categoryBadge}
                                &nbsp;·&nbsp; Product ID: ${item.product_id ?? ""}
                                &nbsp;·&nbsp; ${item.success ? "✅ Success" : "❌ Failed"}
                            </div>

                            ${item.old_title ? `<div class="meta-row">Previously: ${item.old_title}</div>` : ""}

                            <div class="product-title">${item.new_title ?? ""}</div>

                            ${item.short_summary ? `<p class="summary-text">${item.short_summary}</p>` : ""}

                            ${item.technical_analysis ? `<div class="meta-row"><strong>Technical Analysis:</strong> ${item.technical_analysis}</div>` : ""}
                            ${item.target_audience ? `<div class="meta-row"><strong>Target Audience:</strong> ${item.target_audience}</div>` : ""}

                            ${benefits ? `<div style="margin-top:8px;"><strong style="font-size:13px;">Key Benefits</strong><ul style="margin:4px 0 0;padding-left:20px;">${benefits}</ul></div>` : ""}
                            ${sellingPts ? `<div style="margin-top:8px;"><strong style="font-size:13px;">Selling Points</strong><ul style="margin:4px 0 0;padding-left:20px;">${sellingPts}</ul></div>` : ""}

                            ${scentFamilyHtml}
                            ${fragranceNotesHtml}
                            ${fragrancePerformanceHtml}
                            ${usageHtml}
                            ${emotionalHtml}
                            ${luxuryHtml}
                            ${specsHtml}
                            ${electronicsPerformanceHtml}
                            ${prosHtml}
                            ${consHtml}
                            ${fashionHtml}
                            ${fashionOccasionsHtml}
                            ${careHtml}
                            ${softwareHtml}
                            ${integrationsHtml}
                            ${businessHtml}
                            ${genericSpecsHtml}
                            ${useCasesHtml}
                            ${descriptionHtml}
                            ${seoHtml}

                            <div class="diagnostics-row">
                                🔍 category=${item.category ?? "unknown"} | is_fragrance=${item.is_fragrance ?? false} | has_ul=${item.has_ul} | li_count=${item.li_count} | bullet_symbol=${item.contains_bullet_symbol} | source=${item.source_used ?? ""} | lang=${item.language_used ?? ""}
                            </div>
                            ${item.error ? `<div style="color:red;margin-top:8px;"><strong>Error:</strong> ${item.error}</div>` : ""}
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

    # Build response with universal fields
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
    }

    # Include all category-specific fields dynamically
    for field in CATEGORY_SPECIFIC_FIELDS:
        if field in result:
            response_data[field] = result[field]

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

    # Build response with universal fields
    response_data = {
        "category": result.get("category", ""),
        "title": result.get("title", idea),
        "short_summary": result.get("short_summary", ""),
        "technical_analysis": result.get("technical_analysis", ""),
        "target_audience": result.get("target_audience", ""),
        "key_benefits": result.get("key_benefits", []),
        "selling_points": result.get("selling_points", []),
        "long_description": long_desc,
        "meta_description": result.get("meta_description", ""),
        "keywords": result.get("keywords", ""),
        "has_ul": "<ul>" in long_desc.lower(),
        "li_count": long_desc.lower().count("<li>"),
    }

    # Include all category-specific fields dynamically
    for field in CATEGORY_SPECIFIC_FIELDS:
        if field in result:
            response_data[field] = result[field]

    return jsonify(response_data)


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
            }

            # Include all category-specific fields dynamically
            for field in CATEGORY_SPECIFIC_FIELDS:
                if field in optimized:
                    result_item[field] = optimized[field]

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
            
