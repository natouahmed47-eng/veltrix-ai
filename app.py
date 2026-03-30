import os
import requests
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

SHOP = "a-n-t-965.myshopify.com"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN_HERE"


@app.route("/")
def home():
    return "Veltrix AI Shopify Products API 🚀"


@app.route("/products", methods=["GET"])
def get_products():
    url = f"https://{SHOP}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    return jsonify(response.json()), response.status_code


@app.route("/products/create", methods=["POST"])
def create_product():
    data = request.get_json(silent=True) or {}

    title = data.get("title", "New Product")
    body_html = data.get("body_html", "<strong>Created by Veltrix AI</strong>")
    vendor = data.get("vendor", "Veltrix AI")
    product_type = data.get("product_type", "General")

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": vendor,
            "product_type": product_type,
        }
    }

    url = f"https://{SHOP}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    return jsonify(response.json()), response.status_code


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
