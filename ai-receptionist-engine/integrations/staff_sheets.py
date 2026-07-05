import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

TIMEZONE = ZoneInfo("Europe/London")
STAFF_SHEET_ID = os.getenv("STAFF_SHEET_ID", "").strip()
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_service():
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not STAFF_SHEET_ID:
        raise ValueError("STAFF_SHEET_ID is missing")

    if not raw_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")

    creds_info = json.loads(raw_json)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES,
    )

    return build("sheets", "v4", credentials=creds)


def sheet_get(tab_name, cell_range):
    service = get_service()
    full_range = f"'{tab_name}'!{cell_range}"

    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range=full_range,
    ).execute()

    return result.get("values", [])


def sheet_append(tab_name, cell_range, values):
    service = get_service()
    full_range = f"'{tab_name}'!{cell_range}"

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range=full_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()


def sheet_update(tab_name, cell_range, values):
    service = get_service()
    full_range = f"'{tab_name}'!{cell_range}"

    service.spreadsheets().values().update(
        spreadsheetId=STAFF_SHEET_ID,
        range=full_range,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def clean_phone(phone):
    return (
        (phone or "")
        .replace("whatsapp:", "")
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )


def get_rows():
    return sheet_get("Checkins", "A1:I1000")


def get_active_check_in(phone):
    rows = get_rows()
    target_phone = clean_phone(phone)

    for index in range(len(rows) - 1, 0, -1):
        row = rows[index] + [""] * 9

        row_phone = clean_phone(row[2])
        status = row[7].strip().lower()
        check_out = row[5].strip()

        if row_phone == target_phone and status == "on site" and not check_out:
            return {
                "row_number": index + 1,
                "date": row[0],
                "name": row[1],
                "employee": row[1],
                "phone": row[2],
                "site": row[3],
                "check_in": row[4],
                "check_out": row[5],
                "hours": row[6],
                "status": row[7],
                "notes": row[8],
            }

    return None


def add_check_in(name=None, phone="", site="", notes="", employee=None):
    if employee and not name:
        name = employee

    active = get_active_check_in(phone)

    if active:
        return False, active

    now = datetime.now(TIMEZONE)

    values = [[
        now.strftime("%Y-%m-%d"),
        name or "Staff",
        clean_phone(phone),
        site,
        now.strftime("%H:%M"),
        "",
        "",
        "On Site",
        notes,
    ]]

    sheet_append("Checkins", "A1:I1000", values)

    return True, {
        "name": name or "Staff",
        "employee": name or "Staff",
        "site": site,
        "check_in": now.strftime("%H:%M"),
    }


def update_check_out(phone, site=None):
    active = get_active_check_in(phone)

    if not active:
        return None, None

    if site:
        wanted = site.lower().strip()
        current = active["site"].lower().strip()

        if wanted and wanted not in current and current not in wanted:
            return None, None

    now = datetime.now(TIMEZONE)

    try:
        start = datetime.strptime(
            f"{active['date']} {active['check_in']}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=TIMEZONE)

        hours = round((now - start).total_seconds() / 3600, 2)
    except Exception:
        hours = ""

    row_number = active["row_number"]

    sheet_update(
        "Checkins",
        f"F{row_number}:H{row_number}",
        [[
            now.strftime("%H:%M"),
            hours,
            "Completed",
        ]],
    )

    return active["site"], hours


def list_on_site():
    rows = get_rows()
    people = []

    for row in rows[1:]:
        row = row + [""] * 9

        status = row[7].strip().lower()
        check_out = row[5].strip()

        if status == "on site" and not check_out:
            people.append({
                "date": row[0],
                "name": row[1],
                "employee": row[1],
                "phone": row[2],
                "site": row[3],
                "check_in": row[4],
                "status": row[7],
                "notes": row[8],
            })

    return people