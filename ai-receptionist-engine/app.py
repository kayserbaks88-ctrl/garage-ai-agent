from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from engine import BUSINESS

app = Flask(__name__)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():

    incoming = request.values.get("Body","")
    phone = request.values.get("From","")

    if BUSINESS == "garage":
        from integrations.garage_agent import handle_message
        reply = handle_message(incoming, phone)

    elif BUSINESS == "barber":
        from integrations.barber_agent import handle_message
        reply = handle_message(incoming, phone)

    resp = MessagingResponse()
    resp.message(reply)

    return str(resp)