from __future__ import annotations

from datetime import datetime


BUSINESS_NAME = "TrimTech Garage"


def _format_date_time(start_dt: datetime) -> tuple[str, str]:
    date_text = start_dt.strftime("%A %-d %B")
    time_text = start_dt.strftime("%-I:%M %p").lower()

    return date_text, time_text


def appointment_reminder_24h(
    customer_name: str,
    service_label: str,
    registration: str,
    start_dt: datetime,
) -> str:
    date_text, time_text = _format_date_time(start_dt)

    return (
        f"Hi {customer_name} 👋\n\n"
        f"Just a reminder that your {service_label} for "
        f"{registration} is booked for {date_text} at {time_text}.\n\n"
        "If you need to reschedule or cancel, please call us.\n\n"
        f"Thanks,\n{BUSINESS_NAME} 🚗"
    )


def appointment_reminder_2h(
    customer_name: str,
    service_label: str,
    registration: str,
    start_dt: datetime,
) -> str:
    _, time_text = _format_date_time(start_dt)

    return (
        f"Hi {customer_name} 👋\n\n"
        f"Your {service_label} appointment for {registration} "
        f"is today at {time_text}.\n\n"
        "We look forward to seeing you.\n\n"
        f"{BUSINESS_NAME} 🚗"
    )


def appointment_follow_up(
    customer_name: str,
    service_label: str,
    registration: str,
) -> str:
    return (
        f"Hi {customer_name} 👋\n\n"
        f"Thank you for choosing {BUSINESS_NAME} for the "
        f"{service_label} on {registration}.\n\n"
        "We hope everything went well. If you need anything else, "
        "please get in touch.\n\n"
        f"Thanks,\n{BUSINESS_NAME} 🚗"
    )


def review_request(
    customer_name: str,
    review_url: str = "",
) -> str:
    message = (
        f"Hi {customer_name} 👋\n\n"
        f"Thank you for visiting {BUSINESS_NAME}.\n\n"
        "We would really appreciate a quick review about your experience."
    )

    if review_url:
        message += f"\n\nLeave a review here:\n{review_url}"

    message += f"\n\nThanks,\n{BUSINESS_NAME} ⭐"

    return message


def mot_due_reminder(
    customer_name: str,
    registration: str,
    due_date: datetime,
) -> str:
    due_text = due_date.strftime("%A %-d %B %Y")

    return (
        f"Hi {customer_name} 👋\n\n"
        f"Your MOT for {registration} is due on {due_text}.\n\n"
        "Book early to secure a convenient appointment.\n\n"
        f"Thanks,\n{BUSINESS_NAME} 🚗"
    )


def service_due_reminder(
    customer_name: str,
    registration: str,
) -> str:
    return (
        f"Hi {customer_name} 👋\n\n"
        f"It may be time to arrange the next service for {registration}.\n\n"
        "Please contact us to book a suitable date and time.\n\n"
        f"Thanks,\n{BUSINESS_NAME} 🔧"
    )