import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TIMEZONE = ZoneInfo("Europe/London")
STAFF_SHEET_ID = os.getenv("STAFF_SHEET_ID", "").strip()


def get_service():
    creds_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    return build("sheets", "v4", credentials=creds)


def add_check_in(employee, phone, site, notes=""):
    service = get_service()
    now = datetime.now(TIMEZONE)

    values = [[
        now.strftime("%Y-%m-%d"),
        employee,
        phone.replace("whatsapp:", ""),
        site,
        now.strftime("%H:%M"),
        "",
        "",
        "On Site",
        notes,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range="A:I",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def get_rows():
    service = get_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range="A:I",
    ).execute()

    return result.get("values", [])


def update_check_out(phone, site=None):
    service = get_service()
    rows = get_rows()
    now = datetime.now(TIMEZONE)

    clean_phone = phone.replace("whatsapp:", "")

    for idx in range(len(rows) - 1, 0, -1):
        row = rows[idx] + [""] * 9

        row_phone = row[2]
        row_site = row[3]
        check_in = row[4]
        check_out = row[5]
        status = row[7]

        if row_phone == clean_phone and status == "On Site" and not check_out:
            if site and site.lower() not in row_site.lower():
                continue

            try:
                start_dt = datetime.strptime(
                    f"{row[0]} {check_in}",
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=TIMEZONE)

                hours = round((now - start_dt).total_seconds() / 3600, 2)
            except Exception:
                hours = ""

            row_number = idx + 1

            service.spreadsheets().values().update(
                spreadsheetId=STAFF_SHEET_ID,
                range=f"Sheet1!F{row_number}:H{row_number}",
                valueInputOption="RAW",
                body={"values": [[now.strftime("%H:%M"), hours, "Completed"]]},
            ).execute()

            return row_site, hours

    return None, None


def list_on_site():
    rows = get_rows()
    active = []

    for row in rows[1:]:
        row = row + [""] * 9
        if row[7] == "On Site":
            active.append({
                "employee": row[1],
                "site": row[3],
                "check_in": row[4],
            })

    return active