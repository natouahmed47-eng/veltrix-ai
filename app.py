import os
import json
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

TOKEN_FILE = "shopify_token.json"


def save_shop_token(shop, access_token):
    data = {
        "shop": shop,
        "access_token": access_token
    }
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_shop_token():
    if not os.path.exists(TOKEN_FILE):
        return None, None

    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("shop"), data.get("access_token")


@app.route("/install")
def install():
    shop = request.args.get("shop")
    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    api_key = os.getenv("SHOPIFY_API_KEY")
    redirect_uri = os.getenv("SHOPIFY_REDIRECT_URI")
    scopes = "read_products,write_products"

    if not api_key or not redirect_uri:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_REDIRECT_URI"}), 500

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={api_key}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
    )

    return redirect(install_url)


@app.route("/callback")
def callback():
    shop = request.args.get("shop")
    code = request.args.get("code")

    if not shop or not code:
        return jsonify({"error": "Missing shop or code"}), 400

    api_key = os.getenv("SHOPIFY_API_KEY")
    api_secret = os.getenv("SHOPIFY_API_SECRET")

    if not api_key or not api_secret:
        return jsonify({"error": "Missing SHOPIFY_API_KEY or SHOPIFY_API_SECRET"}), 500

    token_url = f"https://{shop}/admin/oauth/access_token"

    response = requests.post(
        token_url,
        json={
            "client_id": api_key,
            "client_secret": api_secret,
            "code": code
        },
        timeout=30
    )

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "text": response.text
        }), 500

    access_token = data.get("access_token")
    if not access_token:
        return jsonify({
            "error": "No access token returned",
            "shopify_response": data
        }), 500

    # نحفظ التوكن الجديد بدل القديم
    save_shop_token(shop, access_token)

    return jsonify({
        "message": "App installed successfully",
        "shop": shop
    })


@app.route("/health")
def health():
    saved_shop, saved_token = load_shop_token()
    return jsonify({
        "status": "ok",
        "saved_shop": saved_shop,
        "shopify_token_ready": bool(saved_token)
    })


@app.route("/products")
def products():
    shop_param = request.args.get("shop")
    saved_shop, access_token = load_shop_token()

    shop = shop_param or saved_shop

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not access_token:
        return jsonify({"error": "No saved Shopify token"}), 500

    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers, timeout=30)

    try:
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid Shopify response",
            "text": response.text
        }), 500

    return jsonify(data), response.status_code


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
