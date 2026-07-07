import os

from integrations.intent_router import route_intent
from integrations.gps_helper import verify_location
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

SESSIONS = {}


def session_key(phone):
    return clean_phone(phone)


def get_user(phone, profile_name=None):
    employee = find_employee_by_phone(phone)

    if employee:
        return {
            "name": employee.get("name") or profile_name or "Staff",
            "role": employee.get("role") or "Staff",
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
    if isinstance(media_urls, list) and media_urls:
        return media_urls[0]
    if isinstance(media_urls, str):
        return media_urls
    return ""


def has_location(location):
    return bool((location or {}).get("latitude") and (location or {}).get("longitude"))


def clean_site(text):
    site = (text or "").strip()

    noise_start = [
        "hi", "hello", "hey", "morning", "good morning",
        "can you please", "can you", "could you please", "could you",
        "please",
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

    end_noise = ["please", "pls", "thanks", "thank you", "cheers", "now"]

    changed = True
    while changed:
        changed = False
        lower = site.lower().strip()

        for phrase in noise_start + action_phrases:
            if lower == phrase:
                site = ""
                changed = True
                break

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
    lower = site.lower()

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

    for phrase in phrases:
        if lower == phrase:
            return None

        if lower.startswith(phrase + " "):
            site = site[len(phrase):].strip()
            break

    for word in ["please", "pls", "thanks", "thank you", "cheers", "now"]:
        lower = site.lower().strip()

        if lower == word:
            site = ""
            break

        if lower.endswith(" " + word):
            site = site[: -len(word)].strip()

    return site.title() if site else None

def request_location(site):
    return (
        f"📍 Before I check you in at {site}, please share your current WhatsApp location.\n\n"
        "Tap + or 📎 → Location → Send current location."
    )


def no_access_reply():
    return (
        "Sorry, this is a manager-only request 🔒\n\n"
        "You can still check in, check out, or ask for your current status."
    )


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
            "• Clock me in at Tesco\n"
            "• Finished"
        )

    return (
        f"Hi 👋 Welcome back, {user['name']}.\n\n"
        "You're currently checked out.\n\n"
        "You can say:\n"
        "• Clock me in at Tesco\n"
        "• Finished"
    )


def on_site_reply():
    people = list_on_site()

    if not people:
        return "Nobody is currently marked as on site 👍"

    reply = "📍 Currently on site:\n\n"

    for person in people:
        gps = person.get("gps", "")
        gps_line = f"GPS: {gps}\n" if gps else ""

        reply += (
            f"👷 {person['name']}\n"
            f"Site: {person['site']}\n"
            f"Since: {person['check_in']}\n"
            f"{gps_line}\n"
        )

    return reply.strip()


def complete_gps_step(phone, location):
    key = session_key(phone)
    pending = SESSIONS.get(key)

    if not pending or pending.get("stage") != "awaiting_location":
        return None

    lat = location.get("latitude")
    lng = location.get("longitude")
    site = pending["site"]
    name = pending["name"]

    gps_result = verify_location(site, lat, lng)

    if not gps_result["verified"]:
        return gps_result["message"]

    if gps_result.get("photo_required"):
        SESSIONS[key] = {
            "stage": "awaiting_photo",
            "name": name,
            "site": gps_result["site"],
            "gps_text": gps_result["gps_text"],
        }

        return (
            f"{gps_result['message']}\n\n"
            "📸 This site requires photo proof. Please send a quick photo from site."
        )

    created, active = add_check_in(
        employee=name,
        phone=phone,
        site=gps_result["site"],
        gps_text=gps_result["gps_text"],
    )

    SESSIONS.pop(key, None)

    if not created:
        return (
            "You're already checked in 👍\n\n"
            f"Staff: {active['name']}\n"
            f"Site: {active['site']}\n"
            f"Since: {active['check_in']}"
        )

    return (
        f"{gps_result['message']}\n\n"
        "✅ Checked in.\n\n"
        f"Staff: {name}\n"
        f"Site: {gps_result['site']}\n\n"
        "Have a good shift 👍"
    )


def complete_photo_step(phone, media_urls):
    key = session_key(phone)
    pending = SESSIONS.get(key)
    photo_url = first_photo(media_urls)

    if not pending or pending.get("stage") != "awaiting_photo" or not photo_url:
        return None

    created, active = add_check_in(
        employee=pending["name"],
        phone=phone,
        site=pending["site"],
        check_in_photo=photo_url,
        gps_text=pending.get("gps_text", ""),
    )

    SESSIONS.pop(key, None)

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


def handle_message(phone, text, profile_name=None, media_urls=None, location=None):
    text = (text or "").strip()
    lower = text.lower()
    media_urls = media_urls or []
    location = location or {}

    intent = route_intent(text)
    user = get_user(phone, profile_name)
    name = user["name"]
    key = session_key(phone)

    if has_location(location):
        gps_reply = complete_gps_step(phone, location)
        if gps_reply:
            return gps_reply

    photo_reply = complete_photo_step(phone, media_urls)
    if photo_reply:
        return photo_reply

    if lower in ["thanks", "thank you", "cheers", "nice one"]:
        return "You're welcome 👍"

    if intent == "greeting":
        return greeting_reply(phone, user)

    if intent == "start":
        active = get_active_check_in(phone)

        if active:
            return (
                "You're already checked in 👍\n\n"
                f"Staff: {active['name']}\n"
                f"Site: {active['site']}\n"
                f"Since: {active['check_in']}\n\n"
                "Send FINISH when you're done."
            )

        site = clean_site(text)

        if not site:
            return "No problem 👍 What site or route are you checking in to?"

        if not has_location(location):
            SESSIONS[key] = {
                "stage": "awaiting_location",
                "name": name,
                "site": site,
            }

            return request_location(site)

        gps_reply = complete_gps_step(phone, location)
        if gps_reply:
            return gps_reply

    if intent == "finish":
        site = clean_finish_site(text)
        photo_url = first_photo(media_urls)

        completed_site, hours = update_check_out(
            phone=phone,
            site=site,
            check_out_photo=photo_url,
        )

        if not completed_site:
            return (
                "I couldn't find an active check-in for you 👍\n\n"
                "If you're starting work, just say:\n"
                "Clock me in at Tesco"
            )

        return (
            "✅ Checked out.\n\n"
            f"Site: {completed_site}\n"
            f"Hours: {hours}\n\n"
            "Nice work 👍"
        )

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

    pending = SESSIONS.get(key)

    if pending and pending.get("stage") == "awaiting_location":
        return request_location(pending["site"])

    if pending and pending.get("stage") == "awaiting_photo":
        return "📸 Please send a quick photo from site to complete your check-in."

    active = get_active_check_in(phone)

    if active:
        return (
            f"You're currently checked in at {active['site']} since {active['check_in']} 👍\n\n"
            "You can say:\n"
            "• Finished\n"
            "• Who is on site?\n"
            "• Report"
        )

    if intent is None:
        return (
            "I didn't quite understand that 👍\n\n"
            "Try saying:\n"
            "• Clock me in at Tesco\n"
            "• Finished\n"
            "• Who is on site?\n"
            "• Report\n"
            "• Payroll\n"
            "• Invoices"
        )
    
    return (
        "I can help manage staff check-ins, reports, payroll and invoices 👍\n\n"
        "Try saying:\n"
        "• Clock me in at Tesco\n"
        "• Finished\n"
        "• Who is on site?\n"
        "• Report\n"
        "• Payroll\n"
        "• Invoices"
    )