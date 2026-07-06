from integrations.staff_sheets import sheet_get, sheet_append, clean_phone


def get_employees():
    return sheet_get("Employees", "A1:F1000")


def find_employee_by_phone(phone):
    rows = get_employees()
    target_phone = clean_phone(phone)

    for row in rows[1:]:
        row = row + [""] * 6

        if clean_phone(row[1]) == target_phone:
            return {
                "name": row[0],
                "phone": row[1],
                "role": row[2] or "Staff",
                "hourly_rate": row[3],
                "status": row[4] or "Active",
                "notes": row[5],
            }

    return None


def add_employee(name, phone="", role="Staff", hourly_rate="", notes=""):
    values = [[
        name,
        clean_phone(phone),
        role,
        hourly_rate,
        "Active",
        notes,
    ]]

    sheet_append("Employees", "A1:F1000", values)
    return True