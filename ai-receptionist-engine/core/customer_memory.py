from __future__ import annotations

from integrations.garage_leads import find_customer_by_phone


def load_customer_memory(phone: str) -> dict:
    try:
        customer = find_customer_by_phone(phone)
    except Exception as error:
        print("CUSTOMER MEMORY ERROR:", repr(error))
        customer = None

    if not customer:
        return {
            "found": False,
            "name": "",
            "vehicle_reg": "",
            "previous_visits": 0,
        }

    return {
        "found": True,
        "name": str(customer.get("name") or "").strip(),
        "vehicle_reg": str(customer.get("vehicle_reg") or "").strip().upper(),
        "previous_visits": int(customer.get("previous_visits") or 0),
    }
