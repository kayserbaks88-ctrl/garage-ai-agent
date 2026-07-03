from datetime import datetime

from integrations.staff_sheets import get_rows


def todays_summary():
    rows = get_rows()

    today = datetime.now().strftime("%Y-%m-%d")

    total_hours = 0
    employees = set()
    completed = 0

    for row in rows[1:]:
        row = row + [""] * 9

        if row[0] != today:
            continue

        employees.add(row[1])

        try:
            total_hours += float(row[6] or 0)
        except:
            pass

        if row[7].lower() == "completed":
            completed += 1

    return {
        "date": today,
        "employees": len(employees),
        "completed": completed,
        "hours": round(total_hours, 2),
    }


def weekly_summary():
    rows = get_rows()

    total_hours = 0
    completed = 0
    employees = set()
    sites = set()

    for row in rows[1:]:
        row = row + [""] * 9

        employees.add(row[1])

        if row[3]:
            sites.add(row[3])

        try:
            total_hours += float(row[6] or 0)
        except:
            pass

        if row[7].lower() == "completed":
            completed += 1

    return {
        "employees": len(employees),
        "sites": len(sites),
        "completed": completed,
        "hours": round(total_hours, 2),
    }


def owner_report():
    today = todays_summary()
    week = weekly_summary()

    return f"""
📊 Workforce Report

TODAY
Employees Worked: {today['employees']}
Jobs Completed: {today['completed']}
Hours Worked: {today['hours']}

THIS WEEK
Employees: {week['employees']}
Sites Worked: {week['sites']}
Completed Jobs: {week['completed']}
Hours Worked: {week['hours']}
""".strip()