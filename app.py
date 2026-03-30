from flask import Flask, request, redirect
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

    redirect_uri = "https://veltrix-ai-fx5c.onrender.com/auth/callback"

    install_url = f"https://{shop}/admin/oauth/authorize?client_id={SHOPIFY_API_KEY}&scope=read_products,write_products,read_orders&redirect_uri={redirect_uri}"

    return redirect(install_url)

@app.route("/auth/callback")
def callback():
    return "Shopify connected successfully ✅"
