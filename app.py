import os
import json
import re
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"


def get_shopify_token():
    env_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    if env_token:
        return env_token.strip()

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

                if content.startswith("{"):
                    data = json.loads(content)
                    token = data.get("access_token")
                    if token:
                        return token.strip()
                else:
                    return content.strip()
            except Exception:
                pass

    return None


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SHOPIFY_TOKEN = get_shopify_token()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


@app.route("/")
def home():
    return """
    <h1>VELTRIX AI</h1>
    <p>System is running successfully.</p>
    """


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "openai_ready": bool(OPENAI_API_KEY),
        "shopify_token_ready": bool(get_shopify_token())
    })


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
        data = response.json()
        return jsonify(data), response.status_code
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500


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

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )

        raw_text = response.choices[0].message.content.strip()
        clean_text = re.sub(r"[#*]", "", raw_text)

        return jsonify({
            "success": True,
            "description": clean_text
        }), 200

    except Exception as e:
        return jsonify({
            "error": "AI generation failed",
            "details": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
