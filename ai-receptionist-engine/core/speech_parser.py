import re
from datetime import date, datetime, timedelta
from typing import Any

import dateparser

from integrations.garage_config import (
    SERVICE_ALIASES,
    SERVICES,
    TIMEZONE,
)


DAY_WORDS = {
    "today",
    "tomorrow",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}

PERIOD_WORDS = {
    "morning": "morning",
    "in the morning": "morning",
    "before lunch": "morning",
    "afternoon": "afternoon",
    "in the afternoon": "afternoon",
    "after lunch": "afternoon",
    "evening": "evening",
    "in the evening": "evening",
}

YES_WORDS = {
    "yes",
    "yeah",
    "yep",
    "correct",
    "that's right",
    "thats right",
    "right",
    "sure",
    "please",
    "okay",
    "ok",
}

NO_WORDS = {
    "no",
    "nope",
    "incorrect",
    "that's wrong",
    "thats wrong",
    "wrong vehicle",
    "not that one",
}

NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

LETTER_WORDS = {
    "alpha": "A",
    "bravo": "B",
    "charlie": "C",
    "delta": "D",
    "echo": "E",
    "foxtrot": "F",
    "golf": "G",
    "hotel": "H",
    "india": "I",
    "juliet": "J",
    "kilo": "K",
    "lima": "L",
    "mike": "M",
    "november": "N",
    "oscar": "O",
    "papa": "P",
    "quebec": "Q",
    "romeo": "R",
    "sierra": "S",
    "tango": "T",
    "uniform": "U",
    "victor": "V",
    "whiskey": "W",
    "x-ray": "X",
    "xray": "X",
    "yankee": "Y",
    "zulu": "Z",
}


def clean_text(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )


def normalise_text(value: Any) -> str:
    return clean_text(value).lower()


def extract_confirmation(text: str) -> str:
    """
    Returns:
        "yes"
        "no"
        ""
    """
    normalised = normalise_text(text)

    if not normalised:
        return ""

    if any(phrase in normalised for phrase in NO_WORDS):
        return "no"

    if any(phrase in normalised for phrase in YES_WORDS):
        return "yes"

    return ""


def extract_service_key(text: str) -> str:
    """
    Convert natural service wording into a key from SERVICES.

    Examples:
        "I need an MOT" -> "mot"
        "engine warning light" -> "diagnostic"
        "oil and filter change" -> "oil_change"
    """
    normalised = normalise_text(text)

    if not normalised:
        return ""

    # Check longest aliases first so "full service" wins over "service".
    aliases = sorted(
        SERVICE_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    for alias, service_key in aliases:
        if alias in normalised and service_key in SERVICES:
            return service_key

    extra_rules = [
        (
            [
                "clutch",
                "gearbox",
                "won't start",
                "wont start",
                "not starting",
                "lost power",
                "limp mode",
                "strange noise",
            ],
            "diagnostic",
        ),
        (
            [
                "brake noise",
                "brakes squeaking",
                "brakes grinding",
                "brake pads",
                "brake discs",
            ],
            "brake_check",
        ),
        (
            [
                "oil filter",
                "engine oil",
            ],
            "oil_change",
        ),
    ]

    for phrases, service_key in extra_rules:
        if any(phrase in normalised for phrase in phrases):
            if service_key in SERVICES:
                return service_key

    return ""


def service_label(service_key: str) -> str:
    service = SERVICES.get(service_key or "")
    return service.get("label", "") if service else ""


def _replace_spoken_characters(text: str) -> str:
    words = normalise_text(text).split()
    converted = []

    for word in words:
        cleaned_word = word.strip(".,!?-")

        if cleaned_word in NUMBER_WORDS:
            converted.append(NUMBER_WORDS[cleaned_word])
            continue

        if cleaned_word in LETTER_WORDS:
            converted.append(LETTER_WORDS[cleaned_word])
            continue

        # Single spoken letters such as "b", "c", "d".
        if len(cleaned_word) == 1 and cleaned_word.isalpha():
            converted.append(cleaned_word.upper())
            continue

        # Already contains letters or digits.
        if re.fullmatch(r"[a-zA-Z0-9]+", cleaned_word):
            converted.append(cleaned_word.upper())

    return "".join(converted)


def format_registration(registration: str) -> str:
    compact = re.sub(
        r"[^A-Z0-9]",
        "",
        str(registration or "").upper(),
    )

    # Most modern UK registrations are 7 characters.
    if len(compact) == 7:
        return f"{compact[:4]} {compact[4:]}"

    return compact


def extract_registration(text: str) -> str:
    """
    Attempt to recognise a UK registration from normal or spoken text.

    Examples:
        "AB12 CDE"
        "A B one two C D E"
        "alpha bravo one two charlie delta echo"
    """
    raw = clean_text(text).upper()

    if not raw:
        return ""

    # Normal written registration.
    candidates = re.findall(
        r"\b[A-Z]{1,3}\s?\d{1,4}\s?[A-Z]{0,3}\b",
        raw,
    )

    for candidate in candidates:
        compact = re.sub(r"[^A-Z0-9]", "", candidate)

        if 5 <= len(compact) <= 8:
            return format_registration(compact)

    # Registration spoken one character at a time.
    spoken = _replace_spoken_characters(text)

    if 5 <= len(spoken) <= 8:
        has_letter = bool(re.search(r"[A-Z]", spoken))
        has_number = bool(re.search(r"\d", spoken))

        if has_letter and has_number:
            return format_registration(spoken)

    return ""


def extract_name(text: str) -> str:
    """
    Extract a caller's name when they introduce themselves.

    Examples:
        "My name is John Smith"
        "It's Sarah"
        "This is David"
    """
    cleaned = clean_text(text)

    patterns = [
        r"\bmy name is\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bi am called\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bi'm called\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bthis is\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bit'?s\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bi am\s+([a-zA-ZÀ-ÿ' -]{2,50})",
        r"\bi'm\s+([a-zA-ZÀ-ÿ' -]{2,50})",
    ]

    stop_words = {
        "calling",
        "looking",
        "trying",
        "after",
        "at",
        "from",
        "here",
        "having",
        "needing",
    }

    for pattern in patterns:
        match = re.search(
            pattern,
            cleaned,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        candidate = match.group(1).strip(" .,!")

        # Stop when the rest of the request begins.
        candidate = re.split(
            r"\b(?:and|because|about|for|with|i need|i want|my car)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()

        words = candidate.split()

        if not words:
            continue

        if words[0].lower() in stop_words:
            continue

        if len(words) <= 4:
            return " ".join(
                word.capitalize()
                for word in words
            )

    return ""


def extract_preferred_period(text: str) -> str:
    normalised = normalise_text(text)

    for phrase, period in sorted(
        PERIOD_WORDS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if phrase in normalised:
            return period

    return ""


def extract_date_phrase(text: str) -> str:
    """
    Return the part of the sentence that describes a date.
    """
    normalised = normalise_text(text)

    patterns = [
        r"\bday after tomorrow\b",
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bthis\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:today|tomorrow)\b",
        r"\bnext week\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\b",
        r"\b(?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?\b",
        r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalised)

        if match:
            return match.group(0)

    return ""


def parse_requested_date(
    text: str,
    now: datetime | None = None,
) -> date | None:
    """
    Convert natural UK date wording into a date.
    """
    now = now or datetime.now(TIMEZONE)
    phrase = extract_date_phrase(text)

    if not phrase:
        return None

    if phrase == "day after tomorrow":
        return (now + timedelta(days=2)).date()

    if phrase == "next week":
        days_until_monday = (7 - now.weekday()) % 7

        if days_until_monday == 0:
            days_until_monday = 7

        return (now + timedelta(days=days_until_monday)).date()

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

    # If someone says today's weekday after the time has passed,
    # dateparser can occasionally return today. Prefer the future.
    if parsed.date() < now.date():
        return None

    return parsed.date()


def extract_time_phrase(text: str) -> str:
    normalised = normalise_text(text)

    patterns = [
        r"\b(?:at|around|about)?\s*"
        r"(?:[01]?\d|2[0-3])"
        r"(?::[0-5]\d|\.[0-5]\d)?"
        r"\s*(?:a\.?m\.?|p\.?m\.?)\b",
        r"\b(?:at|around|about)\s+"
        r"(?:[01]?\d|2[0-3])"
        r"(?::[0-5]\d|\.[0-5]\d)?\b",
        r"\b(?:nine|ten|eleven|twelve|one|two|three|four|five)"
        r"(?:\s+thirty|\s+fifteen|\s+forty five)?"
        r"\s*(?:in the morning|in the afternoon|a\.?m\.?|p\.?m\.?)?\b",
        r"\b(?:midday|noon)\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            normalised,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).strip()

    return ""


def parse_requested_time(
    text: str,
    requested_date: date | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """
    Convert a spoken time into a timezone-aware datetime.

    A period such as "morning" alone is not an exact time and therefore
    returns None. The period is returned separately by parse_speech().
    """
    now = now or datetime.now(TIMEZONE)
    
    normalised_time_text = (
        normalise_text(text)
        .replace("a.m.", "am")
        .replace("p.m.", "pm")
        .replace("a.m", "am")
        .replace("p.m", "pm")
    )

    phrase = extract_time_phrase(
    normalised_time_text
)

    if not phrase:
        return None

    base_date = requested_date or now.date()

    parsed = dateparser.parse(
        phrase,
        settings={
            "TIMEZONE": str(TIMEZONE),
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "DATE_ORDER": "DMY",
            "RELATIVE_BASE": datetime.combine(
                base_date,
                now.time(),
                tzinfo=TIMEZONE,
            ),
        },
        languages=["en"],
    )

    if not parsed:
        return None

    return datetime.combine(
        base_date,
        parsed.astimezone(TIMEZONE).time().replace(
            second=0,
            microsecond=0,
        ),
        tzinfo=TIMEZONE,
    )


def extract_issue(text: str) -> str:
    """
    Keep the caller's own description as the issue when it contains
    useful mechanical context.
    """
    cleaned = clean_text(text)
    normalised = cleaned.lower()

    issue_terms = [
        "noise",
        "rattle",
        "squeak",
        "grinding",
        "clutch",
        "brake",
        "warning light",
        "engine light",
        "won't start",
        "wont start",
        "not starting",
        "lost power",
        "oil leak",
        "leak",
        "overheating",
        "smoke",
        "vibration",
        "pulling",
        "tyre",
        "battery",
        "gearbox",
        "exhaust",
        "problem",
        "issue",
        "fix",
        "repair",
    ]

    if any(term in normalised for term in issue_terms):
        return cleaned

    return ""


def parse_speech(
    text: str,
    now: datetime | None = None,
) -> dict:
    """
    Extract all useful details available in one piece of speech.

    Empty values mean the information was not confidently found.
    """
    now = now or datetime.now(TIMEZONE)
    cleaned = clean_text(text)

    requested_date = parse_requested_date(
        cleaned,
        now=now,
    )

    requested_datetime = parse_requested_time(
        cleaned,
        requested_date=requested_date,
        now=now,
    )

    return {
        "raw_text": cleaned,
        "name": extract_name(cleaned),
        "service_key": extract_service_key(cleaned),
        "registration": extract_registration(cleaned),
        "requested_date": requested_date,
        "requested_datetime": requested_datetime,
        "date_phrase": extract_date_phrase(cleaned),
        "time_phrase": extract_time_phrase(cleaned),
        "preferred_period": extract_preferred_period(cleaned),
        "issue": extract_issue(cleaned),
        "confirmation": extract_confirmation(cleaned),
    }


def merge_parsed_details(
    existing: dict,
    parsed: dict,
) -> dict:
    """
    Safely merge newly extracted details into conversation memory.
    Empty values do not erase information already collected.
    """
    result = dict(existing or {})

    fields = [
        "name",
        "service_key",
        "registration",
        "requested_date",
        "requested_datetime",
        "date_phrase",
        "time_phrase",
        "preferred_period",
        "issue",
    ]

    for field in fields:
        value = parsed.get(field)

        if value not in (None, "", []):
            result[field] = value

    return result