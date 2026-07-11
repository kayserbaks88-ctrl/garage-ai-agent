from datetime import datetime


def greeting(customer_name=None):
    hour = datetime.now().hour

    if hour < 12:
        hello = "Good morning"
    elif hour < 18:
        hello = "Good afternoon"
    else:
        hello = "Good evening"

    if customer_name:
        return (
            f"{hello}, {customer_name}. "
            "Thanks for calling TrimTech Garage. "
            "The team are busy helping customers at the moment, "
            "but I'll happily help you."
        )

    return (
        f"{hello}. "
        "Thanks for calling TrimTech Garage. "
        "The team are busy helping customers right now, "
        "but I'll take a few details and make sure somebody gets back to you."
    )


def ask_service():
    return (
        "What can we help you with today?"
    )


def ask_registration():
    return (
        "Can I take your vehicle registration please?"
    )


def ask_confirm_vehicle(vehicle):
    return (
        f"I found a {vehicle}. "
        "Is that the correct vehicle?"
    )


def ask_day():
    return (
        "What day would you like to bring the vehicle in?"
    )


def ask_time():
    return (
        "What time works best for you?"
    )


def ask_name():
    return (
        "Finally, can I take your name please?"
    )


def booking_saved():
    return (
        "Perfect. I've saved everything for the garage team."
    )


def booking_calendar():
    return (
        "I've also added a provisional booking into the diary."
    )


def goodbye():
    return (
        "Thank you for calling TrimTech Garage. Have a lovely day. Goodbye."
    )


def thanks():
    return (
        "Thank you."
    )


def thinking():
    return (
        "One moment while I check that."
    )


def vehicle_not_found():
    return (
        "I couldn't automatically identify that registration, "
        "but that's absolutely fine. We'll still continue."
    )


def ask_yes_no():
    return (
        "Please answer yes or no."
    )


def ask_again():
    return (
        "Could you say that another way for me please?"
    )


def no_slots():
    return (
        "Nothing suitable is available then. "
        "Would another day work?"
    )


def calendar_problem():
    return (
        "The diary is temporarily unavailable, "
        "but I'll still save your preferred appointment."
    )


def lead_saved():
    return (
        "Everything has been saved successfully."
    )


def ending():
    return (
        "Someone from the garage will contact you shortly to confirm everything."
    )