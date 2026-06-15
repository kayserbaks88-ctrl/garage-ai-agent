import os
import re

from integrations.quote_sheets import add_quote_request
from integrations.email_helper import send_quote_notification

SESSIONS = {}

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "TrimTech Quotes")


def welcome_message():
    return (
        "Hi 👋 Thanks for contacting TrimTech Quotes.\n\n"
        "I'll gather a few details about your project and pass them to our team for a quote.\n\n"
        "What work are you looking to have done?"
    )


def clean_project(text):
    text = (text or "").strip()
    lowered = text.lower()

    remove_phrases = [
        "i need a quote for",
        "need a quote for",
        "quote for",
        "quote to",
        "can i get a quote for",
        "please",
    ]

    for phrase in remove_phrases:
        lowered = lowered.replace(phrase, "")

    cleaned = lowered.strip()

    if not cleaned:
        return text

    return cleaned.capitalize()


def looks_like_postcode(text):
    text = (text or "").strip().upper().replace(" ", "")
    return bool(re.match(r"^[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}$", text))


def looks_like_budget(text):
    text = (text or "").lower()
    return "£" in text or "$" in text or any(char.isdigit() for char in text)


def looks_like_timeline(text):
    text = (text or "").lower()
    words = [
        "asap", "today", "tomorrow", "week", "month", "next",
        "urgent", "soon", "when possible", "no rush",
        "end of", "within", "later"
    ]
    return any(w in text for w in words)


def looks_like_job_notes(text):
    text = (text or "").lower()
    words = [
        "wall", "walls", "ceiling", "room", "paint", "floor",
        "garden", "roof", "door", "window", "woodwork",
        "stairs", "hallway", "kitchen", "bathroom"
    ]
    return any(w in text for w in words)


def format_photos(photos):
    if not photos:
        return "None"
    return "\n".join(photos)


def summary_message(session):
    return (
        "📋 Quote Summary\n\n"
        f"Project: {session.get('job_type', '')}\n"
        f"Size: {session.get('job_size', '')}\n"
        f"Postcode: {session.get('postcode', '')}\n"
        f"Budget: {session.get('budget', '')}\n"
        f"Timeline: {session.get('timeline', '')}\n\n"
        f"Notes:\n{session.get('notes') or 'None'}\n\n"
        f"Photos received: {len(session.get('photos', []))}\n\n"
        "Reply CONFIRM to send this request.\n"
        "Reply CHANGE if you need to edit anything."
    )


def ask_next_question(session):
    if "job_type" not in session:
        return "What work are you looking to have done?"

    if "job_size" not in session:
        return "Roughly how big is the job? For example: small, medium, large, number of rooms, square metres, etc."

    if "postcode" not in session:
        return "What postcode or area is the job in?"

    if "budget" not in session:
        return "Do you have a budget in mind?"

    if "timeline" not in session:
        return (
            "When would you ideally like the work done?\n\n"
            "For example: ASAP, next week, within 1 month, or just gathering quotes."
        )

    if "notes" not in session:
        return "Please add any extra details that would help with the quote."

    if not session.get("photos_asked"):
        session["photos_asked"] = True
        session["awaiting_photos"] = True
        return (
            "Thanks 👍 Do you have any photos of the job?\n\n"
            "Send photos now, or type SKIP."
        )

    session["awaiting_confirmation"] = True
    return summary_message(session)


def save_and_notify(phone, profile_name, session):
    name = session.get("name") or profile_name or "Unknown"
    job_type = session.get("job_type", "")
    job_size = session.get("job_size", "")
    postcode = session.get("postcode", "")
    budget = session.get("budget", "")
    timeline = session.get("timeline", "")
    notes = session.get("notes", "")
    photos = session.get("photos", [])

    photo_text = format_photos(photos)
    notes_with_photos = f"{notes}\n\nPhotos:\n{photo_text}"

    add_quote_request(
        name=name,
        phone=phone,
        job_type=job_type,
        postcode=postcode,
        job_size=job_size,
        budget=budget,
        timeline=timeline,
        notes=notes_with_photos,
    )

    try:
        send_quote_notification(
            name=name,
            phone=phone,
            job_type=job_type,
            postcode=postcode,
            job_size=job_size,
            budget=budget,
            timeline=timeline,
            notes=notes_with_photos,
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

    if lower in ["hi", "hello", "hey", "start", "restart", "new quote"]:
        SESSIONS.pop(phone, None)
        SESSIONS[phone] = {
            "name": profile_name or "",
            "photos": [],
        }
        return welcome_message()

    session = SESSIONS.setdefault(
        phone,
        {
            "name": profile_name or "",
            "photos": [],
        }
    )

    if media_urls:
        session.setdefault("photos", []).extend(media_urls)

        if session.get("awaiting_photos"):
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return (
                f"Thanks 👍 I've added {len(media_urls)} photo(s).\n\n"
                + summary_message(session)
            )

        return f"Thanks 👍 I've added {len(media_urls)} photo(s) to your quote request."

    if session.get("awaiting_confirmation"):
        if lower == "confirm":
            return save_and_notify(phone, profile_name, session)

        if lower == "change":
            session["awaiting_confirmation"] = False
            session["editing"] = True
            return (
                "What would you like to change?\n\n"
                "1. Project\n"
                "2. Size\n"
                "3. Postcode\n"
                "4. Budget\n"
                "5. Timeline\n"
                "6. Notes\n"
                "7. Photos"
            )

        return "Please reply CONFIRM to send, or CHANGE to edit."

    if session.get("editing"):
        fields = {
            "1": "job_type",
            "2": "job_size",
            "3": "postcode",
            "4": "budget",
            "5": "timeline",
            "6": "notes",
            "7": "photos",
        }

        field = fields.get(lower)

        if not field:
            return "Please choose 1, 2, 3, 4, 5, 6 or 7."

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
            session[field] = clean_project(text)
        else:
            session[field] = text

        session["awaiting_confirmation"] = True
        return "Updated 👍\n\n" + summary_message(session)

    if "job_type" not in session:
        session["job_type"] = clean_project(text)
        return ask_next_question(session)

    if "job_size" not in session:
        if looks_like_postcode(text):
            session["postcode"] = text.upper()
            return (
                "No problem 👍 I've saved that as the postcode.\n\n"
                + ask_next_question(session)
            )

        session["job_size"] = text
        return ask_next_question(session)

    if "postcode" not in session:
        if not looks_like_postcode(text):
            return (
                "That doesn't look like a postcode 👍\n\n"
                "Please send the postcode or area for the job."
            )

        session["postcode"] = text.upper()
        return ask_next_question(session)

    if "budget" not in session:
        if not looks_like_budget(text):
            if looks_like_timeline(text):
                session["timeline"] = text
                return (
                    "👍 That sounds like the timeline, so I've saved it there.\n\n"
                    "Do you have a budget in mind?"
                )

            return "Roughly what budget are you working with?"

        session["budget"] = text
        return ask_next_question(session)

    if "timeline" not in session:
        if looks_like_job_notes(text) and not looks_like_timeline(text):
            existing_notes = session.get("notes", "")
            session["notes"] = f"{existing_notes}\n{text}".strip()
            return (
                "👍 That sounds like extra job information rather than a timeframe.\n\n"
                "I've added it to the notes.\n\n"
                "When would you like the work completed?\n"
                "• ASAP\n"
                "• Within 1 month\n"
                "• Within 3 months\n"
                "• Just gathering quotes"
            )

        session["timeline"] = text
        return ask_next_question(session)

    if "notes" not in session:
        session["notes"] = text
        return ask_next_question(session)

    if session.get("awaiting_photos"):
        if lower in ["skip", "no", "none"]:
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return summary_message(session)

        return "Please send photos now, or type SKIP."

    return "We've already received your quote request 👍"