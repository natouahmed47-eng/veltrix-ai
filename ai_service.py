"""AI service module — all OpenAI and product-analysis logic."""

import html
import json
import re

# ---------------------------------------------------------------------------
# Module-level OpenAI client – set once via init_ai_service()
# ---------------------------------------------------------------------------
_client = None
MAX_AI_GENERATION_RETRIES = 3


def init_ai_service(openai_client):
    """Bind the OpenAI client used by every function in this module."""
    global _client
    _client = openai_client


# ---------------------------------------------------------------------------
# Text / HTML helpers
# ---------------------------------------------------------------------------

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


def is_valid_html_description(html_text: str) -> bool:
    if not html_text or not isinstance(html_text, str):
        return False

    text = html_text.strip().lower()

    if "<ul>" not in text or "</ul>" not in text:
        return False

    li_count = text.count("<li>")
    if li_count < 5 or li_count > 7:
        return False

    if "<p>" not in text or "</p>" not in text:
        return False

    return True


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


# ---------------------------------------------------------------------------
# Product-angle / fallback helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Core AI functions
# ---------------------------------------------------------------------------

def build_title_and_description_with_ai(product: dict, lang: str = "en") -> dict:
    if not _client:
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
        response = _client.chat.completions.create(
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


def analyze_product_with_ai(idea: str) -> dict:
    """Analyze a product concept and return structured high-end product content.

    Handles perfumes / fragrances with dedicated note inference, and falls back
    to general ecommerce analysis for all other product categories.
    """
    if not _client:
        raise RuntimeError("OpenAI is not configured")

    prompt = f"""
You are a fragrance chemist, perfumer, and luxury product analyst.
You are also a domain expert with deep knowledge of perfumery, ingredients, accords, and scent composition.

You must strictly respect the provided product content.
However, you are also a domain expert.

If information is explicitly present, use it exactly.
If information is missing, infer only when there is a strong logical signal.
Use realistic domain knowledge, not fantasy.
If something truly cannot be inferred, say so briefly once, not repeatedly.

---
INPUT PRODUCT:
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
   - infer missing details only when there is a strong logical signal from the input or domain expertise
   - prefix inferred values with "Likely" (e.g. "Likely woody-oriental", "Likely moderate to strong projection")
5) You MUST NOT:
   - repeat "not specified", "unavailable", or "cannot be determined" more than once in the entire output
   - produce empty or placeholder analysis — every field should contain useful expert insight
   - use generic marketing filler (e.g. "luxurious fragrance", "captivating scent", "timeless elegance")
   - produce output that contains zero insight — that is wrong
   - produce output that is fully invented — that is wrong
6) Balance accuracy with expert reasoning.

---
STEP 1 — IDENTIFY CATEGORY
Classify the product into exactly one of:
- perfume / fragrance
- skincare / beauty
- grooming
- electronics
- fashion
- home product
- supplement
- general ecommerce product

---
STEP 2 — CATEGORY-SPECIFIC EXTRACTION

IF the product is a perfume / fragrance:

For fragrance products you MUST fill every field with useful content:
- scent_family: use explicit clues first; if absent, infer from product name, brand positioning, concentration type, or any descriptive words. Prefix with "Likely" if inferred (e.g. "Likely woody-oriental").
- top_notes: use notes mentioned in input; if none, infer from scent family and product clues using domain expertise. Prefix inferred notes with "Likely:".
- heart_notes: same approach as top_notes.
- base_notes: same approach as top_notes.
- scent_evolution: describe how the scent would evolve based on known or inferred notes. Use domain knowledge of volatility and molecular weight.
- projection: infer from concentration keywords (parfum = strong, eau de toilette = moderate, etc.), descriptors like "intense", "powerful", "soft". Use "Likely moderate to strong projection" style.
- longevity: infer from concentration type (parfum > EDP > EDT > EDC), keywords like "long-lasting", "enduring". Use "Likely" prefix if inferred.
- best_season: infer from composition weight and character — heavier orientals for fall/winter, lighter citrus/aquatic for spring/summer.
- best_occasions: infer from brand positioning, scent character, and product context.
- emotional_triggers: infer from scent profile, brand positioning, and product language.

For all other categories:
- Identify key ingredients, materials, or components from the input (prefix uncertain items with "Likely:")
- Describe function, use case, and key differentiators based on the input
- Identify the target buyer persona from context in the input
- Use domain expertise to fill gaps when there is a strong logical signal

---
STEP 3 — OUTPUT
Return ONLY valid JSON. No markdown. No code fences. No extra text.

The JSON must have EXACTLY these fields:

{{
  "category": "detected from content",
  "title": "refined version of original title — must reference the actual product, not a generic phrase",
  "clean_summary": "rewritten version of original text — NOT new ideas. 2–3 sentence expert-level summary that references specific elements from the input",
  "extracted_insights": {{
    "key_features": ["feature 1 from input", "feature 2 from input", "feature 3 from input"],
    "benefits": ["benefit 1 from input", "benefit 2", "benefit 3", "benefit 4", "benefit 5"],
    "positioning": "precise target audience and market positioning — based on input context, not generic"
  }},
  "fragrance_analysis": {{
    "scent_family": "accurate scent family — empty string for non-fragrance",
    "top_notes": ["only notes mentioned or strongly implied by the input"],
    "heart_notes": ["only notes mentioned or strongly implied by the input"],
    "base_notes": ["only notes mentioned or strongly implied by the input"],
    "scent_evolution": "how the scent evolves — empty string for non-fragrance or if not supported by input",
    "projection": "soft / moderate / strong based on input clues — empty string for non-fragrance",
    "longevity": "short / moderate / long-lasting based on input clues — empty string for non-fragrance",
    "best_season": "based on composition clues — empty string for non-fragrance",
    "best_occasions": ["occasions based on input context — empty array for non-fragrance"],
    "emotional_triggers": ["specific emotions from input — empty array for non-fragrance"]
  }},
  "technical_analysis": "expert explanation of composition or product structure — based on input content, not invented. Must read like an analyst's breakdown, not marketing copy",
  "luxury_upgrade_text": "same meaning as the input, but elevated to high-end brand level — Tom Ford / Dior caliber. Must reference actual elements from the input. NO generic marketing filler.",
  "long_description": "<p>...</p><ul><li><strong>Label:</strong> explanation</li>...</ul><p>...</p>",
  "meta_description": "under 155 characters, buyer-intent focused, based on input content",
  "keywords": "comma-separated buyer-intent keywords derived from input"
}}

long_description HTML structure (STRICT):
<p>Opening hook paragraph — must reference specific product elements from the input, not generic praise.</p>
<p>Second paragraph that addresses the buyer's desire and positions this product using content from the input.</p>
<ul>
<li><strong>Composition:</strong> Description of product structure / note structure based on input.</li>
<li><strong>Projection & Longevity:</strong> Performance characteristics based on input clues.</li>
<li><strong>Best For:</strong> Specific occasions and seasons based on input context.</li>
<li><strong>Scent Character:</strong> The emotional and sensory signature based on input.</li>
<li><strong>Who Wears This:</strong> The target persona based on input context.</li>
</ul>
<p>Closing paragraph — expert recommendation, not generic call to action.</p>

RULES:
- You are an analyst and domain expert — extract, elevate, and infer with expertise
- Be specific to THIS product — never produce content that could apply to any product
- DO NOT fully invent details with no basis — but DO use domain expertise to fill gaps when logically supported
- Prefix inferred items with "Likely" or "Likely:" (e.g. "Likely woody-oriental", "Likely: bergamot")
- Do NOT use vague filler words or generic phrases: "luxurious fragrance", "captivating scent", "timeless elegance", "ultimate", "premium", "amazing"
- Do NOT repeat "not specified", "unavailable", "cannot be determined", or similar phrases more than once total — if something is truly unknown, mention it briefly once then move on
- If output contains zero insight, it is wrong
- If output is fully invented, it is wrong
- Balance accuracy with expert reasoning
- long_description must use only <p>, <ul>, <li>, <strong> tags and contain exactly 5 <li> items
- fragrance_analysis notes must use empty arrays for non-fragrance products
- fragrance_analysis occasions and emotional_triggers must use empty arrays for non-fragrance products
- fragrance_analysis scent_evolution, best_season must use empty strings for non-fragrance products
- luxury_upgrade_text must reference actual elements from the input — not generic marketing text
- emotional_triggers must cite specific emotions (e.g., dominance, seduction, power, confidence) — not generic adjectives
- technical_analysis must discuss actual materials, accords, or product details from the input — not vague descriptions
- Return ONLY valid JSON — no markdown, no code fences, no extra text
"""

    for _ in range(MAX_AI_GENERATION_RETRIES):
        response = _client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a fragrance chemist, perfumer, and luxury product analyst — also a domain expert. "
                        "You must strictly respect the provided product content. "
                        "If information is explicitly present, use it exactly. "
                        "If information is missing, infer only when there is a strong logical signal — use realistic domain knowledge, not fantasy. "
                        "If something truly cannot be inferred, say so briefly once, not repeatedly. "
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

        try:
            data = json.loads(cleaned)
        except (ValueError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        # Flatten nested AI response to the flat field names used by
        # downstream consumers (API routes, frontend template, router).
        insights = data.pop("extracted_insights", None) or {}
        frag = data.pop("fragrance_analysis", None) or {}

        # clean_summary → short_summary
        if "clean_summary" in data and "short_summary" not in data:
            data["short_summary"] = data.pop("clean_summary")

        # luxury_upgrade_text → luxury_description
        if "luxury_upgrade_text" in data and "luxury_description" not in data:
            data["luxury_description"] = data.pop("luxury_upgrade_text")

        # extracted_insights → flat fields (setdefault: AI flat fields win
        # if present, otherwise fall back to the nested structure).
        data.setdefault("key_benefits", insights.get("benefits", []))
        data.setdefault("selling_points", insights.get("key_features", []))
        data.setdefault("target_audience", insights.get("positioning", ""))

        # fragrance_analysis → flat fields
        if frag:
            data.setdefault("scent_family", frag.get("scent_family", ""))
            data.setdefault("fragrance_notes", {
                "top": frag.get("top_notes", []),
                "heart": frag.get("heart_notes", []),
                "base": frag.get("base_notes", []),
            })
            data.setdefault("scent_evolution", frag.get("scent_evolution", ""))
            data.setdefault("projection", frag.get("projection", ""))
            data.setdefault("longevity", frag.get("longevity", ""))
            data.setdefault("best_season", frag.get("best_season", ""))
            data.setdefault("best_occasions", frag.get("best_occasions", []))
            data.setdefault("emotional_triggers", frag.get("emotional_triggers", []))

        return data

    return {
        "category": "",
        "title": idea,
        "short_summary": "",
        "technical_analysis": "",
        "target_audience": "",
        "scent_family": "",
        "fragrance_notes": {"top": [], "heart": [], "base": []},
        "scent_evolution": "",
        "projection": "",
        "longevity": "",
        "best_season": "",
        "best_occasions": [],
        "emotional_triggers": [],
        "key_benefits": [],
        "selling_points": [],
        "luxury_description": "",
        "long_description": f"<p>{idea}</p>",
        "meta_description": "",
        "keywords": idea,
    }


# ---------------------------------------------------------------------------
# Fragrance detection helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Product optimisation router
# ---------------------------------------------------------------------------

def optimize_product_router(product, lang="en"):
    is_fragrance = looks_like_fragrance(product)
    print("FRAGRANCE DETECTED:", is_fragrance, product.get("title", ""))

    if is_fragrance:
        title = product.get("title", "")
        brand = product.get("vendor", "")
        product_type = product.get("product_type", "")
        tags = product.get("tags", "")
        body_html = product.get("body_html", "")

        idea = (
            f"[SPECIFIC FRAGRANCE PRODUCT — NOT A GENERIC IDEA]\n"
            f"This is a real fragrance product currently listed for sale. "
            f"Analyze it as a specific, existing product — do NOT generate generic perfume content.\n"
            f"\n"
            f"Full Product Title: {title}\n"
            f"Brand / House: {brand}\n"
            f"Product Type: {product_type}\n"
            f"Tags: {tags}\n"
            f"Product Description / Body HTML:\n{body_html}"
        ).strip()

        result = analyze_product_with_ai(idea)
        print("FRAGRANCE ROUTER RESULT:", result)

        result.setdefault("category", "perfume / fragrance")
        result.setdefault("title", product.get("title", ""))
        result.setdefault("short_summary", "")
        result.setdefault("technical_analysis", "")
        result.setdefault("target_audience", "")
        result.setdefault("scent_family", "")
        result.setdefault("fragrance_notes", {"top": [], "heart": [], "base": []})
        result.setdefault("scent_evolution", "")
        result.setdefault("projection", "")
        result.setdefault("longevity", "")
        result.setdefault("best_season", "")
        result.setdefault("best_occasions", [])
        result.setdefault("emotional_triggers", [])
        result.setdefault("key_benefits", [])
        result.setdefault("selling_points", [])
        result.setdefault("luxury_description", "")
        result.setdefault("long_description", "")
        result.setdefault("meta_description", "")
        result.setdefault("keywords", "")
        result["is_fragrance"] = True
        return result

    result = build_title_and_description_with_ai(product, lang=lang)
    result["is_fragrance"] = False
    return result
