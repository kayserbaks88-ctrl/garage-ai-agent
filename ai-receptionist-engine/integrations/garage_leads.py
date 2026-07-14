from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


TIMEZONE = ZoneInfo("Europe/London")
SHEET_ID = os.getenv("GARAGE_LEADS_SHEET_ID", "").strip()
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
TAB = "Garage Leads"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def clean(value) -> str:
    return str(value or "").strip()


def clean_phone(phone: str) -> str:
    return (
        clean(phone)
        .replace("whatsapp:", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def clean_registration(reg: str) -> str:
    return clean(reg).replace(" ", "").replace("-", "").upper()


def _credentials_info() -> dict:
    if not SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing")
    try:
        return json.loads(SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError:
        return json.loads(SERVICE_ACCOUNT_JSON.replace("\\n", "\n"))


def get_service():
    if not SHEET_ID:
        raise ValueError("GARAGE_LEADS_SHEET_ID is missing")
    creds = Credentials.from_service_account_info(_credentials_info(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def row_to_lead(row) -> dict:
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


def get_lead_rows() -> list[list[str]]:
    result = get_service().spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{TAB}!A:J",
    ).execute()
    return result.get("values", [])


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

    get_service().spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"{TAB}!A:J",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()
    return row_to_lead(values)


def find_customer_by_phone(phone: str):
    target = clean_phone(phone)
    if not target:
        return None

    try:
        rows = get_lead_rows()
    except Exception as error:
        print("CUSTOMER LOOKUP ERROR:", repr(error))
        return None

    matches = [
        row_to_lead(row)
        for row in rows[1:]
        if clean_phone(row_to_lead(row)["phone"]) == target
    ]
    if not matches:
        return None

    latest = matches[-1]
    latest["previous_visits"] = len(matches)
    return latest


def get_customer_history(phone: str, limit: int = 5) -> list[dict]:
    target = clean_phone(phone)
    if not target:
        return []
    try:
        rows = get_lead_rows()
    except Exception as error:
        print("CUSTOMER HISTORY ERROR:", repr(error))
        return []

    matches = [
        row_to_lead(row)
        for row in rows[1:]
        if clean_phone(row_to_lead(row)["phone"]) == target
    ]
    return matches[-limit:]
