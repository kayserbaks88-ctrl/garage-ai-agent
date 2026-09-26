from __future__ import annotations

import math


def distance_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, a2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = a2 - a1, math.radians(lon2 - lon1)
    hav = math.sin(dlat / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, hav))))


def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return distance_metres(lat1, lon1, lat2, lon2) / 1609.344
