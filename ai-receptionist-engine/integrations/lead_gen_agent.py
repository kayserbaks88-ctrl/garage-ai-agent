SESSIONS = {}

from integrations.lead_calendar import create_lead

from twilio.rest import Client
import os

def notify_owner(
    name,
    phone,
    email,
    postcode,
    budget,
    enquiry,
    notes
):
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )

    message = f"""
🔥 NEW LEAD

Name: {name}
Phone: {phone}
Email: {email}

Enquiry:
{enquiry}

Budget:
{budget}

Postcode:
{postcode}

Notes:
{notes}
"""

    client.messages.create(
        body=message,
        from_=os.getenv("TWILIO_WHATSAPP_NUMBER"),
        to=os.getenv("OWNER_WHATSAPP")
    )

def handle_message(text, phone, profile_name=None):

    text_lower = text.lower().strip()

    if text_lower in ["thanks", "thank you", "cheers", "perfect", "great"]:
        return (
            f"You're welcome {profile_name or ''} 👍\n\n"
            "If there's anything else you need, just let me know."
        )

    if text_lower in ["ok", "okay", "ok thanks"]:
        return (
            "Perfect 👍\n\n"
            "I'm here if you need anything else."
        )

    if text_lower in ["bye", "goodbye", "see you", "speak soon"]:
        return (
            "Thanks for getting in touch 👋\n\n"
            "Have a great day."
        )

    if text_lower in ["ready", "yes", "yep", "yeah"]:
        return (
            "Perfect 👍\n\n"
            "How can I help today?"
        )

    session = SESSIONS.setdefault(phone, {})

    if profile_name and not session.get("name"):
        session["name"] = profile_name

    text = (text or "").strip()

    if not session.get("enquiry"):

        if text.lower() in ["hi", "hello", "hey"]:

            return (
                f"Hi {profile_name or ''} 👋\n\n"
                "Thanks for getting in touch.\n\n"
                "How can I help today?"
            )

        session["enquiry"] = text

        return (
            "No worries 👍\n\n"
            "Can I take your email address?"
        )

    if not session.get("email"):

        session["email"] = text

        return (
            "Perfect 👍\n\n"
            "What's your postcode?"
        )

    if not session.get("postcode"):

        session["postcode"] = text.upper()

        return (
            "Great 👍\n\n"
            "What's your estimated budget/value?"
        )

    if not session.get("budget"):

        session["budget"] = text

        return (
            "Almost done 👍\n\n"
            "Anything else you'd like us to know?"
        )

    if not session.get("notes"):

        session["notes"] = text

        create_lead(session, phone)

        notify_owner(
            name=session.get("name"),
            phone=phone,
            email=session.get("email"),
            postcode=session.get("postcode"),
            budget=session.get("budget"),
            enquiry=session.get("enquiry"),
            notes=session.get("notes")
        )

        return (
            f"Perfect {session.get('name', profile_name or '')} 👍\n\n"
            f"I've captured:\n\n"
            f"📧 {session['email']}\n"
            f"📍 {session['postcode']}\n"
            f"💷 {session['budget']}\n\n"
            f"A member of the team will contact you shortly."
        )

    return (
        "We've already received your enquiry 👍\n\n"
        "A member of the team will contact you shortly."
    )