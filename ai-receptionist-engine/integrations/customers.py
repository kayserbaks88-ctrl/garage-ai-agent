from integrations.staff_sheets import sheet_get, sheet_append


def get_customers():
    return sheet_get("Customers", "A1:G1000")


def add_customer(customer, contact_name="", phone="", email="", invoice_frequency="", hourly_rate="", notes=""):
    values = [[
        customer,
        contact_name,
        phone,
        email,
        invoice_frequency,
        hourly_rate,
        notes,
    ]]

    sheet_append("Customers", "A1:G1000", values)


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