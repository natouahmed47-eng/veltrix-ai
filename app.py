# Corrected code for app.py

# Import necessary libraries and modules
import os
import sys
from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
def predict():
    data = request.form['data']
    result = process_data(data)
    return render_template('result.html', result=result)

def process_data(data):
    # Function to process data
    processed_data = data.strip().lower()
    return processed_data

if __name__ == '__main__':
    app.run(debug=True)