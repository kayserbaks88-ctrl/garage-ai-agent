import os
import json
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")


def get_service():
    creds_info = json.loads(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    )

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
        ]
    )

    return build("sheets", "v4", credentials=creds)


def add_lead(
    name,
    phone,
    email,
    enquiry,
    budget,
    postcode,
    notes,
):
    service = get_service()

    values = [[
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        name,
        phone,
        email,
        enquiry,
        budget,
        postcode,
        notes,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="Sheet1!A:H",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()