import json
import os

from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from business_configs.lead_gen import LEADS_CALENDAR_ID


def get_service():

    creds_info = json.loads(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    )

    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )

    return build("calendar", "v3", credentials=creds)


def create_lead(session, phone):

    service = get_service()

    body = {
        "summary": f"NEW LEAD - {session.get('name','Unknown')}",
        "description": (
            f"Type: {session.get('enquiry')}\n\n"
            f"Name: {session.get('name')}\n"
            f"Email: {session.get('email')}\n"
            f"Phone: {phone}\n"
            f"Postcode: {session.get('postcode')}\n"
            f"Budget: {session.get('budget')}\n"
            f"Notes: {session.get('notes')}"
        )
    }
    
    body = {
        "summary": f"NEW LEAD - {session.get('name', 'Unknown')}",
        "description": "...",
        "start": {
        "date": datetime.now().date().isoformat()
        },
        "end": {
        "date": (datetime.now().date() + timedelta(days=1)).isoformat()
        }
    }

    service.events().insert(
        calendarId=LEADS_CALENDAR_ID,
        body=body
    ).execute()