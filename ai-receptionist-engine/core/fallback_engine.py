from __future__ import annotations

from typing import Any


MAX_NORMAL_RETRIES = 2
MAX_SILENCE_RETRIES = 2


def clean(value: Any) -> str:
    return str(value or "").strip()


def retry_message(
    awaiting: str = "",
    retry_count: int = 0,
    silence: bool = False,
) -> str:
    """
    Return a natural retry message based on what the receptionist
    is currently waiting for.

    The wording changes slightly after the first failed attempt so
    the AI does not repeat the exact same sentence.
    """
    awaiting = clean(awaiting).lower()
    retry_count = int(retry_count or 0)

    first_attempt = retry_count <= 1

    if awaiting == "service_key":
        if first_attempt:
            return (
                "Sorry, I didn't quite catch what you need help with. "
                "Could you briefly tell me what the vehicle needs?"
            )

        return (
            "I still didn't catch that clearly. "
            "You can say something like MOT, full service, "
            "oil change, brakes, or diagnostic check."
        )

    if awaiting == "registration":
        if first_attempt:
            return (
                "Sorry, I didn't catch the registration clearly. "
                "Could you say it again, one character at a time?"
            )

        return (
            "I'm still having trouble hearing the registration. "
            "Please say each letter and number separately, "
            "for example A B one two C D E."
        )

    if awaiting == "requested_date":
        if first_attempt:
            return (
                "Sorry, which day would suit you best?"
            )

        return (
            "I still didn't catch the day. "
            "You can say tomorrow, next Tuesday, "
            "or a specific date."
        )

    if awaiting == "requested_datetime":
        if first_attempt:
            return (
                "Sorry, what time would suit you best?"
            )

        return (
            "I still didn't catch the time. "
            "You can say something like ten in the morning "
            "or two thirty in the afternoon."
        )

    if awaiting == "name":
        if first_attempt:
            return (
                "Sorry, I didn't catch your name. "
                "Could you say it again please?"
            )

        return (
            "I'm still having trouble hearing your name. "
            "Please say just your first and last name."
        )

    if awaiting == "same_vehicle_confirmation":
        if first_attempt:
            return (
                "Sorry, is this about the same vehicle as last time?"
            )

        return (
            "Please say yes if it is the same vehicle, "
            "or no if it is a different one."
        )

    if awaiting == "vehicle_confirmation":
        if first_attempt:
            return (
                "Sorry, is that the correct vehicle?"
            )

        return (
            "Please say yes if the vehicle details are correct, "
            "or no if they are not."
        )

    if awaiting == "slot_selection":
        if first_attempt:
            return (
                "Sorry, which appointment time would you like?"
            )

        return (
            "Please choose one of the times I offered, "
            "or ask for another day."
        )

    if awaiting == "summary_confirmation":
        if first_attempt:
            return (
                "Sorry, is everything I repeated back correct?"
            )

        return (
            "Please say yes if the details are correct, "
            "or no if something needs changing."
        )

    if awaiting == "correction":
        if first_attempt:
            return (
                "No problem. What would you like me to change?"
            )

        return (
            "Please tell me the detail that needs changing, "
            "such as the service, registration, day, or time."
        )

    if silence:
        if first_attempt:
            return (
                "Sorry, I couldn't hear anything. "
                "Please say that again when you're ready."
            )

        return (
            "I still can't hear you clearly. "
            "Please try once more."
        )

    if first_attempt:
        return (
            "Sorry, I didn't quite catch that. "
            "Could you say it again please?"
        )

    return (
        "I'm still having trouble understanding. "
        "Could you try saying it a different way?"
    )


def should_end_after_retry(
    retry_count: int,
    silence_count: int = 0,
) -> bool:
    """
    End only after repeated failed attempts.

    This prevents the call from hanging up after one missed answer.
    """
    retry_count = int(retry_count or 0)
    silence_count = int(silence_count or 0)

    if silence_count >= MAX_SILENCE_RETRIES:
        return True

    if retry_count >= MAX_NORMAL_RETRIES:
        return True

    return False


def final_retry_message(
    business_name: str = "TrimTech Garage",
) -> str:
    """
    Polite final message after repeated silence or failed recognition.
    """
    business_name = clean(
        business_name
    ) or "TrimTech Garage"

    return (
        "I'm sorry, I'm still having trouble hearing you clearly. "
        f"Please call {business_name} again when you're ready, "
        "or contact the team by WhatsApp. "
        "Thank you for calling. Goodbye."
    )


def temporary_problem_message(
    business_name: str = "TrimTech Garage",
) -> str:
    business_name = clean(
        business_name
    ) or "TrimTech Garage"

    return (
        "I'm sorry, I'm having a temporary technical problem. "
        "I've kept the details you already provided where possible. "
        f"Please contact {business_name} again shortly. "
        "Thank you for your patience."
    )


def calendar_unavailable_message() -> str:
    return (
        "I can't check the live diary at the moment, "
        "but I can still save your preferred day and time "
        "for the garage team to confirm."
    )


def slot_taken_message() -> str:
    return (
        "I'm sorry, that appointment has just become unavailable. "
        "Let me check the next available options for you."
    )


def dvla_unavailable_message() -> str:
    return (
        "I couldn't confirm the vehicle details automatically, "
        "but that's not a problem. "
        "I'll continue using the registration you provided."
    )


def sheet_unavailable_message() -> str:
    return (
        "I'm having trouble saving the enquiry automatically, "
        "but I'll still continue with the call."
    )


def no_slots_message() -> str:
    return (
        "I couldn't find a suitable appointment on that day. "
        "Would another day work for you?"
    )


def misunderstood_correction_message() -> str:
    return (
        "Sorry, I didn't understand what needs changing. "
        "You can say the service, registration, day, time, or name."
    )


def fallback_snapshot(
    retry_count: int,
    silence_count: int,
    awaiting: str,
) -> dict:
    """
    Safe diagnostic data for Render logs.
    """
    return {
        "retry_count": int(retry_count or 0),
        "silence_count": int(silence_count or 0),
        "awaiting": clean(awaiting),
        "should_end": should_end_after_retry(
            retry_count=retry_count,
            silence_count=silence_count,
        ),
    }