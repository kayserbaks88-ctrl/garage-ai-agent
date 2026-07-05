def route_intent(text):
    t = (text or "").lower().strip()

    if not t:
        return "unknown"

    if t in ["hi", "hello", "hey", "yo", "morning", "good morning", "afternoon", "evening", "help"]:
        return "greeting"

    if any(x in t for x in [
        "who is on site", "who's on site", "whos on site",
        "who is working", "who's working", "whos working",
        "who is clocked in", "who's clocked in",
        "who is checked in", "who's checked in",
        "anyone on site", "staff on site", "current staff",
        "who is on shift", "who's on shift"
    ]):
        return "on_site"

    if any(x in t for x in [
        "payroll", "wages", "staff pay", "pay staff",
        "how much do i owe", "what do i owe",
        "wage summary", "pay summary", "total payroll",
        "hours and pay"
    ]):
        return "payroll"

    if any(x in t for x in [
        "invoice", "invoices", "billing", "bill", "bills",
        "how much should i invoice", "what should i invoice",
        "what do i need to invoice", "invoice summary",
        "billing summary", "money to invoice"
    ]):
        return "invoices"

    if any(x in t for x in [
        "report", "reports", "summary", "stats", "dashboard",
        "today report", "weekly report", "work summary",
        "shift summary", "how did we do", "what happened today"
    ]):
        return "report"

    if any(x in t for x in [
        "finish", "finished", "done", "done for today",
        "clock me out", "clock out",
        "check me out", "check out", "checkout",
        "sign me out", "sign out",
        "end shift", "end my shift",
        "end snift",
        "i'm finished", "im finished", "i am finished",
        "i'm done", "im done", "i am done",
        "leaving site", "leaving now", "finished work"
    ]):
        return "finish"

    if any(x in t for x in [
        "clock me in", "clock in",
        "check me in", "check in", "checking in",
        "sign me in", "sign in",
        "start", "started", "starting",
        "i'm at", "im at", "i am at",
        "arrived", "i've arrived", "ive arrived",
        "just got to", "got to",
        "working at", "on site at",
        "at "
    ]):
        return "start"

    return "unknown"