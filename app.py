import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# قراءة التوكن من Render (secret file)
def read_secret_file(filename):
    path = f"/etc/secrets/{filename}"
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return None

def get_secret(name):
    return os.environ.get(name) or read_secret_file(name)

@app.route("/")
def home():
    return "Shopify App Running 🚀"

@app.route("/products")
def get_products():
    token = get_secret("SHOPIFY_ACCESS_TOKEN")

    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    shop = "a-n-t-965.myshopify.com"

    url = f"https://{shop}/admin/api/2023-10/products.json"

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)

    return jsonify(response.json()), response.status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
