import os
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


def looks_like_timeline(text):
    words = ["asap", "today", "tomorrow", "week", "month", "next", "urgent", "quote", "soon"]
    return any(w in text.lower() for w in words)


def looks_like_job_notes(text):
    words = ["wall", "walls", "ceiling", "room", "paint", "floor", "garden", "roof", "door", "window"]
    return any(w in text.lower() for w in words)


def summary_message(session):
    return (
        "📋 Quote Summary\n\n"
        f"Project: {session.get('job_type', '')}\n"
        f"Postcode: {session.get('postcode', '')}\n"
        f"Size: {session.get('job_size', '')}\n"
        f"Budget: {session.get('budget', '')}\n"
        f"Timeline: {session.get('timeline', '')}\n\n"
        f"Notes:\n{session.get('notes', 'None')}\n\n"
        f"Photos received: {len(session.get('photos', []))}\n\n"
        "Reply CONFIRM to send this request.\n"
        "Reply CHANGE if you need to edit anything."
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

    session = SESSIONS.setdefault(phone, {"name": profile_name or "", "photos": []})

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

    if not session:
        session["name"] = profile_name or ""
        session["photos"] = []
        return welcome_message()

    if session.get("awaiting_confirmation"):
        if lower == "confirm":
            name = session.get("name") or profile_name or "Unknown"
            job_type = session.get("job_type", "")
            postcode = session.get("postcode", "")
            job_size = session.get("job_size", "")
            budget = session.get("budget", "")
            timeline = session.get("timeline", "")
            notes = session.get("notes", "")
            photos = session.get("photos", [])

            photo_text = "\n".join(photos) if photos else "None"

            add_quote_request(
                name=name,
                phone=phone,
                job_type=job_type,
                postcode=postcode,
                job_size=job_size,
                budget=budget,
                timeline=timeline,
                notes=f"{notes}\n\nPhotos:\n{photo_text}",
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
                    notes=f"{notes}\n\nPhotos:\n{photo_text}",
                )
            except Exception as e:
                print("EMAIL ERROR:", repr(e))

            SESSIONS.pop(phone, None)

            return (
                f"Perfect {name} 👍\n\n"
                "I've passed your quote request to our team.\n\n"
                "A member of the team will be in touch shortly."
            )

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
        session[field] = text
        session["awaiting_confirmation"] = True
        return "Updated 👍\n\n" + summary_message(session)

    if "job_type" not in session:
        session["job_type"] = text
        return "No problem 👍 What postcode or area is the job in?"

    if "postcode" not in session:
        session["postcode"] = text
        return "Roughly how big is the job? For example: small, medium, large, number of rooms, square metres, etc."

    if "job_size" not in session:
        session["job_size"] = text
        return "Do you have a budget in mind?"

    if "budget" not in session:
        session["budget"] = text
        return "When would you ideally like the work done?"

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