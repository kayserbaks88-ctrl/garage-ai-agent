import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from twilio.twiml.voice_response import VoiceResponse, Gather
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from integrations.garage_leads import save_garage_lead


TIMEZONE = ZoneInfo("Europe/London")
GARAGE_CALENDAR_ID = os.getenv("GARAGE_CALENDAR_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

SCOPES = ["https://www.googleapis.com/auth/calendar"]

SESSIONS = {}


def get_calendar_service():
    if not GARAGE_CALENDAR_ID:
        return None

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None

    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def say_and_listen(message):
    response = VoiceResponse()

    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout="auto",
        language="en-GB",
    )

    gather.say(message, voice="Polly.Amy", language="en-GB")
    response.append(gather)

    response.say(
        "Sorry, I didn't hear anything. Please call again.",
        voice="Polly.Amy",
        language="en-GB",
    )
    response.hangup()

    return str(response)


def end_call(message):
    response = VoiceResponse()
    response.say(message, voice="Polly.Amy", language="en-GB")
    response.hangup()
    return str(response)


def clean(text):
    return (text or "").strip()


def detect_service(text):
    t = text.lower()

    if "mot" in t:
        return "MOT"
    if "full service" in t:
        return "Full Service"
    if "service" in t:
        return "Service"
    if "diagnostic" in t or "warning light" in t or "engine light" in t:
        return "Diagnostic"
    if "oil" in t:
        return "Oil Change"
    if "clutch" in t:
        return "Clutch Repair"
    if "brake" in t:
        return "Brake Repair"
    if "repair" in t or "fix" in t or "problem" in t:
        return "Repair"

    return "General Enquiry"


def service_duration_minutes(service):
    service = (service or "").lower()

    if "mot" in service:
        return 60
    if "full service" in service:
        return 120
    if "service" in service:
        return 90
    if "diagnostic" in service:
        return 45
    if "oil" in service:
        return 30

    return 60


def create_calendar_booking(session):
    service = get_calendar_service()

    if not service:
        return None

    now = datetime.now(TIMEZONE)
    start = now + timedelta(days=1)
    start = start.replace(hour=10, minute=0, second=0, microsecond=0)

    duration = service_duration_minutes(session.get("service_needed"))
    end = start + timedelta(minutes=duration)

    title = f"{session.get('service_needed', 'Garage Booking')} - {session.get('vehicle_reg', '')}"

    description = (
        f"Customer: {session.get('name', '')}\n"
        f"Phone: {session.get('phone', '')}\n"
        f"Reg: {session.get('vehicle_reg', '')}\n"
        f"Service: {session.get('service_needed', '')}\n"
        f"Issue: {session.get('issue', '')}\n"
        f"Preferred time: {session.get('preferred_time', '')}\n"
        f"Source: AI Voice Receptionist"
    )

    event = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "Europe/London",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "Europe/London",
        },
    }

    created = service.events().insert(
        calendarId=GARAGE_CALENDAR_ID,
        body=event,
    ).execute()

    return created.get("htmlLink")


def handle_voice_start(call_sid, caller_number):
    SESSIONS[call_sid] = {
        "phone": caller_number,
        "service_needed": "",
        "vehicle_reg": "",
        "issue": "",
        "preferred_time": "",
        "name": "",
        "notes": "",
        "stage": "service",
    }

    return say_and_listen(
        "Good afternoon, thanks for calling TrimTech Garage. "
        "The team are busy helping customers at the moment, "
        "but I can take your details and make sure someone gets back to you. "
        "How can I help today?"
    )


def handle_voice_process(call_sid, caller_number, speech_text):
    speech_text = clean(speech_text)

    if call_sid not in SESSIONS:
        return handle_voice_start(call_sid, caller_number)

    session = SESSIONS[call_sid]
    stage = session.get("stage")

    if stage == "service":
        session["service_needed"] = detect_service(speech_text)
        session["issue"] = speech_text
        session["stage"] = "reg"

        return say_and_listen(
            "No problem. Can I take your vehicle registration number please?"
        )

    if stage == "reg":
        session["vehicle_reg"] = speech_text.upper().replace(" ", "")
        session["stage"] = "preferred_time"

        if session["service_needed"] == "MOT":
            return say_and_listen(
                "Thank you. Is tomorrow okay, or would another day suit you better?"
            )

        return say_and_listen(
            "Thanks. When would you prefer to bring the vehicle in?"
        )

    if stage == "preferred_time":
        session["preferred_time"] = speech_text
        session["stage"] = "name"

        return say_and_listen(
            "Great. Finally, can I take your name please?"
        )

    if stage == "name":
        session["name"] = speech_text

        save_garage_lead(
            name=session["name"],
            phone=session["phone"],
            vehicle_reg=session["vehicle_reg"],
            service_needed=session["service_needed"],
            issue=session["issue"],
            preferred_time=session["preferred_time"],
            notes=session.get("notes", ""),
        )

        booking_link = create_calendar_booking(session)

        SESSIONS.pop(call_sid, None)

        if booking_link:
            return end_call(
                "Perfect. I've saved your details and added a provisional booking "
                "for the garage team to review. Someone will contact you shortly "
                "to confirm everything. Thank you for calling TrimTech Garage. Goodbye."
            )

        return end_call(
            "Perfect. I've saved your details for the garage team. "
            "Someone will contact you shortly to confirm everything. "
            "Thank you for calling TrimTech Garage. Goodbye."
        )

    return end_call(
        "Thank you. I've saved your details for the garage team. Goodbye."
    )