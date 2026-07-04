from integrations.staff_sheets import (
    add_check_in,
    update_check_out,
    list_on_site,
    get_active_check_in,
)

from integrations.reports import owner_report
from integrations.payroll import payroll_report
from integrations.invoices import invoice_report
from integrations.employees import find_employee_by_phone
from integrations.intent_router import route_intent


OWNER_ROLES = ["owner", "manager"]


def get_user(phone, profile_name=None):
    employee = find_employee_by_phone(phone)

    if employee:
        return {
            "name": employee.get("name") or profile_name or "Staff",
            "role": (employee.get("role") or "Staff").strip(),
            "hourly_rate": employee.get("hourly_rate", ""),
            "status": employee.get("status", "Active"),
        }

    return {
        "name": profile_name or "Staff",
        "role": "Staff",
        "hourly_rate": "",
        "status": "Active",
    }


def is_manager(user):
    return user["role"].lower() in OWNER_ROLES


def clean_site(text):
    t = (text or "").strip()

    remove_phrases = [
        "start",
        "started",
        "clock me in",
        "clock in",
        "check me in",
        "check in",
        "checking in",
        "i'm at",
        "im at",
        "i am at",
        "arrived at",
        "arrived",
        "i've arrived at",
        "ive arrived at",
        "i just got to",
        "just got to",
        "i'm on site at",
        "im on site at",
    ]

    lower = t.lower()

    for phrase in remove_phrases:
        if lower.startswith(phrase):
            site = t[len(phrase):].strip()
            return site.title() if site else ""

    return t.title()


def clean_finish_site(text):
    t = (text or "").strip()

    remove_phrases = [
        "finish",
        "finished",
        "done",
        "done for today",
        "clock me out",
        "clock out",
        "check out",
        "checkout",
        "i'm finished at",
        "im finished at",
        "finished at",
    ]

    lower = t.lower()

    for phrase in remove_phrases:
        if lower.startswith(phrase):
            site = t[len(phrase):].strip()
            return site.title() if site else None

    return None


def greeting_reply(phone, user):
    active = get_active_check_in(phone)

    if active:
        return (
            f"Hi 👋 Welcome back, {user['name']}.\n\n"
            f"You're currently checked in at {active['site']} since {active['check_in']}.\n\n"
            "You can say things like:\n"
            "• Finished\n"
            "• Who is on site?\n"
            "• Payroll\n"
            "• Report"
        )

    if is_manager(user):
        return (
            f"Hi 👋 Welcome back, {user['name']}.\n\n"
            "You're currently checked out.\n\n"
            "You can say things like:\n"
            "• I'm at Tesco\n"
            "• Start Amazon route 17\n"
            "• Who is on site?\n"
            "• Payroll\n"
            "• Invoices\n"
            "• Report"
        )

    return (
        f"Hi 👋 Welcome back, {user['name']}.\n\n"
        "You're currently checked out.\n\n"
        "You can say things like:\n"
        "• I'm at Tesco\n"
        "• Start Amazon route 17\n"
        "• Finished"
    )


def no_access_reply():
    return (
        "Sorry, this looks like a manager-only request 🔒\n\n"
        "You can still check in, check out, or ask for your current status."
    )


def on_site_reply():
    people = list_on_site()

    if not people:
        return "Nobody is currently marked as on site 👍"

    reply = "📍 Currently on site:\n\n"

    for item in people:
        name = item.get("name") or item.get("employee") or "Staff"
        site = item.get("site", "Unknown site")
        check_in = item.get("check_in", "")
        reply += f"👷 {name} - {site} since {check_in}\n"

    return reply.strip()


def handle_message(phone, text, profile_name=None, media_urls=None):
    text = (text or "").strip()
    lower = text.lower()
    intent = route_intent(text)

    user = get_user(phone, profile_name)
    name = user["name"]

    if intent == "greeting":
        return greeting_reply(phone, user)

    if intent == "start":
        site = clean_site(text)

        if not site:
            return "No problem 👍 What site or route are you checking in to?"

        created, active = add_check_in(
            employee=name,
            phone=phone,
            site=site,
        )

        if not created:
            return (
                "You're already checked in 👍\n\n"
                f"Staff: {active.get('name') or active.get('employee')}\n"
                f"Site: {active['site']}\n"
                f"Since: {active['check_in']}\n\n"
                "Send FINISH when you're done."
            )

        return (
            "✅ Checked in.\n\n"
            f"Staff: {name}\n"
            f"Site: {site}\n\n"
            "Have a good shift 👍"
        )

    if intent == "finish":
        site = clean_finish_site(text)

        completed_site, hours = update_check_out(
            phone,
            site if site else None,
        )

        if not completed_site:
            return (
                "I couldn't find an active check-in for you 👍\n\n"
                "If you're starting work, just say:\n"
                "I'm at Tesco"
            )

        return (
            "✅ Checked out.\n\n"
            f"Site: {completed_site}\n"
            f"Hours: {hours}\n\n"
            "Nice work 👍"
        )

    if intent == "on_site":
        if not is_manager(user):
            return no_access_reply()

        return on_site_reply()

    if intent == "report":
        if not is_manager(user):
            return no_access_reply()

        return owner_report()

    if intent == "payroll":
        if not is_manager(user):
            return no_access_reply()

        return payroll_report()

    if intent == "invoices":
        if not is_manager(user):
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
        "I can help with check-ins, reports, payroll and invoices 👍\n\n"
        "Try saying:\n"
        "• I'm at Tesco\n"
        "• Who is on site?\n"
        "• Report\n"
        "• Payroll\n"
        "• Invoices"
    )