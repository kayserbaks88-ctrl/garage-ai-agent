from __future__ import annotations

import os

from trimtech.businesses.garage.services import GARAGE_SERVICES
from trimtech.core.business import BusinessConfig, BusinessFeatures


BUSINESS_CONFIG = BusinessConfig(
    business_id=os.getenv(
        "TRIMTECH_BUSINESS_ID",
        "trimtech-garage",
    ),
    business_type="garage",
    business_name=os.getenv(
        "TRIMTECH_BUSINESS_NAME",
        "TrimTech Garage",
    ),
    timezone_name=os.getenv(
        "GARAGE_TIMEZONE",
        "Europe/London",
    ),
    currency_code="GBP",
    currency_symbol="£",
    features=BusinessFeatures(
        dashboard=True,
        bookings=True,
        crm=True,
        reminders=True,
        revenue=True,
        reports=True,
        analytics=True,
        ai_activity=True,
        voice_agent=True,
        whatsapp=True,
        email=True,
        sms=False,
        vehicles=True,
        dvla=True,
        mot_reminders=True,
        service_reminders=True,
        staff=False,
        sites=False,
        invoices=False,
        payroll=False,
    ),
    services=GARAGE_SERVICES,
    metadata={
        "industry": "automotive",
        "vehicle_lookup_provider": "dvla",
        "calendar_provider": "google_calendar",
        "voice_provider": "vapi",
        "confirmation_channel": "whatsapp",
        "dashboard_title": "Garage Performance",
        "booking_label": "Appointment",
        "customer_label": "Customer",
        "vehicle_label": "Vehicle",
    },
)