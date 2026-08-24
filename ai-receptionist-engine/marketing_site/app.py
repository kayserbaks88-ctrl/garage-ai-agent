from __future__ import annotations

from pathlib import Path

from flask import Flask, send_from_directory


BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)


@app.get("/")
def landing_page():
    return send_from_directory(BASE_DIR, "landing.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "trimtech-ai-marketing",
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)