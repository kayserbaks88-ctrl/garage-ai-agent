from flask import Flask
from engine import get_business_name
import os

app = Flask(__name__)

@app.route("/")
def home():
    return f"{get_business_name()} running"


@app.route("/health")
def health():
    return {"ok": True}