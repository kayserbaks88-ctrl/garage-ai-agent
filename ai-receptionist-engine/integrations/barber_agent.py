from agent_helper import run_receptionist_agent

SESSIONS = {}

def handle_message(text, phone):

    session = SESSIONS.setdefault(phone, {})

    reply = run_receptionist_agent(
        user_message=text,
        phone=phone,
        profile_name=None,
        session=session,
        business_name="TrimTech Barbers",
        timezone_name="Europe/London"
    )

    return reply