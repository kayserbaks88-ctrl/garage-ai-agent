import os

from integrations.intent_router import route_intent
from integrations.staff_sheets import (
    add_check_in,
    update_check_out,
    list_on_site,
    get_active_check_in,
    clean_phone,
)
from integrations.employees import find_employee_by_phone
from integrations.reports import owner_report
from integrations.payroll import payroll_report
from integrations.invoices import invoice_report


MANAGER_ROLES = ["owner", "manager"]
OWNER_NUMBER = clean_phone(os.getenv("OWNER_NUMBER", ""))

PENDING_PHOTO = {}


def get_user(phone, profile_name=None):
    employee = find_employee_by_phone(phone)

    if employee:
        return {
            "name": employee.get("name") or profile_name or "Staff",
            "role": employee.get("role", "Staff"),
            "hourly_rate": employee.get("hourly_rate", ""),
            "status": employee.get("status", "Active"),
        }

    return {
        "name": profile_name or "Staff",
        "role": "Staff",
        "hourly_rate": "",
        "status": "Active",
    }


def is_manager(user, phone=None):
    if phone and OWNER_NUMBER and clean_phone(phone) == OWNER_NUMBER:
        return True

    return user.get("role", "").strip().lower() in MANAGER_ROLES


def first_photo(media_urls):
    if not media_urls:
        return ""

    if isinstance(media_urls, list) and media_urls:
        return media_urls[0]

    if isinstance(media_urls, str):
        return media_urls

    return ""


def clean_site(text):
    site = (text or "").strip()

    noise_start = [
        "hi", "hello", "hey", "morning", "good morning",
        "can you please", "can you", "please",
        "could you please", "could you",
    ]

    action_phrases = [
        "clock me in at", "check me in at", "sign me in at",
        "clock in at", "check in at", "sign in at",
        "clock me in", "check me in", "sign me in",
        "i'm at", "im at", "i am at",
        "start at", "started at", "starting at",
        "start", "started", "starting",
        "arrived at", "i've arrived at", "ive arrived at",
        "just got to", "got to", "working at", "on site at",
        "at",
    ]

    end_noise = ["please", "pls", "thanks", "thank you", "cheers"]

    changed = True
    while changed:
        changed = False
        lower = site.lower().strip()

        for phrase in noise_start:
            if lower.startswith(phrase + " "):
                site = site[len(phrase):].strip()
                changed = True
                break

        if changed:
            continue

        lower = site.lower().strip()

        for phrase in action_phrases:
            if lower.startswith(phrase + " "):
                site = site[len(phrase):].strip()
                changed = True
                break

    for word in end_noise:
        lower = site.lower().strip()
        if lower.endswith(" " + word):
            site = site[: -len(word)].strip()

    return site.title()


def clean_finish_site(text):
    site = (text or "").strip()

    phrases = [
        "clock me out from", "check me out from", "sign me out from",
        "clock out from", "check out from",
        "clock me out at", "check me out at", "sign me out at",
        "finish at", "finished at", "done at",
        "clock me out", "clock out",
        "check me out", "check out",
        "sign me out", "sign out",
        "finish", "finished", "done for today", "done",
        "end shift at", "end shift", "end my shift",
        "leaving", "left",
    ]

    lower = site.lower()

    for phrase in phrases:
        if lower.startswith(phrase + " "):
            site = site[len(phrase):].strip()
            break
        if lower == phrase:
            site = ""
            break

    for word in ["please", "pls", "thanks", "thank you", "cheers"]:
        lower = site.lower().strip()
        if lower.endswith(" " + word):
            site = site[: -len(word)].strip()

    return site.title() if site else None


def greeting_reply(phone, user):
    active = get_active_check_in(phone)

    if active:
        return (
            f"Hi 👋 Welcome back, {user['name']}.\n\n"
            f"You're currently checked in at {active['site']} since {active['check_in']}.\n\n"
            "You can say:\n"
            "• Finished\n"
            "• Who is on site?\n"
            "• Report"
        )

    if is_manager(user, phone):
        return (
            f"Hi 👋 Welcome back, {user['name']}.\n\n"
            "You're currently checked out.\n\n"
            "Manager options:\n"
            "• Who is on site?\n"
            "• Report\n"
            "• Payroll\n"
            "• Invoices\n\n"
            "Staff actions:\n"
            "• I'm at Tesco\n"
            "• Finished"
        )

    return (
        f"Hi 👋 Welcome back, {user['name']}.\n\n"
        "You're currently checked out.\n\n"
        "You can say:\n"
        "• I'm at Tesco\n"
        "• Finished"
    )


def no_access_reply():
    return (
        "Sorry, this is a manager-only request 🔒\n\n"
        "You can still check in, check out, or ask for your current status."
    )


def on_site_reply():
    people = list_on_site()

    if not people:
        return "Nobody is currently marked as on site 👍"

    reply = "📍 Currently on site:\n\n"

    for person in people:
        reply += (
            f"👷 {person['name']}\n"
            f"Site: {person['site']}\n"
            f"Since: {person['check_in']}\n\n"
        )

    return reply.strip()


def complete_pending_photo(phone, media_urls):
    photo_url = first_photo(media_urls)

    if not photo_url:
        return None

    pending = PENDING_PHOTO.get(clean_phone(phone))

    if not pending:
        return None

    action = pending.get("action")

    if action == "check_in":
        created, active = add_check_in(
            employee=pending["name"],
            phone=phone,
            site=pending["site"],
            check_in_photo=photo_url,
        )

        PENDING_PHOTO.pop(clean_phone(phone), None)

        if not created:
            return (
                "You're already checked in 👍\n\n"
                f"Staff: {active['name']}\n"
                f"Site: {active['site']}\n"
                f"Since: {active['check_in']}"
            )

        return (
            "✅ Photo received and checked in.\n\n"
            f"Staff: {pending['name']}\n"
            f"Site: {pending['site']}\n\n"
            "Have a good shift 👍"
        )

    if action == "check_out":
        completed_site, hours = update_check_out(
            phone=phone,
            site=pending.get("site"),
            check_out_photo=photo_url,
        )

        PENDING_PHOTO.pop(clean_phone(phone), None)

        if not completed_site:
            return (
                "I couldn't find an active check-in for you 👍\n\n"
                "If you're starting work, just say:\n"
                "I'm at Tesco"
            )

        return (
            "✅ Photo received and checked out.\n\n"
            f"Site: {completed_site}\n"
            f"Hours: {hours}\n\n"
            "Nice work 👍"
        )

    return None


def handle_message(phone, text, profile_name=None, media_urls=None):
    text = (text or "").strip()
    lower = text.lower()
    intent = route_intent(text)

    user = get_user(phone, profile_name)
    name = user["name"]

    photo_result = complete_pending_photo(phone, media_urls)
    if photo_result:
        return photo_result

    if lower in ["thanks", "thank you", "cheers", "nice one"]:
        return "You're welcome 👍"

    if intent == "greeting":
        return greeting_reply(phone, user)

    if intent == "start":
        site = clean_site(text)

        if not site:
            return "No problem 👍 What site or route are you checking in to?"

        photo_url = first_photo(media_urls)

        if photo_url:
            created, active = add_check_in(
                employee=name,
                phone=phone,
                site=site,
                check_in_photo=photo_url,
            )

            if not created:
                return (
                    "You're already checked in 👍\n\n"
                    f"Staff: {active['name']}\n"
                    f"Site: {active['site']}\n"
                    f"Since: {active['check_in']}"
                )

            return (
                "✅ Checked in with photo.\n\n"
                f"Staff: {name}\n"
                f"Site: {site}\n\n"
                "Have a good shift 👍"
            )

        PENDING_PHOTO[clean_phone(phone)] = {
            "action": "check_in",
            "name": name,
            "site": site,
        }

        return (
            f"📸 Before I check you in at {site}, please send a quick photo from site."
        )

    if intent == "finish":
        site = clean_finish_site(text)
        photo_url = first_photo(media_urls)

        if photo_url:
            completed_site, hours = update_check_out(
                phone=phone,
                site=site,
                check_out_photo=photo_url,
            )

            if not completed_site:
                return (
                    "I couldn't find an active check-in for you 👍\n\n"
                    "If you're starting work, just say:\n"
                    "I'm at Tesco"
                )

            return (
                "✅ Checked out with photo.\n\n"
                f"Site: {completed_site}\n"
                f"Hours: {hours}\n\n"
                "Nice work 👍"
            )

        PENDING_PHOTO[clean_phone(phone)] = {
            "action": "check_out",
            "name": name,
            "site": site,
        }

        return "📸 Please send a quick checkout photo before I clock you out."

    if intent == "on_site":
        if not is_manager(user, phone):
            return no_access_reply()
        return on_site_reply()

    if intent == "report":
        if not is_manager(user, phone):
            return no_access_reply()
        return owner_report()

    if intent == "payroll":
        if not is_manager(user, phone):
            return no_access_reply()
        return payroll_report()

    if intent == "invoices":
        if not is_manager(user, phone):
            return no_access_reply()
        return invoice_report()

    active = get_active_check_in(phone)

    if active:
        return (
            f"You're currently checked in at {active['site']} since {active['check_in']} 👍\n\n"
            "You can say:\n"
            "• Finished\n"
            "• Who is on site?\n"
            "• Report"
        )

    return (
        "I can help manage staff check-ins, reports, payroll and invoices 👍\n\n"
        "Try saying:\n"
        "• I'm at Tesco\n"
        "• Finished\n"
        "• Who is on site?\n"
        "• Report\n"
        "• Payroll\n"
        "• Invoices"
    )