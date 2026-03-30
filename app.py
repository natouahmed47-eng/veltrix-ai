import requests
from flask import request, redirect
import osfrom flask import Flask, request, redirect, jsonify
import os
import 
requests

app = Flask(__name__)

@app.route("/")
def home():
    return "Veltrix AI Shopify App 🚀"

@app.route("/auth")
def auth():
    shop = request.args.get("shop")

    if not shop:
        return "Missing shop", 400

    api_key = os.environ.get("SHOPIFY_API_KEY")
    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"
    scope = "read_products,write_products,read_orders,write_orders"

    install_url = f"https://{shop}/admin/oauth/authorize?client_id={api_key}&scope={scope}&redirect_uri={redirect_uri}"

    return redirect(install_url)

@app.route("/auth/callback")
def callback():
    shop = request.args.get("shop")
    code = request.args.get("code")

    api_key = os.environ.get("SHOPIFY_API_KEY")
    api_secret = os.environ.get("SHOPIFY_API_SECRET")

    url = f"https://{shop}/admin/oauth/access_token"

    response = requests.post(url, json={
        "client_id": api_key,
        "client_secret": api_secret,
        "code": code
    })

    return response.json()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
