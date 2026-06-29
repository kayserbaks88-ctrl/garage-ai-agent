import os
import re

from integrations.quote_sheets import add_quote_request
from integrations.email_helper import send_quote_notification

SESSIONS = {}

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "TrimTech Quotes")


QUOTE_FLOWS = {
    "painting": {
        "keywords": ["paint", "painting", "decorate", "decorating", "walls", "ceiling"],
        "label": "Painting / Decorating",
        "questions": [
            ("job_size", "Roughly how big is the job? For example: 1 room, 2 rooms, whole house, etc."),
            ("job_details", "Is it walls only, or walls and ceiling / woodwork too?"),
            ("location", "What postcode or area is the job in?"),
            ("budget", "Do you have a budget in mind?"),
            ("timeline", "When would you ideally like the work done?"),
            ("notes", "Any extra details that would help with the quote?"),
        ],
    },

    "patio": {
        "keywords": ["patio", "slabs", "paving", "porcelain", "sandstone"],
        "label": "Patio / Paving",
        "questions": [
            ("job_size", "Roughly how big is the patio area? You can tell me in metres, square metres, or small/medium/large."),
            ("materials", "Do you know what material you'd like? For example porcelain, sandstone, slabs, or not sure yet."),
            ("removal", "Is there an old patio, grass, or decking that needs removing first?"),
            ("location", "What postcode or area is the job in?"),
            ("budget", "Do you have a budget in mind?"),
            ("timeline", "When would you ideally like the work done?"),
            ("notes", "Any extra details that would help with the quote?"),
        ],
    },

    "fencing": {
        "keywords": ["fence", "fencing", "panels", "gate"],
        "label": "Fencing",
        "questions": [
            ("job_size", "Roughly how many fence panels or metres of fencing do you need?"),
            ("materials", "What type of fencing are you looking for? Panels, closeboard, feather edge, or not sure yet?"),
            ("removal", "Does any old fencing need removing?"),
            ("location", "What postcode or area is the job in?"),
            ("budget", "Do you have a budget in mind?"),
            ("timeline", "When would you ideally like the work done?"),
            ("notes", "Any extra details that would help with the quote?"),
        ],
    },

    "general": {
        "keywords": [],
        "label": "General Quote Request",
        "questions": [
            ("job_size", "Roughly how big is the job?"),
            ("location", "What postcode or area is the job in?"),
            ("budget", "Do you have a budget in mind?"),
            ("timeline", "When would you ideally like the work done?"),
            ("notes", "Any extra details that would help with the quote?"),
        ],
    },
}


def welcome_message():
    return (
        f"Hi 👋 Thanks for contacting {BUSINESS_NAME}.\n\n"
        "I can collect the details for a quote request and pass them to the team.\n\n"
        "What work are you looking to have done?"
    )


def detect_flow(text):
    lower = (text or "").lower()

    for flow_key, flow in QUOTE_FLOWS.items():
        if flow_key == "general":
            continue

        for keyword in flow["keywords"]:
            if keyword in lower:
                return flow_key

    return "general"


def clean_project(text):
    text = (text or "").strip()
    lowered = text.lower()

    replacements = {
        "pain my room": "paint my room",
        "pain room": "paint room",
    }

    for wrong, right in replacements.items():
        lowered = lowered.replace(wrong, right)

    remove_phrases = [
        "i need a quote for",
        "need a quote for",
        "can i get a quote for",
        "can you quote for",
        "quote to",
        "quote for",
        "i need",
        "please",
    ]

    for phrase in remove_phrases:
        lowered = lowered.replace(phrase, "")

    cleaned = " ".join(lowered.split()).strip()
    return cleaned.capitalize() if cleaned else text.strip()


def looks_like_postcode(text):
    pc = (text or "").strip().upper().replace(" ", "")
    return bool(re.match(r"^[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}$", pc))


def format_postcode(text):
    pc = (text or "").strip().upper().replace(" ", "")
    if len(pc) > 3:
        return pc[:-3] + " " + pc[-3:]
    return pc


def format_location(session):
    area = session.get("area", "")
    postcode = session.get("postcode", "")

    if area and postcode:
        return f"{area} / {postcode}"

    return postcode or area


def summary_message(session):
    flow = QUOTE_FLOWS.get(session.get("flow", "general"), QUOTE_FLOWS["general"])
    answers = session.get("answers", {})

    extra_lines = ""
    for key, value in answers.items():
        if value:
            label = key.replace("_", " ").title()
            extra_lines += f"{label}: {value}\n"

    return (
        "📋 Quote Summary\n\n"
        f"Type: {flow['label']}\n"
        f"Project: {session.get('job_type', '')}\n"
        f"{extra_lines}"
        f"Location: {format_location(session)}\n"
        f"Budget: {session.get('budget', '')}\n"
        f"Timeline: {session.get('timeline', '')}\n\n"
        f"Notes:\n{session.get('notes') or 'None'}\n\n"
        f"Photos received: {len(session.get('photos', []))}\n\n"
        "Reply CONFIRM to send this request.\n"
        "Reply CHANGE if you need to edit anything."
    )


def next_question(session):
    flow = QUOTE_FLOWS.get(session.get("flow", "general"), QUOTE_FLOWS["general"])
    index = session.get("question_index", 0)

    if index >= len(flow["questions"]):
        session["awaiting_photos"] = True
        return (
            "Thanks 👍 Do you have any photos of the job?\n\n"
            "Send photos now, or type SKIP."
        )

    field, question = flow["questions"][index]
    session["current_field"] = field
    return question


def save_current_answer(session, text):
    field = session.get("current_field")

    if field == "location":
        if looks_like_postcode(text):
            session["postcode"] = format_postcode(text)
            session["question_index"] += 1
            return None

        session["area"] = text
        session["waiting_for_postcode_after_area"] = True
        return (
            f"No problem 👍 I've saved the area as {text}.\n\n"
            "Can I take the postcode as well?"
        )

    if field == "budget":
        session["budget"] = text

    elif field == "timeline":
        session["timeline"] = text

    elif field == "notes":
        session["notes"] = text

    else:
        session.setdefault("answers", {})[field] = text

    session["question_index"] += 1
    return None


def save_and_notify(phone, profile_name, session):
    name = session.get("name") or profile_name or "Unknown"
    job_type = session.get("job_type", "")
    location = format_location(session)
    budget = session.get("budget", "")
    timeline = session.get("timeline", "")
    notes = session.get("notes", "")
    photos = session.get("photos", [])
    answers = session.get("answers", {})

    details = ""
    for key, value in answers.items():
        if value:
            details += f"{key.replace('_', ' ').title()}: {value}\n"

    photo_text = "\n".join(photos) if photos else "None"

    final_notes = (
        f"{details}\n"
        f"{notes}\n\n"
        f"Photos:\n{photo_text}"
    ).strip()

    add_quote_request(
        name=name,
        phone=phone,
        job_type=job_type,
        postcode=location,
        job_size=answers.get("job_size", ""),
        budget=budget,
        timeline=timeline,
        notes=final_notes,
    )

    try:
        send_quote_notification(
            name=name,
            phone=phone,
            job_type=job_type,
            postcode=location,
            job_size=answers.get("job_size", ""),
            budget=budget,
            timeline=timeline,
            notes=final_notes,
        )
    except Exception as e:
        print("EMAIL ERROR:", repr(e))

    SESSIONS.pop(phone, None)

    return (
        f"Perfect {name} 👍\n\n"
        "I've passed your quote request to our team.\n\n"
        "A member of the team will be in touch shortly."
    )


def handle_message(phone, text, profile_name=None, media_urls=None):
    text = (text or "").strip()
    lower = text.lower()
    media_urls = media_urls or []

    if lower in ["thanks", "thank you", "ok", "okay", "cheers", "nice one"]:
        return "You're welcome 👍 If you need another quote, just send HI."

    if lower in ["hi", "hello", "hey", "start", "restart", "new quote"]:
        SESSIONS.pop(phone, None)
        SESSIONS[phone] = {
            "name": profile_name or "",
            "photos": [],
            "answers": {},
            "question_index": 0,
        }
        return welcome_message()

    session = SESSIONS.setdefault(
        phone,
        {
            "name": profile_name or "",
            "photos": [],
            "answers": {},
            "question_index": 0,
        },
    )

    if media_urls:
        session.setdefault("photos", []).extend(media_urls)

        if session.get("awaiting_photos"):
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return summary_message(session)

        return "Thanks 👍 I've added the photo(s) to your quote request."

    if session.get("waiting_for_postcode_after_area"):
        if not looks_like_postcode(text):
            return "Please send the postcode for the job 👍"

        session["postcode"] = format_postcode(text)
        session["waiting_for_postcode_after_area"] = False
        session["question_index"] += 1
        return next_question(session)

    if session.get("awaiting_confirmation"):
        if lower == "confirm":
            return save_and_notify(phone, profile_name, session)

        if lower == "change":
            session["awaiting_confirmation"] = False
            session["editing"] = True
            return (
                "What would you like to change?\n\n"
                "1. Project\n"
                "2. Location\n"
                "3. Budget\n"
                "4. Timeline\n"
                "5. Notes\n"
                "6. Photos"
            )

        return "Please reply CONFIRM to send, or CHANGE to edit."

    if session.get("editing"):
        fields = {
            "1": "job_type",
            "2": "location",
            "3": "budget",
            "4": "timeline",
            "5": "notes",
            "6": "photos",
        }

        field = fields.get(lower)

        if not field:
            return "Please choose 1, 2, 3, 4, 5 or 6."

        session["editing"] = False
        session["edit_field"] = field

        if field == "photos":
            session["photos"] = []
            session["awaiting_photos"] = True
            return "No problem 👍 Please send the photo(s) again now, or type SKIP."

        return "No problem 👍 Send the new answer now."

    if session.get("edit_field"):
        field = session.pop("edit_field")

        if field == "job_type":
            session["job_type"] = clean_project(text)
            session["flow"] = detect_flow(text)

        elif field == "location":
            if looks_like_postcode(text):
                session["postcode"] = format_postcode(text)
            else:
                session["area"] = text

        else:
            session[field] = text

        session["awaiting_confirmation"] = True
        return "Updated 👍\n\n" + summary_message(session)

    if "job_type" not in session:
        session["job_type"] = clean_project(text)
        session["flow"] = detect_flow(text)

        flow = QUOTE_FLOWS.get(session["flow"], QUOTE_FLOWS["general"])

        return (
            f"No problem 👍 I've got that as {flow['label']}.\n\n"
            + next_question(session)
        )

    if session.get("awaiting_photos"):
        if lower in ["skip", "no", "none"]:
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return summary_message(session)

        return "Please send photos now, or type SKIP."

    result = save_current_answer(session, text)

    if result:
        return result

    return next_question(session)