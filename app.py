import os
import requests
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

# الصفحة الرئيسية
@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"


# بدء التثبيت (OAuth)
@app.route("/auth")
def auth():
    shop = request.args.get("shop")

    if not shop:
        return "Missing shop", 400

    api_key = os.environ.get("SHOPIFY_API_KEY")

    if not api_key:
        return "Missing SHOPIFY_API_KEY", 500

    scope = "read_products,write_products,read_orders"
    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={api_key}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )

    return redirect(install_url)


# callback بعد التثبيت
@app.route("/auth/callback")
def callback():
    shop = request.args.get("shop")
    code = request.args.get("code")

    if not shop or not code:
        return "Missing shop or code", 400

    api_key = os.environ.get("SHOPIFY_API_KEY")
    api_secret = os.environ.get("SHOPIFY_API_SECRET")

    if not api_key or not api_secret:
        return "Missing API credentials", 500

    url = f"https://{shop}/admin/oauth/access_token"

    response = requests.post(url, json={
        "client_id": api_key,
        "client_secret": api_secret,
        "code": code
    })

    data = response.json()

    return jsonify(data)


# تشغيل السيرفر
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
