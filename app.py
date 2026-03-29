from flask import Flask, request, render_template_string
from openai import OpenAI
import os

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>VELTRIX AI</title>
</head>
<body>
    <h1>VELTRIX AI</h1>

    <form method="POST">
        <textarea name="prompt" rows="5" cols="40"></textarea><br><br>
        <button type="submit">Send</button>
    </form>

    {% if result %}
    <h3>Result:</h3>
    <p>{{ result }}</p>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    result = ""

    if request.method == "POST":
        prompt = request.form.get("prompt")

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )

        result = response.output_text

    return render_template_string(HTML_PAGE, result=result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

