from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

import dateparser

from integrations.garage_config import SERVICE_ALIASES, SERVICES, TIMEZONE


NUMBER_WORDS = {
    "zero": "0", "oh": "0",
    "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

LETTER_WORDS = {
    "alpha": "A", "bravo": "B", "charlie": "C", "delta": "D",
    "echo": "E", "foxtrot": "F", "golf": "G", "hotel": "H",
    "india": "I", "juliet": "J", "juliett": "J", "kilo": "K",
    "lima": "L", "mike": "M", "november": "N", "oscar": "O",
    "papa": "P", "quebec": "Q", "romeo": "R", "sierra": "S",
    "tango": "T", "uniform": "U", "victor": "V", "whiskey": "W",
    "xray": "X", "x-ray": "X", "yankee": "Y", "zulu": "Z",
}

YES_PHRASES = {
    "yes", "yeah", "yep", "correct", "that's right", "thats right",
    "right", "okay", "ok", "it is", "that's correct", "thats correct",
}

NO_PHRASES = {
    "no", "nope", "incorrect", "wrong", "that's wrong", "thats wrong",
    "not correct", "different vehicle", "not that one",
}

PERIODS = {
    "morning": "morning",
    "in the morning": "morning",
    "before lunch": "morning",
    "afternoon": "afternoon",
    "in the afternoon": "afternoon",
    "after lunch": "afternoon",
    "evening": "evening",
    "in the evening": "evening",
}

HOUR_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalise_text(value: Any) -> str:
    return clean_text(value).lower()


def extract_confirmation(text: str) -> str:
    t = normalise_text(text)
    if not t:
        return ""

    for phrase in sorted(NO_PHRASES, key=len, reverse=True):
        if t == phrase or phrase in t:
            return "no"

    for phrase in sorted(YES_PHRASES, key=len, reverse=True):
        if t == phrase or phrase in t:
            return "yes"

    return ""


def extract_service_key(text: str) -> str:
    t = normalise_text(text)
    if not t:
        return ""

    aliases = sorted(SERVICE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, key in aliases:
        if alias in t and key in SERVICES:
            return key

    extra = [
        (("clutch", "gearbox", "won't start", "wont start", "not starting",
          "lost power", "limp mode", "engine noise", "car noise"), "diagnostic"),
        (("brake noise", "squeaking brakes", "grinding brakes", "brake pads",
          "brake discs"), "brake_check"),
        (("oil filter", "engine oil"), "oil_change"),
    ]
    for phrases, key in extra:
        if any(p in t for p in phrases) and key in SERVICES:
            return key
    return ""


def format_registration(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if len(compact) == 7:
        return f"{compact[:4]} {compact[4:]}"
    return compact


def _spoken_characters(text: str) -> str:
    tokens = re.findall(r"[A-Za-z]+|\d+", normalise_text(text))
    result: list[str] = []

    ignored = {
        "registration", "reg", "number", "plate", "is", "it", "the",
        "my", "vehicle", "car", "please",
    }

    for token in tokens:
        if token in ignored:
            continue
        if token in NUMBER_WORDS:
            result.append(NUMBER_WORDS[token])
        elif token in LETTER_WORDS:
            result.append(LETTER_WORDS[token])
        elif len(token) == 1 and token.isalpha():
            result.append(token.upper())
        elif token.isdigit():
            result.extend(list(token))
        elif re.fullmatch(r"[a-z0-9]{2,7}", token):
            result.extend(list(token.upper()))

    return "".join(result)


def extract_registration(text: str) -> str:
    """
    V1 accepts the normal modern UK format only: two letters, two digits,
    three letters. Partial transcripts are rejected before DVLA.
    """
    raw = clean_text(text).upper()

    direct = re.search(r"\b([A-Z]{2})\s*(\d{2})\s*([A-Z]{3})\b", raw)
    if direct:
        return format_registration("".join(direct.groups()))

    spoken = _spoken_characters(text)
    if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]{3}", spoken):
        return format_registration(spoken)

    return ""


def registration_is_valid(value: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]{3}", compact))


def extract_name(text: str) -> str:
    cleaned = clean_text(text)
    patterns = [
        r"\bmy name is\s+([A-Za-zÀ-ÿ' -]{2,60})",
        r"\bthis is\s+([A-Za-zÀ-ÿ' -]{2,60})",
        r"\bi am called\s+([A-Za-zÀ-ÿ' -]{2,60})",
        r"\bi'm called\s+([A-Za-zÀ-ÿ' -]{2,60})",
        r"\bit'?s\s+([A-Za-zÀ-ÿ' -]{2,60})",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if not match:
            continue
        candidate = re.split(
            r"\b(?:and|because|about|for|with|i need|i want|my car)\b",
            match.group(1),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,!")
        words = candidate.split()
        if 1 <= len(words) <= 4:
            return " ".join(word.capitalize() for word in words)
    return ""


def clean_direct_name(text: str) -> str:
    candidate = clean_text(text).strip(" .,!?:;")
    candidate = re.sub(
        r"^(?:my name is|this is|i am|i'm|its|it's)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    words = candidate.split()
    if not 1 <= len(words) <= 4:
        return ""
    if any(char.isdigit() for char in candidate):
        return ""
    return " ".join(word.capitalize() for word in words)


def extract_preferred_period(text: str) -> str:
    t = normalise_text(text)
    for phrase, period in sorted(PERIODS.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in t:
            return period
    return ""


def extract_date_phrase(text: str) -> str:
    t = normalise_text(text)
    patterns = [
        r"\bday after tomorrow\b",
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bthis\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:today|tomorrow)\b",
        r"\bnext week\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|"
        r"july|august|september|october|november|december)\b",
        r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            return match.group(0)
    return ""


def parse_requested_date(text: str, now: datetime | None = None) -> date | None:
    now = now or datetime.now(TIMEZONE)
    phrase = extract_date_phrase(text)
    if not phrase:
        return None

    if phrase == "day after tomorrow":
        return (now + timedelta(days=2)).date()

    parsed = dateparser.parse(
        phrase,
        settings={
            "TIMEZONE": str(TIMEZONE),
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "DATE_ORDER": "DMY",
            "RELATIVE_BASE": now,
        },
        languages=["en"],
    )
    if not parsed:
        return None
    parsed = parsed.astimezone(TIMEZONE)
    return parsed.date() if parsed.date() >= now.date() else None


def _normalise_clock_text(text: str) -> str:
    return (
        normalise_text(text)
        .replace("a.m.", "am")
        .replace("p.m.", "pm")
        .replace("a.m", "am")
        .replace("p.m", "pm")
        .replace("o'clock", "")
        .replace("oclock", "")
    )


def parse_requested_time(
    text: str,
    requested_date: date | None,
    now: datetime | None = None,
) -> datetime | None:
    if not requested_date:
        return None

    now = now or datetime.now(TIMEZONE)
    t = _normalise_clock_text(text)

    # Numeric: 5 pm, 5:30 p.m., 17:00
    match = re.search(r"\b(\d{1,2})(?::|\.)(\d{2})\s*(am|pm)?\b", t)
    if not match:
        match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t)

    if match:
        hour = int(match.group(1))
        minute = 0
        period = ""

        if len(match.groups()) == 3:
            minute = int(match.group(2) or 0)
            period = match.group(3) or ""
        else:
            period = match.group(2) or ""

        if minute > 59:
            return None
        if period:
            if not 1 <= hour <= 12:
                return None
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
        elif not 0 <= hour <= 23:
            return None

        return datetime.combine(requested_date, time(hour=hour, minute=minute), tzinfo=TIMEZONE)

    # Word hours: "five in the afternoon", "ten thirty in the morning"
    word_pattern = (
        r"\b(" + "|".join(HOUR_WORDS.keys()) + r")"
        r"(?:\s+(fifteen|thirty|forty five))?"
        r"(?:\s+(?:in the\s+)?(morning|afternoon|evening))?\b"
    )
    match = re.search(word_pattern, t)
    if match:
        hour = HOUR_WORDS[match.group(1)]
        minute_word = match.group(2) or ""
        minute = {"fifteen": 15, "thirty": 30, "forty five": 45}.get(minute_word, 0)
        period = match.group(3) or extract_preferred_period(t)

        if period in {"afternoon", "evening"} and hour != 12:
            hour += 12
        elif period == "morning" and hour == 12:
            hour = 0
        elif not period:
            # Without a period, choose a sensible garage-hour interpretation.
            if hour < 8:
                hour += 12

        return datetime.combine(requested_date, time(hour=hour, minute=minute), tzinfo=TIMEZONE)

    if "midday" in t or "noon" in t:
        return datetime.combine(requested_date, time(hour=12), tzinfo=TIMEZONE)

    return None


def extract_issue(text: str) -> str:
    cleaned = clean_text(text)
    t = cleaned.lower()
    terms = (
        "noise", "rattle", "squeak", "grinding", "clutch", "brake",
        "warning light", "engine light", "won't start", "wont start",
        "not starting", "lost power", "oil leak", "leak", "overheating",
        "smoke", "vibration", "pulling", "tyre", "battery", "gearbox",
        "exhaust", "problem", "issue", "fix", "repair",
    )
    return cleaned if any(term in t for term in terms) else ""


def parse_speech(
    text: str,
    requested_date: date | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(TIMEZONE)
    cleaned = clean_text(text)
    found_date = parse_requested_date(cleaned, now=now) or requested_date
    found_time = parse_requested_time(cleaned, requested_date=found_date, now=now)

    return {
        "raw_text": cleaned,
        "name": extract_name(cleaned),
        "service_key": extract_service_key(cleaned),
        "registration": extract_registration(cleaned),
        "requested_date": found_date if extract_date_phrase(cleaned) else None,
        "requested_datetime": found_time,
        "date_phrase": extract_date_phrase(cleaned),
        "preferred_period": extract_preferred_period(cleaned),
        "issue": extract_issue(cleaned),
        "confirmation": extract_confirmation(cleaned),
    }
