from flask import Flask, request, render_template_string
from openai import OpenAI
import os

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VELTRIX AI</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 760px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 { margin-bottom: 10px; }
        textarea {
            width: 100%;
            min-height: 160px;
            padding: 12px;
            font-size: 16px;
            box-sizing: border-box;
        }
        button {
            padding: 12px 18px;
            font-size: 16px;
            cursor: pointer;
        }
        .result {
            margin-top: 24px;
            padding: 16px;
            background: #f5f5f5;
            border-radius: 8px;
            white-space: pre-wrap;
        }
        .error {
            margin-top: 24px;
            padding: 16px;
            background: #ffe8e8;
            color: #900;
            border-radius: 8px;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <h1>VELTRIX AI</h1>
    <p>اكتب طلبك ثم اضغط إرسال.</p>

    <form method="POST">
        <textarea name="prompt" placeholder="مثال: اكتب وصفًا احترافيًا لعطر رجالي فاخر">{{ prompt }}</textarea>
        <br><br>
        <button type="submit">إرسال</button>
    </form>

    {% if result %}
    <div class="result">
        <strong>النتيجة:</strong><br><br>
        {{ result }}
    </div>
    {% endif %}

    {% if error %}
    <div class="error">
        <strong>خطأ:</strong><br><br>
        {{ error }}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    result = ""
    error = ""
    prompt = ""

    if request.method == "POST":
        prompt = request.form.get("prompt", "").strip()

        if not prompt:
            error = "اكتب طلبًا أولًا."
        elif not os.getenv("OPENAI_API_KEY"):
            error = "المفتاح OPENAI_API_KEY غير موجود في Render."
        else:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response.choices[0].message.content
            except Exception as e:
                error = str(e)

    return render_template_string(
        HTML_PAGE,
        result=result,
        error=error,
        prompt=prompt
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
