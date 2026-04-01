import os
import requests
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

DEFAULT_SHOP = "cg1ypm-rd.myshopify.com"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


@app.route("/")
def home():
    return dashboard()


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "openai_api_key_exists": bool(OPENAI_API_KEY),
        "shopify_access_token_exists": bool(SHOPIFY_ACCESS_TOKEN)
    })


@app.route("/products", methods=["GET"])
def get_products():
    shop = request.args.get("shop", DEFAULT_SHOP).strip()

    if not shop:
        return jsonify({"error": "Missing shop"}), 400

    if not SHOPIFY_ACCESS_TOKEN:
        return jsonify({"error": "Missing SHOPIFY_ACCESS_TOKEN"}), 500

    url = f"https://{shop}/admin/api/2024-01/products.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        data = response.json()
    except Exception as e:
        return jsonify({
            "error": "Failed to fetch products",
            "details": str(e)
        }), 500

    return jsonify(data), response.status_code


@app.route("/ai/product-description", methods=["POST"])
def ai_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    brand = (data.get("brand") or "").strip()
    product_type = (data.get("product_type") or "").strip()
    audience = (data.get("audience") or "").strip()
    tone = (data.get("tone") or "professional").strip()
    key_features = (data.get("key_features") or "").strip()

    if not title:
        return jsonify({"error": "Missing title"}), 400

    system_prompt = """You are a professional e-commerce copywriter specialized in writing high-converting product descriptions.

Write in clear, persuasive, realistic English.

Rules:
- Do not use poetic or exaggerated language
- Do not use weak words like: maybe, might, possibly
- Focus on real customer benefits
- Write like a real sales expert
- Use clear and direct language
- Do not use Markdown or symbols like ### or **

Structure:
- Strong marketing headline
- Persuasive opening paragraph
- Clear product benefits
- Strong closing call to action

The output must be ready to publish in a professional online store.
"""

    user_prompt = f"""Write a professional English product description for the following product.

Product name: {title}
Brand: {brand}
Product type: {product_type}
Target audience: {audience}
Tone: {tone}
Key features: {key_features}

Write the final result in English only.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        content = response.choices[0].message.content if response.choices else None

        if not content:
            return jsonify({"error": "Empty AI response"}), 500

        return jsonify({"result": content}), 200

    except Exception as e:
        return jsonify({
            "error": "AI request failed",
            "details": str(e)
        }), 500


@app.route("/dashboard", methods=["GET"])
def dashboard():
    html = """
    <!DOCTYPE html>
    <html lang="en" dir="ltr">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>VELTRIX AI</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0b1220;
                color: #e5e7eb;
                margin: 0;
                padding: 24px;
            }
            .container {
                max-width: 900px;
                margin: 0 auto;
            }
            .hero {
                background: linear-gradient(135deg, #172554, #1e293b);
                border-radius: 22px;
                padding: 28px;
                margin-bottom: 22px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.25);
            }
            .hero h1 {
                margin: 0 0 10px 0;
                font-size: 42px;
                color: #ffffff;
            }
            .hero p {
                margin: 0;
                color: #cbd5e1;
                font-size: 17px;
                line-height: 1.8;
            }
            .card {
                background: #162033;
                border-radius: 22px;
                padding: 24px;
                margin-bottom: 20px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.2);
            }
            h2 {
                margin-top: 0;
                margin-bottom: 18px;
                font-size: 30px;
                color: #ffffff;
            }
            .field-label {
                display: block;
                margin-bottom: 8px;
                color: #cbd5e1;
                font-size: 15px;
            }
            input, textarea, button {
                width: 100%;
                box-sizing: border-box;
                border: none;
                border-radius: 14px;
                padding: 14px 16px;
                margin-bottom: 14px;
                font-size: 16px;
            }
            input, textarea {
                background: #334155;
                color: #ffffff;
                outline: none;
            }
            textarea {
                min-height: 110px;
                resize: vertical;
                line-height: 1.7;
            }
            button {
                background: #22c55e;
                color: white;
                font-weight: bold;
                cursor: pointer;
                font-size: 18px;
            }
            button:hover {
                background: #16a34a;
            }
            .status {
                color: #94a3b8;
                margin-bottom: 12px;
            }
            .result-content {
                background: transparent;
                color: #e5e7eb;
                line-height: 1.9;
                font-size: 18px;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .products-box {
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
            @media (max-width: 640px) {
                body {
                    padding: 16px;
                }
                .hero h1 {
                    font-size: 32px;
                }
                h2 {
                    font-size: 26px;
                }
                .result-content {
                    font-size: 17px;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="hero">
                <h1>VELTRIX AI</h1>
                <p>Professional AI product description generator and Shopify product fetcher.</p>
            </div>

            <div class="card">
                <h2>Fetch Products</h2>
                <label class="field-label">Shop Domain</label>
                <input type="text" id="shop" value="cg1ypm-rd.myshopify.com" />
                <button type="button" onclick="loadProducts()">Fetch Products</button>
                <div id="products_result" class="products-box">No products loaded yet.</div>
            </div>

            <div class="card">
                <h2>Generate Product Description</h2>

                <label class="field-label">Product Name</label>
                <input type="text" id="title" placeholder="Example: Premium Perfume" />

                <label class="field-label">Brand</label>
                <input type="text" id="brand" placeholder="Example: Dior" />

                <label class="field-label">Product Type</label>
                <input type="text" id="product_type" placeholder="Example: Fragrance" />

                <label class="field-label">Target Audience</label>
                <input type="text" id="audience" placeholder="Example: Men and women" />

                <label class="field-label">Tone</label>
                <input type="text" id="tone" value="professional" placeholder="Example: professional" />

                <label class="field-label">Key Features</label>
                <textarea id="key_features" placeholder="Example: Long-lasting, elegant bottle, premium scent, gift-ready"></textarea>

                <button type="button" onclick="generateDescription()">Generate Description</button>

                <div id="ai_status" class="status">No description generated yet.</div>
                <div id="ai_result" class="result-content"></div>
            </div>
        </div>

        <script>
            function formatResult(text) {
                if (!text) return "";

                const lines = text.split("\\n").filter(line => line.trim() !== "");
                let html = "";

                for (const line of lines) {
                    const trimmed = line.trim();

                    if (
                        trimmed.toLowerCase().includes("headline") ||
                        trimmed.toLowerCase().includes("key benefits") ||
                        trimmed.toLowerCase().includes("call to action")
                    ) {
                        html += `<h3>${trimmed}</h3>`;
                    } else if (/^[-•\\d]/.test(trimmed)) {
                        html += `<div>• ${trimmed.replace(/^[-•\\d\\.\\s]+/, "")}</div>`;
                    } else {
                        html += `<div>${trimmed}</div>`;
                    }
                }

                return html;
            }

            async function loadProducts() {
                const shop = document.getElementById("shop").value;
                const box = document.getElementById("products_result");
                box.textContent = "Loading products...";

                try {
                    const res = await fetch("/products?shop=" + encodeURIComponent(shop));
                    const data = await res.json();

                    if (!res.ok) {
                        box.textContent = "Error: " + JSON.stringify(data, null, 2);
                        return;
                    }

                    if (!data.products || data.products.length === 0) {
                        box.textContent = "No products found.";
                        return;
                    }

                    let html = "";

                    data.products.forEach(product => {
                        const image = product.images && product.images.length > 0
                            ? product.images[0].src
                            : "";

                        const cleanDescription = product.body_html
                            ? product.body_html.replace(/<[^>]+>/g, "")
                            : "No description";

                        html += `
                            <div class="product-card">
                                ${image ? `<img src="${image}" alt="${product.title}">` : ""}
                                <h3>${product.title || "Untitled"}</h3>
                                <p>${cleanDescription}</p>
                                <p class="muted">ID: ${product.id}</p>
                            </div>
                        `;
                    });

                    box.innerHTML = html;
                } catch (error) {
                    box.textContent = "Failed to load products: " + error.message;
                }
            }

            async function generateDescription() {
                const statusBox = document.getElementById("ai_status");
                const resultBox = document.getElementById("ai_result");

                statusBox.textContent = "Generating description...";
                resultBox.innerHTML = "";

                const payload = {
                    title: document.getElementById("title").value,
                    brand: document.getElementById("brand").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    key_features: document.getElementById("key_features").value
                };

                try {
                    const res = await fetch("/ai/product-description", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload)
                    });

                    const data = await res.json();

                    if (!res.ok) {
                        statusBox.textContent = "Failed to generate description.";
                        resultBox.textContent = JSON.stringify(data, null, 2);
                        return;
                    }

                    if (!data.result) {
                        statusBox.textContent = "No result returned from server.";
                        return;
                    }

                    statusBox.textContent = "Description generated successfully.";
                    resultBox.innerHTML = formatResult(data.result);
                } catch (error) {
                    statusBox.textContent = "Request failed.";
                    resultBox.textContent = error.message;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
                

