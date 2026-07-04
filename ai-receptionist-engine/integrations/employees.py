from integrations.staff_sheets import get_service, STAFF_SHEET_ID


def get_employees():
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range="Employees!A1:F1000",
    ).execute()
    return result.get("values", [])


def add_employee(name, phone="", role="", hourly_rate="", notes=""):
    service = get_service()

    values = [[
        name,
        phone.replace("whatsapp:", ""),
        role,
        hourly_rate,
        "Active",
        notes,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range="Employees!A1:F1000",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def find_employee_by_phone(phone):
    clean_phone = phone.replace("whatsapp:", "")
    rows = get_employees()

    for row in rows[1:]:
        row = row + [""] * 6
        if row[1] == clean_phone:
            return {
                "name": row[0],
                "phone": row[1],
                "role": row[2],
                "hourly_rate": row[3],
                "status": row[4],
                "notes": row[5],
            }

    return None