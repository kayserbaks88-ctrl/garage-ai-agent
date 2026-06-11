import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TIMEZONE = ZoneInfo("Europe/London")
SHEET_ID = os.getenv("SHEET_ID", "").strip()


def get_service():
    creds_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    return build("sheets", "v4", credentials=creds)


def add_quote_request(
    name,
    phone,
    job_type,
    postcode,
    job_size,
    budget,
    timeline,
    notes,
):
    service = get_service()

    values = [[
        datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M"),
        name,
        phone.replace("whatsapp:", ""),
        job_type,
        postcode,
        job_size,
        budget,
        timeline,
        notes,
        "New",
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="Sheet1!A:J",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()