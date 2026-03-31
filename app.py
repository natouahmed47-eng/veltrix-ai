import os
import json
import requests
import markdown
from flask import Flask, request, redirect, jsonify, render_template_string
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# =========================
# الإعدادات
# =========================
DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"
TOKEN_STORE_FILE = "shopify_tokens.json"
SHOPIFY_API_VERSION = "2024-01"

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# =========================
# أدوات مساعدة
# =========================
def read_secret_file(filename: str):
    path = f"/etc/secrets/{filename}"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def get_secret(name: str):
    return os.environ.get(name) or read_secret_file(name)


def normalize_token(token):
    if not token:
        return None

    token = str(token).strip()

    if "shpat_" in token:
        token = "shpat_" + token.split("shpat_")[-1]

    return token.replace('"', "").replace("'", "").strip()


# =========================
# إدارة التوكن
# =========================
def load_token_store():
    if os.path.exists(TOKEN_STORE_FILE):
        try:
            with open(TOKEN_STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_token_store(data):
    with open(TOKEN_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_shop_token(shop, token):
    token = normalize_token(token)
    data = load_token_store()
    data[shop] = token
    save_token_store(data)


def get_shop_token(shop):
    data = load_token_store()
    return normalize_token(data.get(shop))


def get_active_token(shop):
    token = get_shop_token(shop)
    if token:
        return token
    return normalize_token(get_secret("SHOPIFY_ACCESS_TOKEN"))


# =========================
# الصفحة الرئيسية
# =========================
@app.route("/")
def home():
    return dashboard()


# =========================
# فحص سريع
# =========================
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "shopify_api_key_exists": bool(SHOPIFY_API_KEY),
        "shopify_api_secret_exists": bool(SHOPIFY_API_SECRET),
        "openai_api_key_exists": bool(OPENAI_API_KEY),
    })


# =========================
# بدء تثبيت التطبيق
# =========================
@app.route("/auth")
def auth():
    shop = request.args.get("shop")
    if not shop:
        return "Missing shop parameter", 400

    if not SHOPIFY_API_KEY:
        return "Missing SHOPIFY_API_KEY", 500

    base_url = request.host_url.rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"
    scope = "read_products,write_products,read_orders,write_orders,read_customers"

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_API_KEY}"
        f"&scope={scope}"
        f"&redirect_uri={redirect_uri}"
    )

    return redirect(install_url)


# =========================
# callback بعد التثبيت
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

    access_token = normalize_token(data.get("access_token"))
    scope = data.get("scope")

    if not access_token:
        return jsonify({
            "error": "Access token missing",
            "shopify_response": data
        }), 400

    save_shop_token(shop, access_token)

    return jsonify({
        "message": "App installed successfully ✅",
        "shop": shop,
        "scope": scope,
        "access_token": access_token
    })


# =========================
# عرض التوكن
# =========================
@app.route("/api/auth/token", methods=["GET"])
def get_token_info():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)
    return jsonify({
        "shop": shop,
        "access_token": token
    })


# =========================
# جلب المنتجات
# =========================
@app.route("/products", methods=["GET"])
def get_products():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)

    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        data = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code if "response" in locals() else None,
            "text": response.text if "response" in locals() else None
        }), 500

    if response.status_code != 200:
        return jsonify({
            "error": "Shopify API error",
            "status_code": response.status_code,
            "response": data
        }), response.status_code

    return jsonify(data), 200


# =========================
# إنشاء منتج جديد
# =========================
@app.route("/products/create", methods=["POST"])
def create_product():
    shop = request.args.get("shop", DEFAULT_SHOP)
    token = get_active_token(shop)

    if not token:
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

    url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/products.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        result = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code if "response" in locals() else None,
            "text": response.text if "response" in locals() else None
        }), 500

    if response.status_code != 201:
        return jsonify({
            "error": "Failed to create product",
            "status_code": response.status_code,
            "shopify_response": result
        }), response.status_code

    return jsonify(result), 201


# =========================
# AI: توليد وصف منتج
# =========================
@app.route("/ai/product-description", methods=["POST"])
def ai_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(silent=True) or {}

    title = data.get("title")
    product_type = data.get("product_type", "")
    audience = data.get("audience", "")
    tone = data.get("tone", "professional")
    language = data.get("language", "ar")

    if not title:
        return jsonify({"error": "Missing title"}), 400

    prompt = f"""
اكتب وصف منتج احترافي عالي التحويل لمتجر Shopify.

اسم المنتج: {title}
نوع المنتج: {product_type}
الجمهور المستهدف: {audience}
النبرة: {tone}
اللغة: {language}

المطلوب:
- عنوان تسويقي قصير
- وصف احترافي مقنع
- 5 مزايا رئيسية
- دعوة واضحة للشراء
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "أنت خبير كتابة وصف منتجات احترافي لمتاجر التجارة الإلكترونية."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content if response.choices else None

        if not content:
            return jsonify({"error": "Empty AI response"}), 500

    except Exception as e:
        return jsonify({
            "error": "OpenAI request failed",
            "details": str(e)
        }), 500

    return jsonify({
        "title": title,
        "result": content
    })


# =========================
# AI + Shopify: تحديث وصف منتج
# =========================
@app.route("/ai/update-product-description", methods=["POST"])
def ai_update_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(silent=True) or {}

    shop = data.get("shop", DEFAULT_SHOP)
    product_id = data.get("product_id")
    title = data.get("title")
    product_type = data.get("product_type", "")
    audience = data.get("audience", "")
    tone = data.get("tone", "professional")
    language = data.get("language", "ar")

    if not product_id or not title:
        return jsonify({"error": "Missing product_id or title"}), 400

    token = get_active_token(shop)
    if not token:
        return jsonify({"error": "Missing Shopify access token"}), 500

    prompt = f"""
اكتب وصف منتج احترافي عالي التحويل لمتجر Shopify.

اسم المنتج: {title}
نوع المنتج: {product_type}
الجمهور المستهدف: {audience}
النبرة: {tone}
اللغة: {language}

المطلوب:
- عنوان تسويقي قصير
- وصف احترافي مقنع
- 5 مزايا رئيسية
- دعوة واضحة للشراء
"""

    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "أنت خبير كتابة وصف منتجات احترافي لمتاجر التجارة الإلكترونية."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        raw_description = ai_response.choices[0].message.content
        generated_description = markdown.markdown(raw_description)

    except Exception as e:
        return jsonify({
            "error": "AI generation failed",
            "details": str(e)
        }), 500

    url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    payload = {
        "product": {
            "id": int(product_id),
            "body_html": generated_description
        }
    }

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=30)
        result = response.json()
    except Exception:
        return jsonify({
            "error": "Invalid response from Shopify",
            "status_code": response.status_code if "response" in locals() else None,
            "text": response.text if "response" in locals() else None
        }), 500

    if response.status_code != 200:
        return jsonify({
            "error": "Failed to update product",
            "status_code": response.status_code,
            "shopify_result": result
        }), response.status_code

    return jsonify({
        "message": "Product description updated successfully ✅",
        "generated_description": generated_description,
        "shopify_result": result
    }), 200


# =========================
# Dashboard
# =========================
@app.route("/dashboard", methods=["GET"])
def dashboard():
    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>VELTRIX AI Dashboard</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 900px;
                margin: auto;
            }
            .card {
                background: #1e293b;
                padding: 20px;
                border-radius: 16px;
                margin-bottom: 20px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            }
            input, textarea, button, select {
                width: 100%;
                padding: 12px;
                margin-top: 10px;
                margin-bottom: 10px;
                border-radius: 10px;
                border: none;
                font-size: 16px;
                box-sizing: border-box;
            }
            input, textarea, select {
                background: #334155;
                color: white;
            }
            button {
                background: #22c55e;
                color: white;
                cursor: pointer;
                font-weight: bold;
            }
            button:hover {
                background: #16a34a;
            }
            h1, h2 {
                margin-top: 0;
            }
            .small {
                color: #cbd5e1;
                font-size: 14px;
            }
            .result-box {
                white-space: pre-wrap;
                word-wrap: break-word;
                background: #0f172a;
                padding: 12px;
                border-radius: 10px;
                overflow-x: auto;
                min-height: 60px;
            }
            .product-card {
                background: #020617;
                padding: 15px;
                margin-bottom: 15px;
                border-radius: 12px;
            }
            .product-card img {
                width: 100%;
                border-radius: 10px;
                margin-bottom: 10px;
            }
            .muted {
                color: #94a3b8;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>VELTRIX AI</h1>
                <p class="small">لوحة تحكم لتوليد وتحديث أوصاف المنتجات بالذكاء الاصطناعي</p>
            </div>

            <div class="card">
                <h2>1) جلب المنتجات</h2>
                <input type="text" id="shop" value="cg1ypm-rd.myshopify.com" placeholder="اسم المتجر"/>
                <button type="button" onclick="loadProducts()">جلب المنتجات</button>
                <div id="products_result" class="result-box">لم يتم تحميل المنتجات بعد.</div>
            </div>

            <div class="card">
                <h2>2) توليد وصف بالذكاء الاصطناعي</h2>
                <input type="text" id="title" placeholder="اسم المنتج"/>
                <input type="text" id="product_type" placeholder="نوع المنتج"/>
                <input type="text" id="audience" placeholder="الجمهور المستهدف"/>
                <input type="text" id="tone" value="احترافي" placeholder="النبرة"/>
                <input type="text" id="language" value="ar" placeholder="اللغة"/>
                <button type="button" onclick="generateDescription()">توليد الوصف</button>
                <div id="ai_result" class="result-box">لم يتم توليد وصف بعد.</div>
            </div>

            <div class="card">
                <h2>3) تحديث وصف المنتج في Shopify</h2>
                <input type="text" id="product_id" placeholder="Product ID"/>
                <button type="button" onclick="updateDescription()">تحديث المنتج</button>
                <div id="update_result" class="result-box">لم يتم تحديث أي منتج بعد.</div>
            </div>
        </div>

        <script>
            function selectProduct(id, title) {
                document.getElementById("product_id").value = id;
                document.getElementById("title").value = title;
                alert("تم اختيار المنتج: " + title);
            }

            async function loadProducts() {
                const shop = document.getElementById("shop").value;
                const container = document.getElementById("products_result");
                container.innerHTML = "جاري تحميل المنتجات...";

                try {
                    const res = await fetch("/products?shop=" + encodeURIComponent(shop));
                    const data = await res.json();

                    if (!res.ok) {
                        container.textContent = "خطأ: " + JSON.stringify(data, null, 2);
                        return;
                    }

                    if (!data.products || data.products.length === 0) {
                        container.textContent = "لا توجد منتجات.";
                        return;
                    }

                    let html = "";

                    data.products.forEach(product => {
                        const image = product.images && product.images.length > 0
                            ? product.images[0].src
                            : "";

                        const cleanDescription = product.body_html || "لا يوجد وصف";
                            
                            

                        const safeTitle = String(product.title || "").replace(/'/g, "\\\\'");

                        html += `
                            <div class="product-card">
                                ${image ? `<img src="${image}" alt="${product.title}">` : ""}
                                <h3>${product.title || "بدون اسم"}</h3>
                                <div>${cleanDescription}</div>
                                <p class="muted">ID: ${product.id}</p>
                                <button type="button" onclick="selectProduct('${product.id}', '${safeTitle}')">
                                    اختيار هذا المنتج
                                </button>
                            </div>
                        `;
                    });

                    container.innerHTML = html;
                } catch (error) {
                    container.textContent = "فشل تحميل المنتجات: " + error.message;
                }
            }

            async function generateDescription() {
                const resultBox = document.getElementById("ai_result");
                resultBox.textContent = "جاري توليد الوصف...";

                const payload = {
                    title: document.getElementById("title").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    language: document.getElementById("language").value
                };

                try {
                    const res = await fetch("/ai/product-description", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    const data = await res.json();
                    resultBox.textContent = JSON.stringify(data, null, 2);
                } catch (error) {
                    resultBox.textContent = "فشل توليد الوصف: " + error.message;
                }
            }

            async function updateDescription() {
                const resultBox = document.getElementById("update_result");
                resultBox.textContent = "جاري تحديث المنتج...";

                const payload = {
                    shop: document.getElementById("shop").value,
                    product_id: document.getElementById("product_id").value,
                    title: document.getElementById("title").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    language: document.getElementById("language").value
                };

                try {
                    const res = await fetch("/ai/update-product-description", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    const data = await res.json();
                    resultBox.innerHTML = data.result
    .replace(/\n/g, "<br>")
    .replace(/### (.*?)/g, "<h3>$1</h3>")
    .replace(/\*\*(.*?)\*\*/g, "<b>$1</b>");
                } catch (error) {
                    resultBox.textContent = "فشل تحديث المنتج: " + error.message;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


# =========================
# تشغيل التطبيق
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

