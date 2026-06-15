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
Size: {job_size}
Postcode: {postcode}
Budget: {budget}
Timeline: {timeline}

Notes:
{notes}
""",
        },
        timeout=20,
    )

    print("RESEND STATUS:", response.status_code)
    print("RESEND RESPONSE:", response.text)

    response.raise_for_status()