from flask import Flask, request, redirect, jsonify
import os
import requests

app = Flask(__name__)

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")

@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"

@app.route("/auth")
def auth():
    shop = request.args.get("shop")
    if not shop:
        return "Missing shop", 400

    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"
    scope = "read_products,write_products,read_orders,write_orders"

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )
    return redirect(install_url)

@app.route("/auth/callback")
def callback():
    shop = request.args.get("shop")
    code = request.args.get("code")

    if not shop or not code:
        return "Missing shop or code", 400

    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }

    response = requests.post(token_url, json=payload)
    data = response.json()

    access_token = data.get("access_token")
    if not access_token:
        return jsonify(data), 400

    return f"Shopify connected successfully ✅ Token: {access_token[:12]}..."
