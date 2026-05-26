from engine import get_business_name

def handle_message(text, phone):

    text = text.lower().strip()

    if text in ["hi", "hello", "hey"]:
        return (
            f"Hey 👋 welcome to {get_business_name()}\n\n"
            "• Book appointment ✂️\n"
            "• View bookings 📅\n"
            "• Reschedule 🔁\n"
            "• Cancel booking ❌"
        )

    return f"{get_business_name()} received: {text}"