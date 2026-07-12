import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


TIMEZONE = ZoneInfo("Europe/London")

GARAGE_LEADS_SHEET_ID = os.getenv(
    "GARAGE_LEADS_SHEET_ID",
    "",
).strip()

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "",
).strip()

SHEET_TAB = "Garage Leads"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def clean(value):
    return str(value or "").strip()


def clean_phone(phone):
    return (
        clean(phone)
        .replace("whatsapp:", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def clean_registration(registration):
    return (
        clean(registration)
        .replace(" ", "")
        .replace("-", "")
        .upper()
    )


def _load_service_account_json():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is missing"
        )

    try:
        return json.loads(
            GOOGLE_SERVICE_ACCOUNT_JSON
        )

    except json.JSONDecodeError:
        fixed_json = (
            GOOGLE_SERVICE_ACCOUNT_JSON
            .replace("\\n", "\n")
        )

        return json.loads(fixed_json)


def get_service():
    if not GARAGE_LEADS_SHEET_ID:
        raise ValueError(
            "GARAGE_LEADS_SHEET_ID is missing"
        )

    credentials_info = (
        _load_service_account_json()
    )

    credentials = (
        Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES,
        )
    )

    return build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def row_to_lead(row):
    row = list(row or []) + [""] * 10

    return {
        "date": clean(row[0]),
        "time": clean(row[1]),
        "name": clean(row[2]),
        "phone": clean(row[3]),
        "vehicle_reg": clean(row[4]).upper(),
        "service_needed": clean(row[5]),
        "issue": clean(row[6]),
        "preferred_time": clean(row[7]),
        "notes": clean(row[8]),
        "status": clean(row[9]),
    }


def get_lead_rows():
    service = get_service()

    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=GARAGE_LEADS_SHEET_ID,
            range=f"{SHEET_TAB}!A:J",
        )
        .execute()
    )

    return result.get("values", [])


def sheet_append(tab_name, values):
    service = get_service()

    (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=GARAGE_LEADS_SHEET_ID,
            range=f"{tab_name}!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [values],
            },
        )
        .execute()
    )


def save_garage_lead(
    name="",
    phone="",
    vehicle_reg="",
    service_needed="",
    issue="",
    preferred_time="",
    notes="",
    status="New",
):
    now = datetime.now(TIMEZONE)

    values = [
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M"),
        clean(name),
        clean_phone(phone),
        clean_registration(vehicle_reg),
        clean(service_needed),
        clean(issue),
        clean(preferred_time),
        clean(notes),
        clean(status) or "New",
    ]

    sheet_append(
        SHEET_TAB,
        values,
    )

    return row_to_lead(values)


def find_customer_by_phone(phone):
    """
    Return the most recent lead matching the caller's
    phone number.

    Returns None when no previous customer is found.
    """
    target_phone = clean_phone(phone)

    if not target_phone:
        return None

    try:
        rows = get_lead_rows()

    except Exception as error:
        print(
            "GARAGE CUSTOMER LOOKUP ERROR:",
            repr(error),
        )
        return None

    matches = []

    for row in rows[1:]:
        lead = row_to_lead(row)

        if clean_phone(
            lead.get("phone")
        ) == target_phone:
            matches.append(lead)

    if not matches:
        return None

    latest = matches[-1]

    return {
        "name": latest.get("name", ""),
        "phone": latest.get("phone", ""),
        "vehicle_reg": latest.get(
            "vehicle_reg",
            "",
        ),
        "service_needed": latest.get(
            "service_needed",
            "",
        ),
        "issue": latest.get("issue", ""),
        "preferred_time": latest.get(
            "preferred_time",
            "",
        ),
        "notes": latest.get("notes", ""),
        "status": latest.get("status", ""),
        "previous_visits": len(matches),
    }


def get_customer_history(phone, limit=5):
    """
    Return the caller's most recent enquiries,
    newest last.
    """
    target_phone = clean_phone(phone)

    if not target_phone:
        return []

    try:
        rows = get_lead_rows()

    except Exception as error:
        print(
            "GARAGE HISTORY LOOKUP ERROR:",
            repr(error),
        )
        return []

    matches = []

    for row in rows[1:]:
        lead = row_to_lead(row)

        if clean_phone(
            lead.get("phone")
        ) == target_phone:
            matches.append(lead)

    return matches[-limit:]


def get_latest_registration(phone):
    customer = find_customer_by_phone(phone)

    if not customer:
        return ""

    return clean_registration(
        customer.get("vehicle_reg")
    )


def customer_exists(phone):
    return (
        find_customer_by_phone(phone)
        is not None
    )