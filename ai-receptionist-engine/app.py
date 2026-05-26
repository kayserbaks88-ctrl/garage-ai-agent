from flask import Flask
from engine import get_business_name

app = Flask(__name__)

@app.route("/")
def home():
    return f"{get_business_name()} running"

import os

if __name__ == "__main__":
    print("Loaded:", get_business_name())

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=True
    )