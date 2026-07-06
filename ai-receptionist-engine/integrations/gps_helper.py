import math
from integrations.staff_sheets import sheet_get


def normalise_site_name(value):
    return (value or "").strip().lower()


def get_sites():
    rows = sheet_get("Sites", "A1:D1000")
    sites = []

    for row in rows[1:]:
        row = row + [""] * 4

        site = row[0].strip()
        latitude = row[1].strip()
        longitude = row[2].strip()
        radius = row[3].strip()

        if not site or not latitude or not longitude:
            continue

        try:
            sites.append({
                "site": site,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "radius": float(radius or 100),
            })
        except ValueError:
            continue

    return sites


def find_site(site_name):
    search = normalise_site_name(site_name)

    for site in get_sites():
        current = normalise_site_name(site["site"])

        if current == search:
            return site

        if search in current or current in search:
            return site

    return None


def calculate_distance_metres(lat1, lon1, lat2, lon2):
    radius_earth = 6371000

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))

    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(radius_earth * c)


def verify_location(site_name, latitude, longitude):
    site = find_site(site_name)

    if not site:
        return {
            "verified": False,
            "reason": "site_not_found",
            "message": f"Site '{site_name}' is not set up with GPS yet.",
            "gps_text": "⚠️ Site GPS missing",
        }

    distance = calculate_distance_metres(
        latitude,
        longitude,
        site["latitude"],
        site["longitude"],
    )

    verified = distance <= site["radius"]

    if verified:
        return {
            "verified": True,
            "reason": "verified",
            "site": site["site"],
            "distance": distance,
            "radius": site["radius"],
            "message": f"✅ GPS verified ({distance}m from {site['site']})",
            "gps_text": f"✅ {distance}m",
        }

    return {
        "verified": False,
        "reason": "too_far",
        "site": site["site"],
        "distance": distance,
        "radius": site["radius"],
        "message": f"❌ You're {distance}m away from {site['site']}. Please move closer to site.",
        "gps_text": f"❌ {distance}m",
    }