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

from datetime import datetime


def get_rows():
    return sheet_get("Checkins", "A1:I1000")


def add_check_in(name, phone, site, notes=""):
    clean_phone = phone.replace("whatsapp:", "")
    now = datetime.now(TIMEZONE)

    values = [[
        now.strftime("%Y-%m-%d"),
        name,
        clean_phone,
        site,
        now.strftime("%H:%M"),
        "",
        "",
        "On Site",
        notes,
    ]]

    sheet_append("Checkins", "A1:I1000", values)


def get_active_check_in(phone):
    rows = get_rows()
    clean_phone = phone.replace("whatsapp:", "")

    for idx in range(len(rows) - 1, 0, -1):
        row = rows[idx] + [""] * 9

        if row[2].strip() == clean_phone and row[7].strip().lower() == "on site":
            return {
                "row_number": idx + 1,
                "date": row[0],
                "name": row[1],
                "phone": row[2],
                "site": row[3],
                "check_in": row[4],
                "check_out": row[5],
                "hours": row[6],
                "status": row[7],
                "notes": row[8],
            }

    return None   

def update_check_out(row_number):
    service = get_service()
    now = datetime.now(TIMEZONE)

    rows = get_rows()
    row = rows[row_number - 1] + [""] * 9

    check_in_time = row[4]

    hours = ""
    try:
        check_in_dt = datetime.strptime(
            f"{row[0]} {check_in_time}",
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TIMEZONE)

        hours = round((now - check_in_dt).total_seconds() / 3600, 2)
    except Exception:
        hours = ""

    values = [[
        now.strftime("%H:%M"),
        hours,
        "Completed",
    ]]

    service.spreadsheets().values().update(
        spreadsheetId=STAFF_SHEET_ID,
        range=f"Checkins!F{row_number}:H{row_number}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    return hours