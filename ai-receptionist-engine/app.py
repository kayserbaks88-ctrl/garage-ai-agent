from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from engine import get_business_name

app = Flask(__name__)


@app.route("/")
def home():
    return f"{get_business_name()} running"


@app.route("/whatsapp", methods=["POST"])
def whatsapp():

    incoming = request.values.get("Body", "").strip()

    resp = MessagingResponse()

    # temporary test
    resp.message(
        f"{get_business_name()} received: {incoming}"
    )

    return str(resp)