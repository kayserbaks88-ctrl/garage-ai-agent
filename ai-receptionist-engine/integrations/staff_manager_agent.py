import re

from integrations.staff_sheets import (
    add_check_in,
    update_check_out,
    list_on_site,
    get_active_check_in,
)


def clean_site(text):
    lower = text.lower().strip()

    remove_phrases = [
        "clock me in at",
        "clock me in",
        "check me in at",
        "check me in",
        "checking in at",
        "check in at",
        "check in",
        "i'm at",
        "im at",
        "i am at",
        "arrived at",
        "arrived",
        "started at",
        "started",
        "start at",
        "start",
        "at",
    ]

    for phrase in remove_phrases:
        lower = lower.replace(phrase, " ")

    site = " ".join(lower.split()).strip()

    return site.title()


def clean_finish_site(text):
    lower = text.lower().strip()

    remove_phrases = [
        "clock me out from",
        "clock me out",
        "check me out from",
        "check me out",
        "checking out from",
        "check out from",
        "check out",
        "finished at",
        "finished from",
        "finished",
        "finish at",
        "finish",
        "done at",
        "done",
        "leaving",
        "left",
    ]

    for phrase in remove_phrases:
        lower = lower.replace(phrase, " ")

    site = " ".join(lower.split()).strip()

    return site.title()


def is_start_message(lower):
    start_phrases = [
        "start",
        "started",
        "arrived",
        "check in",
        "checking in",
        "clock in",
        "clock me in",
        "i'm at",
        "im at",
        "i am at",
    ]

    return any(phrase in lower for phrase in start_phrases)


def is_finish_message(lower):
    finish_phrases = [
        "finish",
        "finished",
        "check out",
        "checking out",
        "clock out",
        "clock me out",
        "done",
        "leaving",
        "left",
    ]

    return any(phrase in lower for phrase in finish_phrases)


def is_owner_site_question(lower):
    phrases = [
        "who is on site",
        "who's on site",
        "who on site",
        "who is working",
        "who's working",
        "where is everyone",
        "where are staff",
        "current staff",
        "on site",
    ]

    return any(phrase in lower for phrase in phrases)


def handle_message(phone, text, profile_name=None):
    text = (text or "").strip()
    lower = text.lower()
    name = profile_name or "Staff"

    if lower in ["hi", "hello", "hey"]:
        active = get_active_check_in(phone)

        if active:
            return (
                f"Hi 👋 Welcome back, {name}.\n\n"
                f"You're currently checked in at {active['site']} since {active['check_in']}.\n\n"
                "You can say:\n"
                "FINISH\n"
                "WHO IS ON SITE"
            )

        return (
            f"Hi 👋 Welcome back, {name}.\n\n"
            "You're currently checked out.\n\n"
            "You can say:\n"
            "START Tesco\n"
            "I'm at Tesco\n"
            "WHO IS ON SITE"
        )

    if is_owner_site_question(lower):
        active = list_on_site()

        if not active:
            return "Nobody is currently marked as on site 👍"

        reply = "📍 Currently on site:\n\n"

        for item in active:
            reply += f"✅ {item['employee']} - {item['site']} since {item['check_in']}\n"

        return reply.strip()

    if is_start_message(lower):
        site = clean_site(text)

        if not site:
            return "No problem 👍 What site are you checking in to?"

        created, active = add_check_in(
            employee=name,
            phone=phone,
            site=site,
        )

        if not created:
            return (
                "You're already checked in 👍\n\n"
                f"Staff: {active['employee']}\n"
                f"Site: {active['site']}\n"
                f"Since: {active['check_in']}\n\n"
                "Send FINISH when you're done."
            )

        return (
            "✅ Checked in.\n\n"
            f"Staff: {name}\n"
            f"Site: {site}"
        )

    if is_finish_message(lower):
        site = clean_finish_site(text)

        completed_site, hours = update_check_out(
            phone,
            site if site else None,
        )

        if not completed_site:
            return "I couldn't find an active check-in for you 👍"

        return (
            "✅ Checked out.\n\n"
            f"Site: {completed_site}\n"
            f"Hours: {hours}"
        )

    return (
        "I can help track staff check-ins 👍\n\n"
        "Try:\n"
        "START Tesco\n"
        "I'm at Tesco\n"
        "FINISH Tesco\n"
        "WHO IS ON SITE"
    )