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


def handle_message(phone, text, profile_name=None):
    text = (text or "").strip()
    lower = text.lower()

    if lower in ["hi", "hello", "hey", "start", "restart", "new quote"]:
        SESSIONS.pop(phone, None)
        SESSIONS[phone] = {"name": profile_name or ""}
        return welcome_message()

    session = SESSIONS.setdefault(phone, {})

    if not session:
        session["name"] = profile_name or ""
        return welcome_message()

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
        session["timeline"] = text
        return "Please add any extra details that would help with the quote."

    if "notes" not in session:
        session["notes"] = text

        name = session.get("name") or profile_name or "Unknown"
        job_type = session.get("job_type", "")
        postcode = session.get("postcode", "")
        job_size = session.get("job_size", "")
        budget = session.get("budget", "")
        timeline = session.get("timeline", "")
        notes = session.get("notes", "")

        add_quote_request(
            name=name,
            phone=phone,
            job_type=job_type,
            postcode=postcode,
            job_size=job_size,
            budget=budget,
            timeline=timeline,
            notes=notes,
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
                notes=notes,
            )
        except Exception as e:
            print("EMAIL ERROR:", e)

        SESSIONS.pop(phone, None)

        return (
            f"Perfect {name} 👍\n\n"
            "I've passed your quote request to our team.\n\n"
            "Summary:\n"
            f"• Project: {job_type}\n"
            f"• Postcode: {postcode}\n"
            f"• Budget: {budget}\n"
            f"• Timeline: {timeline}\n\n"
            "A member of the team will be in touch shortly."
        )

    return (
        "We've already received your quote request 👍\n\n"
        "A member of the team will contact you shortly."
    )