MAX_RETRIES = 2


def retry_message(stage: str, retry_count: int, silence: bool = False) -> str:
    first = retry_count <= 1

    if silence:
        return (
            "Sorry, I couldn't hear anything. Please say that again when you're ready."
            if first else
            "I still can't hear you clearly. Please try once more."
        )

    messages = {
        "service": (
            "Sorry, what does the vehicle need help with?",
            "You can say MOT, full service, oil change, brakes, or diagnostic.",
        ),
        "registration": (
            "Sorry, I didn't catch the full registration. Please say all seven characters slowly.",
            "Please say it one character at a time, for example M C six five X L N.",
        ),
        "registration_confirm": (
            "Please say yes if the registration I repeated is correct, or no to try again.",
            "Is that registration correct? Please say yes or no.",
        ),
        "vehicle_confirm": (
            "Is that the correct vehicle? Please say yes or no.",
            "Please say yes if the vehicle is correct, or no to repeat the registration.",
        ),
        "date": (
            "Sorry, which day would suit you best?",
            "You can say tomorrow, next Tuesday, or a specific date.",
        ),
        "time": (
            "Sorry, what exact time would suit you?",
            "You can say five p m, ten in the morning, or two thirty.",
        ),
        "name": (
            "Sorry, I didn't catch your name. Could you say it again please?",
            "Please say just your first and last name.",
        ),
        "summary": (
            "Are the booking details correct? Please say yes or no.",
            "Please say yes to book, or no to change something.",
        ),
    }
    pair = messages.get(stage, (
        "Sorry, I didn't quite catch that. Could you say it again please?",
        "I'm still having trouble understanding. Please try saying it differently.",
    ))
    return pair[0] if first else pair[1]


def should_end(session: dict) -> bool:
    return int(session.get("retry_count") or 0) >= MAX_RETRIES


def final_message(business_name: str) -> str:
    return (
        "I'm sorry, I'm still having trouble hearing you clearly. "
        f"Please call {business_name} again, or contact the team by WhatsApp. Goodbye."
    )
