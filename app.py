from flask import Flask
import os
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

@app.route("/")
def home():
    return "Veltrix AI is running 🚀"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
