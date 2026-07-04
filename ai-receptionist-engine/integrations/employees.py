from integrations.staff_sheets import sheet_get, sheet_append


def get_employees():
    return sheet_get("Employees", "A1:F1000")


def add_employee(name, phone="", role="", hourly_rate="", notes=""):
    clean_phone = phone.replace("whatsapp:", "")

    values = [[
        name,
        clean_phone,
        role,
        hourly_rate,
        "Active",
        notes,
    ]]

    sheet_append("Employees", "A1:F1000", values)


def find_employee_by_phone(phone):
    clean_phone = phone.replace("whatsapp:", "")
    rows = get_employees()

    for row in rows[1:]:
        row = row + [""] * 6

        if row[1].strip() == clean_phone:
            return {
                "name": row[0],
                "phone": row[1],
                "role": row[2],
                "hourly_rate": row[3],
                "status": row[4],
                "notes": row[5],
            }

    return None