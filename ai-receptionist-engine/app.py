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
    phone = request.values.get("From", "")

    resp = MessagingResponse()

    from engine import BUSINESS

    if BUSINESS == "garage":
        from integrations.garage_agent import handle_message
        reply = handle_message(incoming, phone)

    elif BUSINESS == "barber":
        from integrations.barber_agent import handle_message
        reply = handle_message(incoming, phone)

    else:
        reply = f"{get_business_name()} received: {incoming}"

    resp.message(reply)

    return str(resp)