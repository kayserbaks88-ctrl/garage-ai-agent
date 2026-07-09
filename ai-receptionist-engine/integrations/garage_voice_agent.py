from twilio.twiml.voice_response import VoiceResponse, Gather

from integrations.garage_leads import save_garage_lead


SESSIONS = {}


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

    response.say("Sorry, I didn't hear anything. Please call again.", voice="Polly.Amy")
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
    if "service" in t:
        return "Service"
    if "diagnostic" in t or "warning light" in t or "engine light" in t:
        return "Diagnostic"
    if "oil" in t:
        return "Oil Change"
    if "repair" in t or "fix" in t or "problem" in t:
        return "Repair"

    return ""


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
        "Hi, thanks for calling TrimTech Garage. "
        "The team are busy at the moment, but I can take a few details "
        "and make sure someone gets back to you. "
        "How can I help today?"
    )


def handle_voice_process(call_sid, caller_number, speech_text):
    speech_text = clean(speech_text)

    if call_sid not in SESSIONS:
        return handle_voice_start(call_sid, caller_number)

    session = SESSIONS[call_sid]
    stage = session.get("stage")

    if stage == "service":
        service = detect_service(speech_text)

        if not service:
            session["issue"] = speech_text
            session["service_needed"] = "General Enquiry"
        else:
            session["service_needed"] = service

        session["stage"] = "reg"

        return say_and_listen(
            "No problem. Can I take your vehicle registration number please?"
        )

    if stage == "reg":
        session["vehicle_reg"] = speech_text.upper().replace(" ", "")
        session["stage"] = "issue"

        if session["service_needed"] == "MOT":
            return say_and_listen(
                "Thank you. Is this just for an MOT, or are there any advisories "
                "or repair work you would like the garage to look at as well?"
            )

        return say_and_listen(
            "Thanks. Please briefly tell me what the issue is, or what work you need done."
        )

    if stage == "issue":
        session["issue"] = speech_text
        session["stage"] = "preferred_time"

        return say_and_listen(
            "When would you prefer to bring the vehicle in?"
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

        SESSIONS.pop(call_sid, None)

        return end_call(
            "Thank you. I've passed your details to the garage. "
            "Someone will follow up with you as soon as possible. Goodbye."
        )

    return end_call(
        "Thank you. I've passed your details to the garage. Goodbye."
    )