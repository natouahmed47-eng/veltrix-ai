import os
import json
import re
import requests
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =========================
# GET SHOPIFY TOKEN (SAFE)
# =========================
def get_shopify_token():
    # 1) from ENV
    env_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    if env_token:
        return env_token.strip()

    # 2) from Render Secret Files
    possible_paths = [
        "/etc/secrets/shopify.json",
        "/etc/secrets/SHOPIFY_ACCESS_TOKEN",
        "/etc/secrets/shopify_token.json",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()

                if not content:
                    continue

                # JSON file
                if content.startswith("{"):
                    data = json.loads(content)
                    token = data.get("access_token")
                    if token:
                        return token.strip()
                else:
                    # plain text token
                    return content.strip()
            except Exception:
                pass

    return None


# =========================
# HOME
# =========================
@app.route("/")
def home():
    return """
    <h1>VELTRIX AI</h1>
    <p>System is running.</p>
    """


# =========================
# HEALTH CHECK
# =========================
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "openai_ready": bool(OPENAI_API_KEY),
        "shopify_token_ready": bool(get_shopify_token())
    })


# =========================
# FETCH PRODUCTS
# =========================
@app.route("/products", methods=["GET"])
def get_products():
    shop = request.args.get("shop", DEFAULT_SHOP).strip()
    token = get_shopify_token()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not token:
        return jsonify({"error": "Missing Shopify token"}), 500

    url = f"https://{shop}/admin/api/2024-01/products.json"

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500


# =========================
# AI DESCRIPTION (CLEAN)
# =========================
@app.route("/ai/product-description", methods=["POST"])
def generate_description():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.json

    product_name = data.get("product_name", "")
    brand = data.get("brand", "")
    category = data.get("category", "")
    audience = data.get("audience", "")
    tone = data.get("tone", "professional")
    features = data.get("features", "")

    system_prompt = """You are a high-converting e-commerce copywriter.

Write product descriptions that drive immediate purchase decisions.

Rules:
- No markdown symbols (#, *, **)
- No poetic language
- No exaggeration
- No weak words
- Be direct, realistic, persuasive

Structure:
Strong headline
Short convincing paragraph
Clear benefits
Strong closing line

Output must be clean plain text only.
"""

    user_prompt = f"""
Product: {product_name}
Brand: {brand}
Category: {category}
Audience: {audience}
Tone: {tone}
Key features: {features}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )

        text = response.choices[0].message.content.strip()

        # REMOVE MARKDOWN SYMBOLS
        clean_text = re.sub(r"[#*]", "", text)

        return jsonify({
            "success": True,
            "description": clean_text
        })

    except Exception as e:
        return jsonify({
            "error": "AI generation failed",
            "details": str(e)
        }), 500


# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
                

