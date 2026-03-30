import os
import requests
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

# =========================
# الإعدادات الأساسية
# =========================
SHOP = "a-n-t-965.myshopify.com"

# ضع التوكن هنا مؤقتًا للتجربة فقط
ACCESS_TOKEN = "PUT_YOUR_SHOPIFY_ACCESS_TOKEN_HERE"

# مفاتيح Shopify للتثبيت
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")


# =========================
# الصفحة الرئيسية
# =========================
@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"


# =========================
# بدء تثبيت التطبيق
# =========================
@app.route("/auth")
def auth():
    shop = request.args.get("shop")

    if not shop:
        return "Missing shop", 400

    if not SHOPIFY_API_KEY:
        return "Missing SHOPIFY_API_KEY", 500

    scope = "read_products,write_products,read_orders,write_orders,read_customers"
    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )

    return redirect(install_url)


# =========================
# الرجوع من Shopify بعد التثبيت
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

    data = response.json()

    return jsonify({
        "message": "App installed successfully ✅",
        "data": data
    })


# =========================
# جلب المنتجات
# =========================
@app.route("/products", methods=["GET"])
def get_products():
    if not ACCESS_TOKEN or ACCESS_TOKEN == "PUT_YOUR_SHOPIFY_ACCESS_TOKEN_HERE":
        return jsonify({"error": "Missing Shopify access token"}), 500

    url = f"https://{SHOP}/admin/api/2025-10/products.json"
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    return jsonify(response.json()), response.status_code


# =========================
# إنشاء منتج جديد
# =========================
@app.route("/products/create", methods=["POST"])
def create_product():
    if not ACCESS_TOKEN or ACCESS_TOKEN == "PUT_YOUR_SHOPIFY_ACCESS_TOKEN_HERE":
        return jsonify({"error": "Missing Shopify access token"}), 500

    data = request.get_json(silent=True) or {}

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

    url = f"https://{SHOP}/admin/api/2025-10/products.json"
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    return jsonify(response.json()), response.status_code


# =========================
# تشغيل السيرفر
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
