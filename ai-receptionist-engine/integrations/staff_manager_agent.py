from integrations.staff_sheets import add_check_in, update_check_out, list_on_site


def clean_site(text):
    text = text.strip()

    remove_words = [
        "start",
        "started",
        "arrived",
        "arrive",
        "check in",
        "checking in",
        "at",
    ]

    lower = text.lower()

    for word in remove_words:
        lower = lower.replace(word, "")

    return " ".join(lower.split()).title()


def handle_message(phone, text, profile_name=None):
    text = (text or "").strip()
    lower = text.lower()
    name = profile_name or "Staff"

    if lower in ["hi", "hello", "hey"]:
        return (
            "Hi 👋 Staff Manager is ready.\n\n"
            "Employees can message:\n"
            "START Tesco\n"
            "FINISH Tesco\n\n"
            "Owner can ask:\n"
            "WHO IS ON SITE"
        )

    if "who is on site" in lower or "who's on site" in lower or "who on site" in lower:
        active = list_on_site()

        if not active:
            return "Nobody is currently marked as on site 👍"

        reply = "📍 Currently on site:\n\n"

        for item in active:
            reply += f"✅ {item['employee']} - {item['site']} since {item['check_in']}\n"

        return reply.strip()

    if lower.startswith("start") or lower.startswith("arrived") or lower.startswith("check in"):
        site = clean_site(text)

        if not site:
            return "No problem 👍 What site are you checking in to?"

        add_check_in(
            employee=name,
            phone=phone,
            site=site,
        )

        return f"✅ Checked in.\n\nStaff: {name}\nSite: {site}"

    if lower.startswith("finish") or lower.startswith("finished") or lower.startswith("check out"):
        site = text
        for word in ["finish", "finished", "check out"]:
            site = site.lower().replace(word, "")
        site = " ".join(site.split()).title()

        completed_site, hours = update_check_out(phone, site if site else None)

        if not completed_site:
            return "I couldn't find an active check-in for you 👍"

        return (
            f"✅ Checked out.\n\n"
            f"Site: {completed_site}\n"
            f"Hours: {hours}"
        )

    return (
        "I can help track staff check-ins 👍\n\n"
        "Try:\n"
        "START Tesco\n"
        "FINISH Tesco\n"
        "WHO IS ON SITE"
    )