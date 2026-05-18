import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

from garage_agent import run_receptionist_agent

load_dotenv()

app = Flask(__name__)

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "RapidFix Garage")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/London"))

SESSIONS: dict[str, dict] = {}


@app.route("/", methods=["GET"])
def home():
    return {"ok": True, "service": BUSINESS_NAME}


@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "service": BUSINESS_NAME}


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    from_number = request.values.get("From", "")
    body = request.values.get("Body", "").strip()
    profile_name = request.values.get("ProfileName", "")

    session = SESSIONS.setdefault(from_number, {})

    print("📩 MESSAGE:", body)
    print("👤 USER:", from_number)

    try:
        reply = run_receptionist_agent(
            user_message=body,
            phone=from_number,
            profile_name=profile_name,
            session=session,
            business_name=BUSINESS_NAME,
            timezone_name=str(TIMEZONE),
        )
    except Exception as e:
        print("❌ BOT ERROR:", e)
        reply = "Sorry, something went wrong on my side. Try that again 👍"

    print("🤖 REPLY:", reply)

    resp = MessagingResponse()
    resp.message(reply)
    return str(resp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)