import os
from zoneinfo import ZoneInfo

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "TrimTech Garage")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/London")
TIMEZONE = ZoneInfo(TIMEZONE_NAME)

# Single calendar for now
GARAGE_CALENDAR_ID = os.getenv("GARAGE_CALENDAR_ID", "")

SERVICES = {
    "mot": {
        "label": "MOT",
        "minutes": 60,
        "needs_reg": True,
        "needs_vehicle": True,
        "needs_notes": False,
    },
    "full_service": {
        "label": "Full Service",
        "minutes": 120,
        "needs_reg": True,
        "needs_vehicle": True,
        "needs_notes": False,
    },
    "diagnostic": {
        "label": "Diagnostic Check",
        "minutes": 45,
        "needs_reg": True,
        "needs_vehicle": True,
        "needs_notes": True,
    },
    "oil_change": {
        "label": "Oil Change",
        "minutes": 30,
        "needs_reg": True,
        "needs_vehicle": True,
        "needs_notes": False,
    },
    "brake_check": {
        "label": "Brake Check",
        "minutes": 45,
        "needs_reg": True,
        "needs_vehicle": True,
        "needs_notes": True,
    },
}

SERVICE_ALIASES = {
    "mot": "mot",
    "m.o.t": "mot",
    "full service": "full_service",
    "major service": "full_service",
    "service": "full_service",
    "diagnostic": "diagnostic",
    "diagnostics": "diagnostic",
    "engine light": "diagnostic",
    "warning light": "diagnostic",
    "oil": "oil_change",
    "oil change": "oil_change",
    "brake": "brake_check",
    "brakes": "brake_check",
    "brake check": "brake_check",
}
