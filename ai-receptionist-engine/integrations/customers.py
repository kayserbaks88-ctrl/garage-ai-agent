from integrations.staff_sheets import get_service, STAFF_SHEET_ID


def get_customers():
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=STAFF_SHEET_ID,
        range="Customers!A:G",
    ).execute()
    return result.get("values", [])


def add_customer(customer, contact_name="", phone="", email="", invoice_frequency="", hourly_rate="", notes=""):
    service = get_service()

    values = [[
        customer,
        contact_name,
        phone,
        email,
        invoice_frequency,
        hourly_rate,
        notes,
    ]]

    service.spreadsheets().values().append(
        spreadsheetId=STAFF_SHEET_ID,
        range="Customers!A:G",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def find_customer(customer_name):
    rows = get_customers()
    search = customer_name.lower().strip()

    for row in rows[1:]:
        row = row + [""] * 7
        if row[0].lower().strip() == search:
            return {
                "customer": row[0],
                "contact_name": row[1],
                "phone": row[2],
                "email": row[3],
                "invoice_frequency": row[4],
                "hourly_rate": row[5],
                "notes": row[6],
            }

    return None