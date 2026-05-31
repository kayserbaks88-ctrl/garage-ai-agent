SESSIONS = {}

from integrations.lead_calendar import create_lead

def handle_message(text, phone, profile_name=None):

    session = SESSIONS.setdefault(phone, {})

    if profile_name and not session.get("name"):
        session["name"] = profile_name

    text = (text or "").strip()

    if not session.get("enquiry"):

        if text.lower() in ["hi", "hello", "hey"]:

            return (
                f"Hi {profile_name or ''} 👋\n\n"
                "Thanks for getting in touch.\n\n"
                "How can I help today?\n\n"
                "• Property valuation\n"
                "• Selling a house\n"
                "• Car finance\n"
                "• Trade quote\n"
                "• Mortgage enquiry"
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