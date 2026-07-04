def route_intent(text):
    t = (text or "").lower().strip()

    greetings = ["hi", "hello", "hey", "yo", "morning", "afternoon", "evening"]
    if t in greetings:
        return "greeting"

    if any(x in t for x in [
        "who is on site", "who's on site", "who is working", "who's working",
        "who is there", "who's there", "who is clocked in", "who's clocked in",
        "who is checked in", "who's checked in", "who is on shift",
        "on site now", "currently on site", "staff on site"
    ]):
        return "on_site"

    if any(x in t for x in [
        "payroll", "wages", "staff pay", "pay staff", "how much do i owe",
        "what do i owe", "pay summary", "wage summary", "total payroll",
        "hours and pay"
    ]):
        return "payroll"

    if any(x in t for x in [
        "invoice", "invoices", "billing", "bill", "bills", "what should i bill",
        "how much should i invoice", "what do i need to invoice",
        "invoice summary", "billing summary", "money to invoice"
    ]):
        return "invoices"

    if any(x in t for x in [
        "report", "reports", "summary", "stats", "dashboard",
        "today report", "weekly report", "work summary", "shift summary",
        "how did we do", "what happened today"
    ]):
        return "report"

    if any(x in t for x in [
        "finish", "finished", "done", "done for today", "clock me out",
        "clock out", "check me out", "check out", "checkout",
        "sign me out", "sign out", "end shift", "end my shift",
        "i'm finished", "im finished", "i am finished",
        "i'm done", "im done", "i am done", "leaving site",
        "leaving now", "finished work"
    ]):
        return "finish"

    if any(x in t for x in [
        "start", "started", "clock me in", "clock in", "check me in",
        "check in", "checking in", "sign me in", "sign in",
        "i'm at", "im at", "i am at", "arrived", "i've arrived",
        "ive arrived", "just got to", "got to", "working at",
        "on site at", "starting at"
    ]):
        return "start"

    return "unknown"