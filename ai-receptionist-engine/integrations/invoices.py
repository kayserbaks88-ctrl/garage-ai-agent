from datetime import datetime

from integrations.staff_sheets import get_rows
from integrations.customers import get_customers


def calculate_invoice_totals():
    rows = get_rows()
    customers = get_customers()

    rates = {}

    for row in customers[1:]:
        row = row + [""] * 7
        customer = row[0]

        try:
            rates[customer.lower()] = float(row[5] or 0)
        except:
            rates[customer.lower()] = 0

    invoices = {}

    for row in rows[1:]:
        row = row + [""] * 9

        if row[7].lower() != "completed":
            continue

        site = row[3]

        try:
            hours = float(row[6] or 0)
        except:
            hours = 0

        customer_key = site.lower()

        if customer_key not in invoices:
            invoices[customer_key] = {
                "customer": site,
                "hours": 0,
                "rate": rates.get(customer_key, 0),
            }

        invoices[customer_key]["hours"] += hours

    for key in invoices:
        invoices[key]["total"] = round(
            invoices[key]["hours"] * invoices[key]["rate"],
            2,
        )

    return invoices


def invoice_report():
    invoices = calculate_invoice_totals()

    if not invoices:
        return "No completed work found for invoices yet."

    message = "🧾 Invoice Summary\n\n"
    grand_total = 0

    for _, data in invoices.items():
        grand_total += data["total"]

        message += (
            f"🏢 {data['customer']}\n"
            f"Hours: {data['hours']:.2f}\n"
            f"Rate: £{data['rate']:.2f}\n"
            f"Invoice Total: £{data['total']:.2f}\n\n"
        )

    message += f"💰 Total To Invoice: £{grand_total:.2f}"

    return message


def create_invoice_number():
    return "INV-" + datetime.now().strftime("%Y%m%d%H%M")