import os
from zoneinfo import ZoneInfo

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "TrimTech Leads")

TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/London")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

LEADS_CALENDAR_ID = os.getenv("LEADS_CALENDAR_ID", "")

LEAD_TYPES = {
    "estate_agent": {
        "label": "Estate Agent Lead"
    },
    "car_dealer": {
        "label": "Car Dealer Lead"
    },
    "tradesman": {
        "label": "Tradesman Lead"
    },
    "mortgage": {
        "label": "Mortgage Lead"
    }
}