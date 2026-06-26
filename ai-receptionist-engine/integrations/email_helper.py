import os
import requests

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")


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
    photo_count = notes.count("https://api.twilio.com")

    clean_notes = notes.split("Photos:")[0].strip()

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": "Quote Builder <onboarding@resend.dev>",
            "to": [OWNER_EMAIL],
            "subject": f"🔥 New Quote Request - {job_type}",
            "text": f"""
New Quote Request

Name: {name}
Phone: {phone.replace("whatsapp:", "")}

Project: {job_type}
Location: {postcode}
Job Size: {job_size}
Budget: {budget}
Timeline: {timeline}

Notes:
{clean_notes}

Photos received: {photo_count}
""",
        },
        timeout=30,
    )

    print("RESEND STATUS:", response.status_code)
    print("RESEND RESPONSE:", response.text)

    response.raise_for_status()