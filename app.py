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

    title = data.get("title", "").strip()
    product_type = data.get("product_type", "").strip()
    audience = data.get("audience", "").strip()
    tone = data.get("tone", "احترافي").strip()
    language = data.get("language", "ar").strip()

    if not title:
        return jsonify({"error": "Missing title"}), 400

    prompt = f"""
اكتب وصف منتج احترافي عالي التحويل.

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
        <title>VELTRIX AI - AI Only</title>
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
            input, button {
                width: 100%;
                padding: 12px;
                margin-top: 10px;
                margin-bottom: 10px;
                border-radius: 10px;
                border: none;
                font-size: 16px;
                box-sizing: border-box;
            }
            input {
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
            .result-box {
                white-space: pre-wrap;
                word-wrap: break-word;
                background: #0f172a;
                padding: 12px;
                border-radius: 10px;
                overflow-x: auto;
                min-height: 100px;
            }
            h1, h2 {
                margin-top: 0;
            }
            .small {
                color: #cbd5e1;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>VELTRIX AI</h1>
                <p class="small">المرحلة 1: توليد النص فقط</p>
            </div>

            <div class="card">
                <h2>توليد وصف بالذكاء الاصطناعي</h2>
                <input type="text" id="title" placeholder="اسم المنتج"/>
                <input type="text" id="product_type" placeholder="نوع المنتج"/>
                <input type="text" id="audience" placeholder="الجمهور المستهدف"/>
                <input type="text" id="tone" value="احترافي" placeholder="النبرة"/>
                <input type="text" id="language" value="ar" placeholder="اللغة"/>
                <button type="button" onclick="generateDescription()">توليد الوصف</button>
                <div id="ai_result" class="result-box">لم يتم توليد وصف بعد.</div>
            </div>
        </div>

        <script>
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

                    if (!res.ok) {
                        resultBox.textContent = "خطأ: " + JSON.stringify(data, null, 2);
                        return;
                    }

                    if (resultBox.innerHTML = data.result
    .replace(/\\n/g, "<br>")
    .replace(/\n/g, "<br>")
    .replace(/### (.*?)(<br>|$)/g, "<h3>$1</h3>")
    .replace(/## (.*?)(<br>|$)/g, "<h2>$1</h2>")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
                         = "لم يرجع النص من الخادم.";
                        return;
                    }

                    resultBox.textContent = data.result;
                } catch (error) {
                    resultBox.textContent = "فشل توليد الوصف: " + error.message;
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

