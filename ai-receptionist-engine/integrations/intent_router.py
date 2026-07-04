def route_intent(text):
    t = (text or "").lower().strip()

    greetings = ["hi", "hello", "hey", "yo", "morning", "afternoon", "evening"]
    if t in greetings:
        return "greeting"

    if any(x in t for x in ["who is on site", "who's on site", "who is working", "who's working", "on site"]):
        return "on_site"

    if any(x in t for x in ["payroll", "wages", "pay", "owe staff"]):
        return "payroll"

    if any(x in t for x in ["invoice", "invoices", "bill", "billing"]):
        return "invoices"

    if any(x in t for x in ["report", "summary", "stats"]):
        return "report"

    if any(x in t for x in ["finish", "finished", "done", "clock out", "check out", "checkout"]):
        return "finish"

    if any(x in t for x in ["start", "arrived", "i'm at", "im at", "clock in", "check in", "checking in"]):
        return "start"

    return "unknown"