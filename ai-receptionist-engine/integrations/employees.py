from integrations.staff_sheets import get_service, STAFF_SHEET_ID


def clean_phone(phone):
    return (
        (phone or "")
        .replace("whatsapp:", "")
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )


def get_employees():
    service = get_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range="'Employees'!A1:F1000",
    ).execute()

    return result.get("values", [])


def find_employee_by_phone(phone):
    rows = get_employees()
    search_phone = clean_phone(phone)

    for row in rows[1:]:
        row = row + [""] * 6

        sheet_phone = clean_phone(row[1])

        if sheet_phone == search_phone:
            return {
                "name": row[0],
                "phone": row[1],
                "role": row[2] or "Staff",
                "hourly_rate": row[3],
                "status": row[4] or "Active",
                "note": row[5],
            }

    return None


def add_employee(name, phone="", role="Staff", hourly_rate="", status="Active", note=""):
    service = get_service()

    values = [[
        name,
        clean_phone(phone),
        role,
        hourly_rate,
        status,
        note,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range="'Employees'!A1:F1000",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()

    return True