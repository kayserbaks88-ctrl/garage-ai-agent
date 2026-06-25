import os
import base64
import requests

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


def download_twilio_photo(url):
    response = requests.get(
        url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=20,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "image/jpeg")

    if "png" in content_type:
        filename = "job-photo.png"
    else:
        filename = "job-photo.jpg"

    encoded = base64.b64encode(response.content).decode("utf-8")

    return {
        "filename": filename,
        "content": encoded,
    }


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
    photo_urls = []

    if "Photos:" in notes:
        parts = notes.split("Photos:")
        notes_only = parts[0].strip()
        photo_text = parts[1].strip()
        photo_urls = [
            line.strip()
            for line in photo_text.splitlines()
            if line.strip().startswith("http")
        ]
    else:
        notes_only = notes

    attachments = []

    for index, url in enumerate(photo_urls, start=1):
        try:
            attachment = download_twilio_photo(url)
            attachment["filename"] = f"job-photo-{index}.jpg"
            attachments.append(attachment)
        except Exception as e:
            print("PHOTO DOWNLOAD ERROR:", repr(e))

    payload = {
        "from": "Quote Builder <onboarding@resend.dev>",
        "to": [OWNER_EMAIL],
        "subject": f"🔥 New Quote Request - {job_type}",
        "text": f"""
New Quote Request

Name: {name}
Phone: {phone.replace("whatsapp:", "")}

Project: {job_type}
Location/Postcode: {postcode}
Job Size: {job_size}
Budget: {budget}
Timeline: {timeline}

Notes:
{notes_only}

Photos attached: {len(attachments)}
""",
    }

    if attachments:
        payload["attachments"] = attachments

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    print("RESEND STATUS:", response.status_code)
    print("RESEND RESPONSE:", response.text)

    response.raise_for_status()