from __future__ import annotations

from trimtech.integrations.dvla import (
    clean_registration,
    format_registration,
    is_plausible_registration,
    lookup_vehicle,
    safely_lookup_vehicle,
    vehicle_confirmation_question,
)

__all__ = [
    "clean_registration",
    "format_registration",
    "is_plausible_registration",
    "lookup_vehicle",
    "safely_lookup_vehicle",
    "vehicle_confirmation_question",
]