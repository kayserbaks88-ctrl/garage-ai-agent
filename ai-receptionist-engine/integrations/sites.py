from integrations.staff_sheets import sheet_get, sheet_append


def get_sites():
    return sheet_get("Sites", "A1:F1000")


def add_site(site, customer="", address="", contact="", phone="", notes=""):
    values = [[
        site,
        customer,
        address,
        contact,
        phone,
        notes,
    ]]

    sheet_append("Sites", "A1:F1000", values)


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
                "contact": row[3],
                "phone": row[4],
                "notes": row[5],
            }

    return None