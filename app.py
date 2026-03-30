import os
import requests
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)


def read_secret_file(filename: str):
    path = f"/etc/secrets/{filename}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def get_secret(name: str):
    return os.environ.get(name) or read_secret_file(name)


SHOPIFY_API_KEY = get_secret("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = get_secret("SHOPIFY_API_SECRET")


@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"


@app.route("/auth")
def auth():
    shop = request.args.get("shop")

    if not shop:
        return "Missing shop parameter", 400

    if not SHOPIFY_API_KEY:
        return "SHOPIFY_API_KEY missing", 500

    scope = "read_products,write_products,read_orders,write_orders,read_customers"
    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"

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

    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        return "Shopify API credentials missing", 500

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

    return jsonify({
        "message": "App installed successfully ✅",
        "data": data
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
