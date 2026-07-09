import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


TIMEZONE = ZoneInfo("Europe/London")
GARAGE_LEADS_SHEET_ID = os.getenv("GARAGE_LEADS_SHEET_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_service():
    if not GARAGE_LEADS_SHEET_ID:
        raise ValueError("GARAGE_LEADS_SHEET_ID is missing")

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")

    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)

    return build("sheets", "v4", credentials=creds)


def clean(value):
    return (value or "").strip()


def sheet_append(tab_name, values):
    service = get_service()

    service.spreadsheets().values().append(
        spreadsheetId=GARAGE_LEADS_SHEET_ID,
        range=f"{tab_name}!A:H",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()


def save_garage_lead(
    name="",
    phone="",
    vehicle_reg="",
    service_needed="",
    issue="",
    preferred_time="",
    notes="",
):
    now = datetime.now(TIMEZONE)

    values = [
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M"),
        clean(name),
        clean(phone),
        clean(vehicle_reg).upper(),
        clean(service_needed),
        clean(issue),
        clean(preferred_time),
        clean(notes),
        "New",
    ]

    sheet_append("Garage Leads", values)

    return {
        "date": values[0],
        "time": values[1],
        "name": values[2],
        "phone": values[3],
        "vehicle_reg": values[4],
        "service_needed": values[5],
        "issue": values[6],
        "preferred_time": values[7],
        "notes": values[8],
        "status": values[9],
    }