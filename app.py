import os
import json
import requests
from flask import Flask, request, redirect, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# =========================
# الإعدادات
# =========================
DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"
TOKEN_STORE_FILE = "shopify_tokens.json"


# =========================
# أدوات مساعدة
# =========================
def read_secret_file(filename: str):
    path = f"/etc/secrets/{filename}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def get_secret(name: str):
    return os.environ.get(name) or read_secret_file(name)


def load_token_store():
    if os.path.exists(TOKEN_STORE_FILE):
        try:
            with open(TOKEN_STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_token_store(data: dict):
    with open(TOKEN_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_shop_token(shop: str, token: str):
    data = load_token_store()
    data[shop] = token
    save_token_store(data)


def get_shop_token(shop: str):
    data = load_token_store()
    return data.get(shop)


def get_active_token(shop: str):
    token = get_shop_token(shop)
    if token:
        return token
    return get_secret("SHOPIFY_ACCESS_TOKEN")


SHOPIFY_API_KEY = get_secret("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = get_secret("SHOPIFY_API_SECRET")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =========================
# الصفحة الرئيسية
# =========================
@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"


# =========================
# فحص سريع
# =========================
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "shopify_api_key_exists": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_exists": bool(SHOPIFY_API_SECRET),
        "openai_api_key_exists": bool(OPENAI_API_KEY),
    })


# =========================
# بدء تثبيت التطبيق
# =========================
@app.route("/auth")
def auth():
    shop = request.args.get("shop", DEFAULT_SHOP)

    if not shop:
        return "Missing shop", 400

    if not SHOPIFY_API_KEY:
        return "Missing SHOPIFY_API_KEY", 500

    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"
    scope = "read_products,write_products,read_orders,write_orders,read_customers"

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )

    return redirect(install_url)


# =========================
# callback بعد التثبيت
# =========================
@app.route("/auth/callback")
def callback():
    shop = request.args.get("shop")
    code = request.args.get("code")

    if not shop or not code:
        return "Missing shop or code", 400

    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        return "Missing Shopify API credentials", 500

    token_url = f"https://{shop}/admin/oauth/access_token"

    response = requests.post(
        token_url,
        json={
            "client_id": SHOPIFY_API_KEY,
            "client_secret": SHOPIFY_API_SECRET,
            "code": code,
        },
        timeout=30,
    )

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code,
            "text": response.text
        }), 500

    if response.status_code != 200:
        return jsonify({
            "error": "Failed to get access token",
            "status_code": response.status_code,
            "shopify_response": data
        }), 400

    access_token = data.get("access_token")
    scope = data.get("scope")

    if not access_token:
        return jsonify({
            "error": "Access token missing",
            "shopify_response": data
        }), 400

    save_shop_token(shop, access_token)

    return jsonify({
        "message": "App installed successfully ✅",
        "shop": shop,
        "scope": scope,
        "access_token": access_token
    })


# =========================
# جلب المنتجات
# =========================
@app.route("/products", methods=["GET"])
def get_products():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)

    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    url = f"https://{shop}/admin/api/2025-10/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code,
            "text": response.text
        }), 500

    return jsonify(data), response.status_code


# =========================
# إنشاء منتج جديد
# =========================
@app.route("/products/create", methods=["POST"])
def create_product():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)

    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    data = request.get_json(force=True) or {}

    title = data.get("title", "New Product")
    body_html = data.get("body_html", "<strong>Created by Veltrix AI</strong>")
    vendor = data.get("vendor", "Veltrix AI")
    product_type = data.get("product_type", "AI Product")

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": vendor,
            "product_type": product_type,
        }
    }

    url = f"https://{shop}/admin/api/2025-10/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    try:
        result = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code,
            "text": response.text
        }), 500

    return jsonify(result), response.status_code


# =========================
# عرض التوكن المحفوظ
# =========================
@app.route("/token", methods=["GET"])
def show_token():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)

    if not token:
        return jsonify({"error": "No token found for this shop"}), 404

    return jsonify({
        "shop": shop,
        "access_token": token
    })


# =========================
# AI: توليد وصف منتج
# =========================
@app.route("/ai/product-description", methods=["POST"])
def ai_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(force=True) or {}

    title = data.get("title")
    product_type = data.get("product_type", "")
    audience = data.get("audience", "")
    tone = data.get("tone", "professional")
    language = data.get("language", "ar")

    if not title:
        return jsonify({"error": "Missing title"}), 400

    prompt = f"""
اكتب وصف منتج احترافي عالي التحويل لمتجر Shopify.

اسم المنتج: {title}
نوع المنتج: {product_type}
الجمهور المستهدف: {audience}
النبرة: {tone}
اللغة: {language}

المطلوب:
- عنوان تسويقي قصير
- وصف احترافي مقنع
- 5 مزايا رئيسية
- دعوة واضحة للشراء
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "أنت خبير كتابة وصف منتجات احترافي لمتاجر التجارة الإلكترونية."},
            {"role": "user", "content": prompt}
        ]
    )

    content = response.choices[0].message.content

    return jsonify({
        "title": title,
        "result": content
    })


# =========================
# AI + Shopify: تحديث وصف منتج
# =========================
@app.route("/ai/update-product-description", methods=["POST"])
def ai_update_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(force=True) or {}

    shop = data.get("shop", DEFAULT_SHOP)
    product_id = data.get("product_id")
    title = data.get("title")
    product_type = data.get("product_type", "")
    audience = data.get("audience", "")
    tone = data.get("tone", "professional")
    language = data.get("language", "ar")

    if not product_id or not title:
        return jsonify({"error": "Missing product_id or title"}), 400

    token = get_active_token(shop)
    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    prompt = f"""
اكتب وصف منتج احترافي عالي التحويل لمتجر Shopify.

اسم المنتج: {title}
نوع المنتج: {product_type}
الجمهور المستهدف: {audience}
النبرة: {tone}
اللغة: {language}

المطلوب:
- عنوان تسويقي قصير
- وصف احترافي مقنع
- 5 مزايا رئيسية
- دعوة واضحة للشراء
"""

    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "أنت خبير كتابة وصف منتجات احترافي لمتاجر التجارة الإلكترونية."},
            {"role": "user", "content": prompt}
        ]
    )

    generated_description = ai_response.choices[0].message.content

    url = f"https://{shop}/admin/api/2025-10/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    payload = {
        "product": {
            "id": int(product_id),
            "body_html": generated_description
        }
    }

    response = requests.put(url, headers=headers, json=payload, timeout=30)

    try:
        result = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code,
            "text": response.text
        }), 500

    return jsonify({
        "message": "Product description updated successfully ✅",
        "generated_description": generated_description,
        "shopify_result": result
    }), response.status_code


# =========================
# تشغيل التطبيق
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
