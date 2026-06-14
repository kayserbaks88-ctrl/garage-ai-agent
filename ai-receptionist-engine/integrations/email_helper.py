import os
import smtplib
from email.message import EmailMessage

OWNER_EMAIL = os.getenv("OWNER_EMAIL")


def send_quote_notification(
    name,
    phone,
    job_type,
    postcode,
    job_size,
    budget,
    timeline,
    notes,
):
    msg = EmailMessage()

    msg["Subject"] = f"🔥 New Quote Request - {job_type}"
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = OWNER_EMAIL

    msg.set_content(
        f"""
New Quote Request

Name: {name}
Phone: {phone}

Project: {job_type}
Postcode: {postcode}
Job Size: {job_size}
Budget: {budget}
Timeline: {timeline}

Notes:
{notes}
"""
    )

    print("EMAIL_FROM =", os.getenv("EMAIL_FROM"))
    print("OWNER_EMAIL =", OWNER_EMAIL)
    print("CONNECTING TO GMAIL...")

    try:
        print("CONNECTING TO GMAIL...")

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()

            print("LOGGING IN...")

        smtp.login(
            os.getenv("EMAIL_FROM"),
            os.getenv("EMAIL_PASSWORD")
        )

        print("SENDING EMAIL...")

        smtp.send_message(msg)

        print("EMAIL SENT")

    except Exception as e:
        print("EMAIL HELPER ERROR:", repr(e))