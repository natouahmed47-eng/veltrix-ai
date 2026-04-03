import json
import os
import re
from typing import Optional, Tuple

import requests
from flask import Flask, jsonify, redirect, request
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"
TOKEN_FILE = "/var/data/shopify_token.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_REDIRECT_URI = os.getenv("SHOPIFY_REDIRECT_URI")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def save_shop_token(shop: str, access_token: str) -> None:
    payload = {
        "shop": shop,
        "access_token": access_token
    }
    import os
import json

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return None

    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


def load_shop_token() -> Tuple[Optional[str], Optional[str]]:
    if not os.path.exists(TOKEN_FILE):
        return None, None

    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        shop = data.get("shop")
        access_token = data.get("access_token")
        return shop, access_token
    except Exception:
        return None, None


def get_saved_shop() -> Optional[str]:
    shop, _ = load_shop_token()
    return shop


def get_saved_token() -> Optional[str]:
    _, token = load_shop_token()
    return token


def sanitize_plain_text(text: str) -> str:
    clean = re.sub(r"[#*`]", "", text)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def build_description_with_ai(product: dict) -> str:
    if not client:
        raise RuntimeError("OpenAI is not configured")

    title = (product.get("title") or "").strip()
    body_html = (product.get("body_html") or "").strip()
    vendor = (product.get("vendor") or "").strip()
    product_type = (product.get("product_type") or "").strip()
    tags = (product.get("tags") or "").strip()

    image_alt_text = ""
    images = product.get("images") or []
    if images and isinstance(images, list):
        first_image = images[0] or {}
        image_alt_text = (first_image.get("alt") or "").strip()

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
Image alt text: {image_alt_text}

Write a better final product description in English only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )

    raw_text = response.choices[0].message.content if response.choices else ""
    clean_text = sanitize_plain_text(raw_text or "")
    html_text = clean_text.replace("\n", "<br>")
    return html_text


def shopify_get_products(shop: str, token: str, limit: Optional[int] = None) -> requests.Response:
    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    params = {}
    if limit:
        params["limit"] = limit
    return requests.get(url, headers=headers, params=params, timeout=30)


def shopify_update_product_description(shop: str, token: str, product_id: int, description_html: str) -> requests.Response:
    url = f"https://{shop}/admin/api/2024-01/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    payload = {
        "product": {
            "id": int(product_id),
            "body_html": description_html
        }
    }
    return requests.put(url, headers=headers, json=payload, timeout=30)


@app.route("/")
def home():
    return """
    <h1>VELTRIX AI</h1>
    <p>System is running successfully.</p>
    <p>Available routes:</p>
    <ul>
      <li>/health</li>
      <li>/install?shop=your-store.myshopify.com</li>
      <li>/products</li>
      <li>/products?shop=your-store.myshopify.com</li>
      <li>/ai/product-description</li>
      <li>/optimize-all-products</li>
    </ul>
    """


@app.route("/health")
def health():
    saved_shop, saved_token = load_shop_token()
    return jsonify({
        "status": "ok",
        "openai_ready": bool(OPENAI_API_KEY),
        "shopify_api_key_ready": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_ready": bool(SHOPIFY_API_SECRET),
        "shopify_redirect_ready": bool(SHOPIFY_REDIRECT_URI),
        "saved_shop": saved_shop,
        "shopify_token_ready": bool(saved_token)
    })


@app.route("/install")
def install():
    shop = (request.args.get("shop") or "").strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not SHOPIFY_API_KEY or not SHOPIFY_REDIRECT_URI:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_REDIRECT_URI"}), 500

    scopes = "read_products,write_products"
    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={scopes}"
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

    try:
        response = requests.post(
            token_url,
            json={
                "client_id": SHOPIFY_API_KEY,
                "client_secret": SHOPIFY_API_SECRET,
                "code": code
            },
            timeout=30
        )
    except Exception as e:
        return jsonify({
            "error": "Failed to contact Shopify",
            "details": str(e)
        }), 500

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "raw_text": response.text
        }), 500

    access_token = data.get("access_token")
    if not access_token:
        return jsonify({
            "error": "No access token returned",
            "shopify_response": data
        }), 500

    save_shop_token(shop, access_token)

    return jsonify({
        "message": "App installed successfully",
        "shop": shop
    })


@app.route("/products", methods=["GET"])
def get_products():
    requested_shop = (request.args.get("shop") or "").strip()
    saved_shop, token = load_shop_token()

    shop = requested_shop or saved_shop or DEFAULT_SHOP

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not token:
        return jsonify({"error": "No saved Shopify token"}), 500

    try:
        response = shopify_get_products(shop=shop, token=token)
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid Shopify response",
            "raw_text": response.text
        }), 500

    return jsonify(data), response.status_code


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

        raw_text = response.choices[0].message.content if response.choices else ""
        clean_text = sanitize_plain_text(raw_text or "")

        return jsonify({
            "success": True,
            "description": clean_text
        }), 200

    except Exception as e:
        return jsonify({
            "error": "AI generation failed",
            "details": str(e)
        }), 500


@app.route("/optimize-all-products", methods=["GET", "POST"])
def optimize_all_products():
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500

    data = request.get_json(silent=True) or {}
    requested_shop = (data.get("shop") or request.args.get("shop") or "").strip()
    saved_shop, token = load_shop_token()

    shop = requested_shop or saved_shop or DEFAULT_SHOP

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not token:
        return jsonify({"error": "No saved Shopify token"}), 500

    try:
        limit = int(data.get("limit", 5))
    except Exception:
        limit = 5

    try:
        products_response = shopify_get_products(shop=shop, token=token, limit=limit)
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500

    try:
        products_data = products_response.json()
    except Exception:
        return jsonify({
            "error": "Invalid Shopify response",
            "raw_text": products_response.text
        }), 500

    if products_response.status_code != 200:
        return jsonify({
            "error": "Shopify fetch failed",
            "details": products_data
        }), products_response.status_code

    products = products_data.get("products", [])
    results = []

    for product in products:
        product_id = product.get("id")
        title = product.get("title", "")

        try:
            generated_description = build_description_with_ai(product)
            update_response = shopify_update_product_description(
                shop=shop,
                token=token,
                product_id=int(product_id),
                description_html=generated_description
            )

            try:
                update_data = update_response.json()
            except Exception:
                update_data = {"raw_text": update_response.text}

            results.append({
                "product_id": product_id,
                "title": title,
                "success": update_response.status_code == 200,
                "status_code": update_response.status_code,
                "generated_description": generated_description,
                "shopify_response": update_data
            })

        except Exception as e:
            results.append({
                "product_id": product_id,
                "title": title,
                "success": False,
                "error": str(e)
            })

    success_count = sum(1 for item in results if item.get("success"))

    return jsonify({
        "shop": shop,
        "total_processed": len(results),
        "success_count": success_count,
        "failed_count": len(results) - success_count,
        "results": results
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
