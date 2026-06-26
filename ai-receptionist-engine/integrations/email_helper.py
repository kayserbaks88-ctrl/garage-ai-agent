import os
import base64
import requests

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


def extract_photo_urls(notes):
    if "Photos:" not in notes:
        return [], notes.strip()

    notes_part, photos_part = notes.split("Photos:", 1)

    urls = [
        line.strip()
        for line in photos_part.splitlines()
        if line.strip().startswith("http")
    ]

    return urls, notes_part.strip()


def download_photo(url, index):
    response = requests.get(
        url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=25,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "image/jpeg")

    if "png" in content_type:
        filename = f"job-photo-{index}.png"
    else:
        filename = f"job-photo-{index}.jpg"

    return {
        "filename": filename,
        "content": base64.b64encode(response.content).decode("utf-8"),
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
    photo_urls, clean_notes = extract_photo_urls(notes)

    attachments = []

    for index, url in enumerate(photo_urls, start=1):
        try:
            attachments.append(download_photo(url, index))
        except Exception as e:
            print("PHOTO ATTACH ERROR:", repr(e))

    payload = {
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

Photos attached: {len(attachments)}
Photos received: {len(photo_urls)}
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
        timeout=40,
    )

    print("RESEND STATUS:", response.status_code)
    print("RESEND RESPONSE:", response.text)

    response.raise_for_status()