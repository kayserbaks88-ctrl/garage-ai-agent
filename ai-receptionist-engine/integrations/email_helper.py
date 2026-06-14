import os
import requests

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
    requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "from": "Quote Builder <onboarding@resend.dev>",
            "to": [OWNER_EMAIL],
            "subject": f"🔥 New Quote Request - {job_type}",
            "text": f"""
Name: {name}
Phone: {phone}

Project: {job_type}
Postcode: {postcode}
Job Size: {job_size}
Budget: {budget}
Timeline: {timeline}

Notes:
{notes}
""",
        },
        timeout=20,
    )