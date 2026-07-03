from integrations.staff_sheets import get_rows
from integrations.employees import get_employees


def calculate_payroll():
    rows = get_rows()
    employees = get_employees()

    rates = {}

    # Build hourly rate lookup
    for row in employees[1:]:
        row = row + [""] * 6

        try:
            rates[row[0]] = float(row[3] or 0)
        except:
            rates[row[0]] = 0

    payroll = {}

    for row in rows[1:]:
        row = row + [""] * 9

        if row[7].lower() != "completed":
            continue

        employee = row[1]

        try:
            hours = float(row[6] or 0)
        except:
            hours = 0

        if employee not in payroll:
            payroll[employee] = {
                "hours": 0,
                "rate": rates.get(employee, 0),
            }

        payroll[employee]["hours"] += hours

    for employee in payroll:
        payroll[employee]["pay"] = round(
            payroll[employee]["hours"] *
            payroll[employee]["rate"], 2
        )

    return payroll


def payroll_report():
    payroll = calculate_payroll()

    if not payroll:
        return "No payroll data available."

    message = "💷 Payroll Summary\n\n"

    grand_total = 0

    for employee, data in payroll.items():
        grand_total += data["pay"]

        message += (
            f"👤 {employee}\n"
            f"Hours: {data['hours']:.2f}\n"
            f"Rate: £{data['rate']:.2f}\n"
            f"Pay: £{data['pay']:.2f}\n\n"
        )

    message += f"💰 Total Payroll: £{grand_total:.2f}"

    return message