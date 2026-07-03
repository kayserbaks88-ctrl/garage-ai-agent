from integrations.staff_sheets import list_on_site


def who_is_on_site():
    active = list_on_site()

    if not active:
        return "Nobody is currently marked as on site 👍"

    reply = "📍 Currently on site:\n\n"

    for item in active:
        reply += f"✅ {item['employee']} - {item['site']} since {item['check_in']}\n"

    return reply.strip()


def morning_briefing():
    active = list_on_site()

    return (
        "Good morning 👋\n\n"
        f"Staff currently on site: {len(active)}\n\n"
        "You can ask:\n"
        "WHO IS ON SITE\n"
        "PAYROLL THIS WEEK\n"
        "INVOICES DUE"
    )