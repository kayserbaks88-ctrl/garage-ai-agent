from integrations.staff_sheets import get_service, STAFF_SHEET_ID


def get_sites():
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range="Sites!A1:F1000",
    ).execute()
    return result.get("values", [])


def add_site(site, customer="", address="", required_staff="", start_time="", notes=""):
    service = get_service()

    values = [[
        site,
        customer,
        address,
        required_staff,
        start_time,
        notes,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range="Sites!A1:F1000",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def find_site(site_name):
    rows = get_sites()
    search = site_name.lower().strip()

    for row in rows[1:]:
        row = row + [""] * 6
        if row[0].lower().strip() == search:
            return {
                "site": row[0],
                "customer": row[1],
                "address": row[2],
                "required_staff": row[3],
                "start_time": row[4],
                "notes": row[5],
            }

    return None