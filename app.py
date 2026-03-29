from flask import Flask, request, render_template_string
from openai import OpenAI
import os

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar">
<head>
<meta charset="UTF-8">
<title>VELTRIX AI</title>
</head>
<body>

<h1>VELTRIX AI</h1>

<form method="POST">
<textarea name="prompt" rows="5" cols="40"></textarea><br><br>
<button type="submit">إرسال</button>
</form>

{% if response %}
<h3>الرد:</h3>
<p>{{ response }}</p>
{% endif %}

</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    response = ""

    if request.method == "POST":
        user_input = request.form["prompt"]

        try:
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": user_input}]
            )

            response = completion.choices[0].message.content

        except Exception as e:
            response = str(e)

    return render_template_string(HTML_PAGE, response=response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
