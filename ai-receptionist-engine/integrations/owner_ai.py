from integrations.scheduler import who_is_on_site, morning_briefing


def handle_owner_message(text):
    lower = (text or "").lower().strip()

    if lower in ["morning", "good morning", "daily update", "today"]:
        return morning_briefing()

    if (
        "who is on site" in lower
        or "who's on site" in lower
        or "who on site" in lower
        or "who is working" in lower
        or "where is everyone" in lower
    ):
        return who_is_on_site()

    if "payroll" in lower:
        return "Payroll module is ready to connect next 👍"

    if "invoice" in lower:
        return "Invoice module is ready to connect next 👍"

    return (
        "I can help manage the workforce 👍\n\n"
        "Try:\n"
        "WHO IS ON SITE\n"
        "MORNING\n"
        "PAYROLL THIS WEEK\n"
        "INVOICES DUE"
    )