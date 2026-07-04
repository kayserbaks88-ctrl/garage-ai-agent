from integrations.staff_sheets import get_rows


def calculate_invoice_totals():
    rows = get_rows()
    invoices = {}

    for row in rows[1:]:
        row = row + [""] * 9

        date = row[0]
        employee = row[1]
        site = row[3]
        hours = row[6]
        status = row[7]

        if status.lower().strip() != "completed":
            continue

        try:
            hours_float = float(hours)
        except Exception:
            continue

        if not site:
            site = "Unknown Site"

        rate = 20.0
        total = hours_float * rate

        if site not in invoices:
            invoices[site] = {
                "customer": site,
                "hours": 0,
                "rate": rate,
                "total": 0,
            }

        invoices[site]["hours"] += hours_float
        invoices[site]["total"] += total

    return invoices


def invoice_report():
    invoices = calculate_invoice_totals()

    if not invoices:
        return "No completed work found for invoices yet."

    message = "🧾 Invoice Summary\n\n"
    grand_total = 0

    for site, data in invoices.items():
        grand_total += data["total"]

        message += (
            f"🏢 {site}\n"
            f"Hours: {data['hours']:.2f}\n"
            f"Rate: £{data['rate']:.2f}\n"
            f"Invoice Total: £{data['total']:.2f}\n\n"
        )

    message += f"💰 Total Invoices: £{grand_total:.2f}"

    return message