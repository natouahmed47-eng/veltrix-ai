import os
import requests
from flask import Flask, request, redirect, jsonify


# 👇 ضع الكود هنا مباشرة
def read_secret_file(filename: str):
    path = f"/etc/secrets/{filename}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def get_secret(name: str):
    return os.environ.get(name) or read_secret_file(name)

SHOPIFY_ACCESS_TOKEN = get_secret("SHOPIFY_ACCESS_TOKEN")


# 👇 بعدها يبدأ التطبيق
app = Flask(__name__)
