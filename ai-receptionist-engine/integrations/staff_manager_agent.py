import re

from integrations.staff_sheets import (
    add_check_in,
    update_check_out,
    list_on_site,
    get_active_check_in,
)

from integrations.reports import owner_report
from integrations.payroll import payroll_report
from integrations.invoices import invoice_report
from integrations.employees import get_employees
from integrations.customers import get_customers
from integrations.sites import get_sites


def clean_site(text):
    lower = text.lower().strip()

    phrases = [
        "clock me in at", "clock me in", "check me in at", "check me in",
        "checking in at", "check in at", "check in",
        "i'm at", "im at", "i am at",
        "arrived at", "arrived",
        "started at", "started",
        "start at", "start",
        "at",
    ]

    for phrase in phrases:
        lower = lower.replace(phrase, " ")

    return " ".join(lower.split()).strip().title()


def clean_finish_site(text):
    lower = text.lower().strip()

    phrases = [
        "clock me out from", "clock me out",
        "check me out from", "check me out",
        "checking out from", "check out from", "check out",
        "finished at", "finished from", "finished",
        "finish at", "finish",
        "done at", "done",
        "leaving", "left",
    ]

    for phrase in phrases:
        lower = lower.replace(phrase, " ")

    return " ".join(lower.split()).strip().title()


def is_start_message(lower):
    return any(p in lower for p in [
        "start", "started", "arrived",
        "check in", "checking in",
        "clock in", "clock me in",
        "i'm at", "im at", "i am at",
    ])


def is_finish_message(lower):
    return any(p in lower for p in [
        "finish", "finished",
        "check out", "checking out",
        "clock out", "clock me out",
        "done", "leaving", "left",
    ])


def is_owner_site_question(lower):
    return any(p in lower for p in [
        "who is on site",
        "who's on site",
        "who on site",
        "who is working",
        "who's working",
        "where is everyone",
        "where are staff",
        "current staff",
        "on site",
    ])


def format_list(title, rows):
    if not rows or len(rows) <= 1:
        return f"{title}\n\nNothing saved yet 👍"

    message = f"{title}\n\n"

    for row in rows[1:]:
        row = row + [""] * 10
        message += f"• {row[0]}\n"

    return message.strip()


def handle_message(phone, text, profile_name=None, media_urls=None):
    text = (text or "").strip()
    lower = text.lower()
    name = profile_name or "Staff"

    if lower in ["hi", "hello", "hey", "start again", "help"]:
        active = get_active_check_in(phone)

        if active:
            return (
                f"Hi 👋 Welcome back, {name}.\n\n"
                f"You're currently checked in at {active['site']} since {active['check_in']}.\n\n"
                "You can say things like:\n"
                "• Finished\n"
                "• Who is on site?\n"
                "• Payroll\n"
                "• Report"
            )

        return (
            f"Hi 👋 Welcome back, {name}.\n\n"
            "You're currently checked out.\n\n"
            "You can say things like:\n"
            "• I'm at Tesco\n"
            "• Start Amazon route 17\n"
            "• Who is on site?\n"
            "• Payroll\n"
            "• Invoices\n"
            "• Report"
        )

    if lower in ["thanks", "thank you", "cheers", "nice one"]:
        return "You're welcome 👍"

    if is_owner_site_question(lower):
        active = list_on_site()

        if not active:
            return "Nobody is currently marked as on site 👍"

        reply = "📍 Currently on site:\n\n"

        for item in active:
            reply += f"✅ {item['employee']} - {item['site']} since {item['check_in']}\n"

        return reply.strip()

    if "report" in lower or "summary" in lower or "today" in lower:
        return owner_report()

    if "payroll" in lower or "wages" in lower or "pay" in lower:
        return payroll_report()

    if "invoice" in lower or "invoices" in lower or "bill" in lower:
        return invoice_report()

    if "employees" in lower or "staff list" in lower or "show staff" in lower:
        return format_list("👥 Employees", get_employees())

    if "customers" in lower or "clients" in lower:
        return format_list("🏢 Customers", get_customers())

    if "sites" in lower or "jobs" in lower:
        return format_list("📍 Sites", get_sites())

    if is_start_message(lower):
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
                f"Staff: {active['employee']}\n"
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

    if is_finish_message(lower):
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

    return (
        "I can help manage staff, sites, payroll and invoices 👍\n\n"
        "Try saying:\n"
        "• I'm at Tesco\n"
        "• Finished Tesco\n"
        "• Who is on site?\n"
        "• Report\n"
        "• Payroll\n"
        "• Invoices"
    )