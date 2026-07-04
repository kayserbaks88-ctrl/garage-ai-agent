import os
import json
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


TIMEZONE = ZoneInfo("Europe/London")

STAFF_SHEET_ID = os.getenv("STAFF_SHEET_ID", "").strip()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_service():
    if not STAFF_SHEET_ID:
        raise ValueError("STAFF_SHEET_ID is missing from environment variables")

    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing from environment variables")

    creds_info = json.loads(raw_json)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES,
    )

    return build("sheets", "v4", credentials=creds)


def sheet_get(tab_name, cell_range):
    service = get_service()
    full_range = f"{tab_name}!{cell_range}"

    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range=full_range,
    ).execute()

    return result.get("values", [])


def sheet_append(tab_name, cell_range, values):
    service = get_service()
    full_range = f"{tab_name}!{cell_range}"

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range=full_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()