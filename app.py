import os
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


@app.route("/")
def home():
    return dashboard()


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "openai_api_key_exists": bool(OPENAI_API_KEY)
    })


@app.route("/ai/product-description", methods=["POST"])
def ai_product_description():
    if not client:
        return jsonify({"error": "Missing OPENAI_API_KEY"}), 500

    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    product_type = (data.get("product_type") or "").strip()
    audience = (data.get("audience") or "").strip()
    tone = (data.get("tone") or "احترافي").strip()
    language = (data.get("language") or "ar").strip()
    brand = (data.get("brand") or "").strip()
    key_features = (data.get("key_features") or "").strip()

    if not title:
        return jsonify({"error": "Missing title"}), 400

    if language == "ar":
        system_prompt = """
أنت خبير عربي محترف في كتابة أوصاف منتجات التجارة الإلكترونية.
اكتب بأسلوب تسويقي راقٍ ومقنع وواضح.
تجنب الحشو والعبارات الضعيفة والتكرار.
لا تستخدم تنسيق markdown مثل ### أو **.
اكتب النص النهائي بصياغة عربية نظيفة وجاهزة للعرض داخل متجر احترافي.

البنية المطلوبة:
1) عنوان تسويقي قصير.
2) فقرة وصف احترافية من 2 إلى 4 أسطر.
3) عنوان: المزايا الرئيسية
4) 5 نقاط مزايا واضحة ومقنعة.
5) فقرة ختامية تحفز على الشراء.

اجعل الأسلوب مناسبًا للمتاجر الحديثة والفاخرة.
"""
        user_prompt = f"""
اكتب وصفًا احترافيًا لهذا المنتج:

اسم المنتج: {title}
العلامة التجارية: {brand}
نوع المنتج: {product_type}
الجمهور المستهدف: {audience}
النبرة المطلوبة: {tone}
أهم المزايا: {key_features}

أريد النص عربيًا احترافيًا، أنيقًا، مقنعًا، وقابلًا للاستخدام مباشرة داخل المتجر.
"""
    else:
        system_prompt = """
أنت كاتب وصف منتجات فاخر ومحترف متخصص في التجارة الإلكترونية العربية.

اكتب وصفًا عربيًا أنيقًا ومقنعًا وجاهزًا للنشر في متجر احترافي.

تعليمات مهمة:
- لا تستخدم Markdown أو رموز مثل ### أو **.
- لا تكرر الفكرة بصيغ مختلفة.
- لا تكتب بلغة آلية أو جامدة.
- اجعل الأسلوب راقيًا، واضحًا، ومغريًا للشراء.
- ركّز على القيمة والفائدة والشعور الذي سيأخذه العميل من المنتج.
- اجعل النص مناسبًا لمتجر فاخر وحديث.

البنية المطلوبة:
1) عنوان تسويقي فاخر وقصير.
2) فقرة افتتاحية قوية ومقنعة.
3) عنوان فرعي: المزايا الرئيسية
4) خمس مزايا واضحة ومختصرة.
5) خاتمة بيع راقية تشجع على الشراء.

الناتج يجب أن يكون عربيًا طبيعيًا، نظيفًا، وسهل القراءة.
"""


import requests

@app.route("/products", methods=["GET"])
def get_products():
    shop = request.args.get("shop")

    if not shop:
        return jsonify({"error": "Shop is required"}), 400

    ACCESS_TOKEN = "PUT_YOUR_SHOPIFY_TOKEN_HERE"

    url = f"https://{shop}/admin/api/2023-10/products.json"

    headers = {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return jsonify({
                "error": "Shopify API error",
                "details": response.text
            }), response.status_code

        return jsonify(response.json())

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    































        user_prompt = f"""
Write a professional product description for:

Product name: {title}
Brand: {brand}
Product type: {product_type}
Target audience: {audience}
Tone: {tone}
Key features: {key_features}

The result must be premium, persuasive, elegant, and ready to use in an online store.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.8,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        content = response.choices[0].message.content if response.choices else None

        if not content:
            return jsonify({"error": "Empty AI response"}), 500

        return jsonify({
            "title": title,
            "result": content
        })

    except Exception as e:
        return jsonify({
            "error": "OpenAI request failed",
            "details": str(e)
        }), 500


@app.route("/dashboard")
def dashboard():
    html = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
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
                line-height: 1.9;
            }

            .card {
                background: #162033;
                border-radius: 22px;
                padding: 24px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.2);
            }

            h2 {
                margin-top: 0;
                margin-bottom: 18px;
                font-size: 34px;
                color: #ffffff;
            }

            .field-label {
                display: block;
                margin-bottom: 8px;
                color: #cbd5e1;
                font-size: 15px;
            }

            input, textarea, select, button {
                width: 100%;
                box-sizing: border-box;
                border: none;
                border-radius: 14px;
                padding: 14px 16px;
                margin-bottom: 14px;
                font-size: 16px;
            }

            input, textarea, select {
                background: #334155;
                color: #ffffff;
                outline: none;
            }

            textarea {
                min-height: 110px;
                resize: vertical;
                line-height: 1.8;
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

            .result-wrap {
                margin-top: 10px;
                background: transparent;
                border-radius: 0;
                padding: 0;
            }

            .result-content {
                background: transparent;
                color: #e5e7eb;
                line-height: 2;
                font-size: 18px;
                white-space: pre-wrap;
                word-wrap: break-word;
            }

            .result-content h3 {
                color: #ffffff;
                margin: 18px 0 10px 0;
                font-size: 24px;
            }

            .result-content strong {
                color: #22c55e;
            }

            .status {
                color: #94a3b8;
                margin-bottom: 12px;
            }

            @media (max-width: 640px) {
                body {
                    padding: 16px;
                }

                .hero h1 {
                    font-size: 32px;
                }

                h2 {
                    font-size: 28px;
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
                <p>مولد أوصاف منتجات احترافي، مصمم لكتابة نصوص راقية ومقنعة وجاهزة للاستخدام داخل المتجر.</p>
            </div>

            <div class="card">
                <h2>توليد وصف احترافي</h2>

                <label class="field-label">اسم المنتج</label>
                <input type="text" id="title" placeholder="مثال: ماكينة حلاقة رجالية احترافية" />

                <label class="field-label">العلامة التجارية</label>
                <input type="text" id="brand" placeholder="مثال: Hansom" />

                <label class="field-label">نوع المنتج</label>
                <input type="text" id="product_type" placeholder="مثال: أدوات العناية الشخصية" />

                <label class="field-label">الجمهور المستهدف</label>
                <input type="text" id="audience" placeholder="مثال: الرجال من 20 إلى 50 سنة" />

                <label class="field-label">النبرة</label>
                <input type="text" id="tone" value="احترافي" placeholder="مثال: احترافي / فاخر / مقنع" />

                <label class="field-label">اللغة</label>
                <input type="text" id="language" value="ar" placeholder="ar أو en" />

                <label class="field-label">أهم المزايا</label>
                <textarea id="key_features" placeholder="مثال: بطارية تدوم طويلاً، شفرات دقيقة، تصميم مريح، مقاومة للتهيج، سهلة الحمل"></textarea>

                <button type="button" onclick="generateDescription()">توليد الوصف</button>

                <div class="result-wrap">
                    <div id="ai_status" class="status">لم يتم توليد وصف بعد.</div>
                    <div id="ai_result" class="result-content"></div>
                </div>
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
                        trimmed.includes("العنوان التسويقي") ||
                        trimmed.includes("الوصف الاحترافي") ||
                        trimmed.includes("المزايا الرئيسية") ||
                        trimmed.includes("دعوة") ||
                        trimmed.includes("Key Benefits") ||
                        trimmed.includes("Marketing Headline")
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

            async function generateDescription() {
                const statusBox = document.getElementById("ai_status");
                const resultBox = document.getElementById("ai_result");

                statusBox.textContent = "جاري توليد الوصف...";
                resultBox.innerHTML = "";

                const payload = {
                    title: document.getElementById("title").value,
                    brand: document.getElementById("brand").value,
                    product_type: document.getElementById("product_type").value,
                    audience: document.getElementById("audience").value,
                    tone: document.getElementById("tone").value,
                    language: document.getElementById("language").value,
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
                        statusBox.textContent = "حدث خطأ أثناء التوليد.";
                        resultBox.textContent = JSON.stringify(data, null, 2);
                        return;
                    }

                    if (!data.result) {
                        statusBox.textContent = "لم يرجع النص من الخادم.";
                        return;
                    }

                    statusBox.textContent = "تم توليد الوصف بنجاح.";
                    resultBox.innerHTML = formatResult(data.result);

                } catch (error) {
                    statusBox.textContent = "فشل توليد الوصف.";
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

