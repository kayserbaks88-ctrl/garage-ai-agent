import os
import re

from integrations.quote_sheets import add_quote_request
from integrations.email_helper import send_quote_notification

SESSIONS = {}

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "TrimTech Quotes")


FAQS = {
    "areas": "We cover local and surrounding areas 👍 If you send your postcode, we can confirm.",
    "area": "We cover local and surrounding areas 👍 If you send your postcode, we can confirm.",
    "open": "Our team will get back to quote requests as soon as possible.",
    "hours": "Our team will get back to quote requests as soon as possible.",
    "price": "Prices depend on the size and details of the job. I can collect a few details and pass them to the team for a quote.",
    "cost": "Prices depend on the size and details of the job. I can collect a few details and pass them to the team for a quote.",
    "photos": "Yes 👍 You can send photos during the quote request and I’ll pass them to the team.",
}


def welcome_message():
    return (
        f"Hi 👋 Thanks for contacting {BUSINESS_NAME}.\n\n"
        "I can answer simple questions or collect details for a quote request.\n\n"
        "What work are you looking to have done?"
    )


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

    if not cleaned:
        return text.strip()

    return cleaned.capitalize()

def looks_like_area(text):
    return bool(text.strip()) and not looks_like_postcode(text)


def format_location(session):
    area = session.get("area", "")
    postcode = session.get("postcode", "")

    if area and postcode:
        return f"{area} / {postcode}"
    return postcode or area

def format_postcode(text):
    pc = (text or "").strip().upper().replace(" ", "")
    if len(pc) > 3:
        return pc[:-3] + " " + pc[-3:]
    return pc


def looks_like_postcode(text):
    pc = (text or "").strip().upper().replace(" ", "")
    return bool(re.match(r"^[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2}$", pc))


def looks_like_budget(text):
    text = (text or "").lower()
    return "£" in text or "$" in text or any(char.isdigit() for char in text)


def looks_like_timeline(text):
    text = (text or "").lower()
    words = [
        "asap", "today", "tomorrow", "week", "month", "next",
        "urgent", "quote", "soon", "end of", "within", "no rush"
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


def maybe_answer_faq(text):
    lower = (text or "").lower()

    if any(word in lower for word in ["quote", "book", "need", "paint", "fix", "repair", "install"]):
        return None

    for key, answer in FAQS.items():
        if key in lower:
            return answer + "\n\nWould you like me to collect details for a quote?"

    return None


def summary_message(session):
    return (
        "📋 Quote Summary\n\n"
        f"Project: {session.get('job_type', '')}\n"
        f"Location: {format_location(session)}\n"
        f"Size: {session.get('job_size', '')}\n"
        f"Budget: {session.get('budget', '')}\n"
        f"Timeline: {session.get('timeline', '')}\n\n"
        f"Notes:\n{session.get('notes') or 'None'}\n\n"
        f"Photos received: {len(session.get('photos', []))}\n\n"
        "Reply CONFIRM to send this request.\n"
        "Reply CHANGE if you need to edit anything."
    )


def save_and_notify(phone, profile_name, session):
    name = session.get("name") or profile_name or "Unknown"
    job_type = session.get("job_type", "")
    postcode = session.get("postcode", "")
    job_size = session.get("job_size", "")
    budget = session.get("budget", "")
    timeline = session.get("timeline", "")
    notes = session.get("notes", "")
    photos = session.get("photos", [])

    photo_text = "\n".join(photos) if photos else "None"
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
            postcode=format_location(session),
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

    if lower in ["thanks", "thank you", "ok", "okay", "cheers", "nice one"]:
        return "You're welcome 👍 If you need another quote, just send HI."

    if lower in ["hi", "hello", "hey", "start", "restart", "new quote"]:
        SESSIONS.pop(phone, None)
        SESSIONS[phone] = {
            "name": profile_name or "",
            "photos": [],
        }
        return welcome_message()

    session = SESSIONS.setdefault(phone, {"name": profile_name or "", "photos": []})

    if media_urls:
        session.setdefault("photos", []).extend(media_urls)

        if session.get("awaiting_photos"):
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return summary_message(session)

        return ""

    if not any(k in session for k in ["job_type", "postcode", "job_size", "budget", "timeline", "notes"]):
        faq_reply = maybe_answer_faq(text)
        if faq_reply:
            return faq_reply

    if session.get("awaiting_confirmation"):
        if lower == "confirm":
            return save_and_notify(phone, profile_name, session)

        if lower == "change":
            session["awaiting_confirmation"] = False
            session["editing"] = True
            return (
                "What would you like to change?\n\n"
                "1. Project\n"
                "2. Postcode\n"
                "3. Size\n"
                "4. Budget\n"
                "5. Timeline\n"
                "6. Notes\n"
                "7. Photos"
            )

        return "Please reply CONFIRM to send, or CHANGE to edit."

    if session.get("editing"):
        fields = {
            "1": "job_type",
            "2": "postcode",
            "3": "job_size",
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
        elif field == "postcode":
            if not looks_like_postcode(text):
                session["edit_field"] = field
                return "That doesn't look like a postcode 👍 Please send the postcode again."
            session[field] = format_postcode(text)
        else:
            session[field] = text

        session["awaiting_confirmation"] = True
        return "Updated 👍\n\n" + summary_message(session)

    if "job_type" not in session:
        session["job_type"] = clean_project(text)
        return "No problem 👍 Roughly how big is the job? For example: small, medium, large, number of rooms, square metres, etc."

    if "job_size" not in session:
        session["job_size"] = text
        return "What postcode or area is the job in?"

    if "postcode" not in session and "area" not in session:
        if looks_like_postcode(text):
            session["postcode"] = format_postcode(text)
            return "Do you have a budget in mind?"

        session["area"] = text
        return (
            f"No problem 👍 I've saved the area as {text}.\n\n"
            "Can I take the postcode as well?"
        )

    if "area" in session and "postcode" not in session:
        if not looks_like_postcode(text):
            return "Please send the postcode for the job 👍"

        session["postcode"] = format_postcode(text)
        return "Do you have a budget in mind?"

        session["postcode"] = format_postcode(text)
        return "Do you have a budget in mind?"

    if "budget" not in session:
        if not looks_like_budget(text):
            return "Roughly what budget are you working with?"

        session["budget"] = text
        return (
            "When would you ideally like the work done?\n\n"
            "For example: ASAP, next week, within 1 month, or just gathering quotes."
        )

    if "timeline" not in session:
        if looks_like_job_notes(text) and not looks_like_timeline(text):
            session["notes"] = text
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
        return "Please add any extra details that would help with the quote."

    if "notes" not in session:
        session["notes"] = text
        session["awaiting_photos"] = True
        return (
            "Thanks 👍 Do you have any photos of the job?\n\n"
            "Send photos now, or type SKIP."
        )

    if session.get("awaiting_photos"):
        if lower in ["skip", "no", "none"]:
            session["awaiting_photos"] = False
            session["awaiting_confirmation"] = True
            return summary_message(session)

        return "Please send photos now, or type SKIP."

    return "We've already received your quote request 👍"