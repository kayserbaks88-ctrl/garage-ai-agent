from agent_helper import run_receptionist_agent

SESSIONS = {}


def handle_message(text, phone, profile_name=None):
    session = SESSIONS.setdefault(
        phone,
        {
            "history": []
        }
    )

    if profile_name:
        session["profile_name"] = profile_name

    reply = run_receptionist_agent(
        user_message=text,
        phone=phone,
        profile_name=session.get("profile_name"),
        session=session,
        business_name="TrimTech Barbers",
        timezone_name="Europe/London"
    )

    session["history"].append({
        "role": "user",
        "content": text
    })

    session["history"].append({
        "role": "assistant",
        "content": reply
    })

    session["history"] = session["history"][-20:]

    return reply
