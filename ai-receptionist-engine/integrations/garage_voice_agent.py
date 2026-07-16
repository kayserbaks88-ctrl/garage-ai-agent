from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from twilio.twiml.voice_response import Gather, VoiceResponse

from core.booking_engine import (
    build_slot_offer,
    check_requested_slot,
    create_from_session,
    match_slot,
    service_label,
)
from core.conversation_engine import (
    add_retry,
    apply_parsed,
    create_session,
    first_name,
    next_required_stage,
    record_message,
    reset_retries,
    set_stage,
    summary_text,
)
from core.customer_memory import load_customer_memory
from core.dvla_helper import (
    safely_lookup_vehicle,
    vehicle_confirmation_question,
)
from core.fallback_engine import (
    final_message,
    retry_message,
    should_end,
)
from core.speech_parser import (
    clean_direct_name,
    extract_confirmation,
    extract_registration,
    parse_requested_date,
    parse_requested_time,
    parse_speech,
    registration_is_valid,
)
from integrations.garage_config import BUSINESS_NAME, TIMEZONE


VOICE_NAME = "Polly.Emma"
VOICE_LANGUAGE = "en-GB"
PROCESS_URL = "/voice/process"

SESSIONS: dict[str, dict] = {}


LETTER_NAMES = {
    "a": "A",
    "ay": "A",
    "eh": "A",
    "alpha": "A",

    "b": "B",
    "bee": "B",
    "be": "B",
    "bravo": "B",

    "c": "C",
    "cee": "C",
    "sea": "C",
    "charlie": "C",

    "d": "D",
    "dee": "D",
    "delta": "D",

    "e": "E",
    "ee": "E",
    "echo": "E",

    "f": "F",
    "ef": "F",
    "foxtrot": "F",

    "g": "G",
    "gee": "G",
    "golf": "G",

    "h": "H",
    "aitch": "H",
    "haitch": "H",
    "hotel": "H",

    "i": "I",
    "eye": "I",
    "india": "I",

    "j": "J",
    "jay": "J",
    "juliet": "J",
    "juliett": "J",

    "k": "K",
    "kay": "K",
    "kilo": "K",

    "l": "L",
    "el": "L",
    "lima": "L",

    "m": "M",
    "em": "M",
    "mike": "M",

    "n": "N",
    "en": "N",
    "november": "N",

    "o": "O",
    "oh": "O",
    "oscar": "O",

    "p": "P",
    "pee": "P",
    "papa": "P",

    "q": "Q",
    "cue": "Q",
    "queue": "Q",
    "quebec": "Q",

    "r": "R",
    "are": "R",
    "ar": "R",
    "romeo": "R",

    "s": "S",
    "ess": "S",
    "sierra": "S",

    "t": "T",
    "tee": "T",
    "tea": "T",
    "tango": "T",

    "u": "U",
    "you": "U",
    "uniform": "U",

    "v": "V",
    "vee": "V",
    "victor": "V",

    "w": "W",
    "doubleyou": "W",
    "double-you": "W",
    "whiskey": "W",

    "x": "X",
    "ex": "X",
    "xray": "X",
    "x-ray": "X",

    "y": "Y",
    "why": "Y",
    "wye": "Y",
    "yankee": "Y",

    "z": "Z",
    "zed": "Z",
    "zee": "Z",
    "zulu": "Z",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def _listen(message: str) -> str:
    response = VoiceResponse()

    gather = Gather(
        input="speech",
        action=PROCESS_URL,
        method="POST",
        speech_timeout="auto",
        timeout=6,
        language=VOICE_LANGUAGE,
        action_on_empty_result=True,
    )

    gather.say(
        message,
        voice=VOICE_NAME,
        language=VOICE_LANGUAGE,
    )

    response.append(gather)
    response.redirect(PROCESS_URL, method="POST")

    return str(response)


def _end(message: str) -> str:
    response = VoiceResponse()

    response.say(
        message,
        voice=VOICE_NAME,
        language=VOICE_LANGUAGE,
    )

    response.hangup()
    return str(response)


def _spoken_registration(registration: str) -> str:
    compact = re.sub(
        r"[^A-Z0-9]",
        "",
        clean(registration).upper(),
    )

    return " ".join(compact)


def _parse_spelled_name(text: str) -> str:
    """
    Converts speech transcripts such as:

    B A K S
    bee ay kay ess
    B. A. K. S.
    bravo alpha kilo sierra

    into:

    Baks
    """
    raw = clean(text).lower()

    if not raw:
        return ""

    raw = raw.replace(".", " ")
    raw = raw.replace(",", " ")
    raw = raw.replace("-", " ")
    raw = raw.replace("_", " ")

    raw = re.sub(
        r"\b(?:my name is|it is|it's|its|that is|"
        r"spelled|spelt|the spelling is)\b",
        " ",
        raw,
    )

    tokens = re.findall(r"[a-z]+", raw)

    letters: list[str] = []

    ignored_words = {
        "and",
        "then",
        "space",
        "please",
        "name",
        "first",
        "letter",
        "letters",
    }

    for token in tokens:
        if token in ignored_words:
            continue

        if token in LETTER_NAMES:
            letters.append(LETTER_NAMES[token])
            continue

        if len(token) == 1 and token.isalpha():
            letters.append(token.upper())
            continue

        # Twilio may combine individually spoken letters into one word.
        if (
            len(tokens) == 1
            and token.isalpha()
            and 2 <= len(token) <= 20
        ):
            return token.capitalize()

    if 2 <= len(letters) <= 20:
        return "".join(letters).capitalize()

    # Accept the caller repeating the whole name instead of spelling it.
    direct_name = clean_direct_name(text)

    if direct_name:
        return first_name(direct_name)

    return ""


def _prompt_for_stage(session: dict) -> str:
    stage = clean(session.get("stage"))

    prompts = {
        "service": (
            "What does your vehicle need help with? "
            "You can say M O T, full service, oil change, "
            "brakes, or diagnostic."
        ),
        "same_vehicle": (
            f"Is this booking for the same vehicle, registration "
            f"{_spoken_registration(session.get('previous_registration', ''))}?"
        ),
        "registration": (
            "What is the vehicle registration? "
            "Please say all seven characters slowly."
        ),
        "date": (
            "What day would you like the appointment?"
        ),
        "time": (
            "What time would suit you?"
        ),
        "name": (
            "May I take your name for the booking?"
        ),
        "confirm_name": (
            "Please spell your first name, one letter at a time."
        ),
        "correction": (
            "What would you like to change?"
        ),
    }

    return prompts.get(
        stage,
        "What would you like to do next?",
    )


def _new_session(
    call_sid: str,
    caller_number: str,
) -> dict:
    customer = load_customer_memory(caller_number)

    session = create_session(
        call_sid=call_sid,
        phone=caller_number,
        customer=customer,
    )

    # A remembered customer name does not need to be requested again.
    if session.get("name"):
        session["name_confirmed"] = True

    SESSIONS[call_sid] = session
    return session


def _get_session(
    call_sid: str,
    caller_number: str,
) -> dict:
    session = SESSIONS.get(call_sid)

    if session is None:
        session = _new_session(
            call_sid=call_sid,
            caller_number=caller_number,
        )

    return session


def _move_to_next_stage(
    session: dict,
    lead_message: str = "",
) -> str:
    next_stage = next_required_stage(session)
    set_stage(session, next_stage)
    reset_retries(session)

    if next_stage == "summary":
        message = summary_text(
            session,
            service_label(session.get("service_key", "")),
        )

        if lead_message:
            message = f"{lead_message} {message}"

        return _listen(message)

    prompt = _prompt_for_stage(session)

    if lead_message:
        prompt = f"{lead_message} {prompt}"

    return _listen(prompt)


def _retry(
    session: dict,
    silence: bool = False,
    custom_message: str = "",
) -> str:
    add_retry(session, silence=silence)

    if should_end(session):
        return _end(final_message(BUSINESS_NAME))

    message = custom_message or retry_message(
        stage=clean(session.get("stage")),
        retry_count=int(session.get("retry_count") or 0),
        silence=silence,
    )

    return _listen(message)


def handle_voice_start(
    call_sid: str,
    caller_number: str,
) -> str:
    session = _new_session(
        call_sid=call_sid,
        caller_number=caller_number,
    )

    remembered_name = first_name(session.get("name"))

    if remembered_name:
        greeting = (
            f"Hello {remembered_name}. "
            f"Thank you for calling {BUSINESS_NAME}. "
            "What does your vehicle need help with?"
        )
    else:
        greeting = (
            f"Thank you for calling {BUSINESS_NAME}. "
            "What does your vehicle need help with? "
            "You can say M O T, full service, oil change, "
            "brakes, or diagnostic."
        )

    return _listen(greeting)

# Backwards-compatible name
handle_incoming_call = handle_voice_start

def _handle_service(
    session: dict,
    speech_text: str,
) -> str:
    parsed = parse_speech(
        speech_text,
        requested_date=session.get("requested_date"),
    )

    apply_parsed(session, parsed)

    if not session.get("service_key"):
        return _retry(session)

    return _move_to_next_stage(session)


def _handle_same_vehicle(
    session: dict,
    speech_text: str,
) -> str:
    confirmation = extract_confirmation(speech_text)

    if confirmation == "yes":
        registration = clean(
            session.get("previous_registration")
        ).upper()

        session["registration"] = registration
        session["registration_confirmed"] = True

        result = safely_lookup_vehicle(registration)

        if result.get("success"):
            session["vehicle"] = result.get("vehicle") or {}
            session["vehicle_confirmed"] = False

            set_stage(session, "vehicle_confirm")
            reset_retries(session)

            return _listen(
                vehicle_confirmation_question(
                    session["vehicle"]
                )
            )

        # Continue even if DVLA is temporarily unavailable.
        session["vehicle"] = {
            "reg": registration,
            "registration": registration,
            "make_model": "Vehicle not confirmed",
        }
        session["vehicle_confirmed"] = True

        return _move_to_next_stage(session)

    if confirmation == "no":
        session["registration"] = ""
        session["registration_confirmed"] = False
        session["vehicle"] = {}
        session["vehicle_confirmed"] = False

        set_stage(session, "registration")
        reset_retries(session)

        return _listen(
            "No problem. What is the vehicle registration?"
        )

    return _retry(
        session,
        custom_message=(
            "Please say yes if it is the same vehicle, "
            "or no if it is a different vehicle."
        ),
    )


def _handle_registration(
    session: dict,
    speech_text: str,
) -> str:
    registration = extract_registration(speech_text)

    if not registration or not registration_is_valid(registration):
        return _retry(session)

    session["registration"] = registration
    session["registration_confirmed"] = False
    session["vehicle"] = {}
    session["vehicle_confirmed"] = False

    set_stage(session, "registration_confirm")
    reset_retries(session)

    spoken_registration = _spoken_registration(registration)

    return _listen(
        f"I heard {spoken_registration}. "
        "Is that registration correct?"
    )


def _handle_registration_confirm(
    session: dict,
    speech_text: str,
) -> str:
    confirmation = extract_confirmation(speech_text)

    if confirmation == "no":
        session["registration"] = ""
        session["registration_confirmed"] = False
        session["vehicle"] = {}
        session["vehicle_confirmed"] = False

        set_stage(session, "registration")
        reset_retries(session)

        return _listen(
            "No problem. Please say the registration again, "
            "one character at a time."
        )

    if confirmation != "yes":
        return _retry(session)

    session["registration_confirmed"] = True

    result = safely_lookup_vehicle(
        session.get("registration", "")
    )

    if result.get("success"):
        session["vehicle"] = result.get("vehicle") or {}
        session["vehicle_confirmed"] = False

        set_stage(session, "vehicle_confirm")
        reset_retries(session)

        return _listen(
            vehicle_confirmation_question(
                session["vehicle"]
            )
        )

    reason = clean(result.get("reason"))

    if reason in {
        "invalid_registration",
        "not_found",
    }:
        session["registration"] = ""
        session["registration_confirmed"] = False

        set_stage(session, "registration")
        reset_retries(session)

        return _listen(
            "I couldn't find that vehicle. "
            "Please say the registration again slowly."
        )

    # Do not block the booking if the DVLA API or API key is unavailable.
    registration = clean(
        session.get("registration")
    ).upper()

    session["vehicle"] = {
        "reg": registration,
        "registration": registration,
        "make_model": "Vehicle not confirmed",
    }
    session["vehicle_confirmed"] = True

    return _move_to_next_stage(
        session,
        lead_message=(
            "Thank you. I couldn't retrieve the vehicle details, "
            "but we can still continue with the booking."
        ),
    )


def _handle_vehicle_confirm(
    session: dict,
    speech_text: str,
) -> str:
    confirmation = extract_confirmation(speech_text)

    if confirmation == "yes":
        session["vehicle_confirmed"] = True
        return _move_to_next_stage(session)

    if confirmation == "no":
        session["registration"] = ""
        session["registration_confirmed"] = False
        session["vehicle"] = {}
        session["vehicle_confirmed"] = False

        set_stage(session, "registration")
        reset_retries(session)

        return _listen(
            "No problem. Please say the correct registration."
        )

    return _retry(session)


def _handle_date(
    session: dict,
    speech_text: str,
) -> str:
    parsed = parse_speech(
        speech_text,
        requested_date=session.get("requested_date"),
    )

    apply_parsed(session, parsed)

    requested_date = (
        parsed.get("requested_date")
        or parse_requested_date(speech_text)
    )

    if not requested_date:
        return _retry(session)

    session["requested_date"] = requested_date

    # The caller may say both the day and time together.
    requested_datetime = parsed.get("requested_datetime")

    if isinstance(requested_datetime, datetime):
        session["requested_datetime"] = requested_datetime
        return _check_calendar(session)

    set_stage(session, "time")
    reset_retries(session)

    date_label = requested_date.strftime("%A %-d %B")

    return _listen(
        f"{date_label}. What time would suit you?"
    )


def _handle_time(
    session: dict,
    speech_text: str,
) -> str:
    requested_datetime = parse_requested_time(
        speech_text,
        requested_date=session.get("requested_date"),
    )

    if not isinstance(requested_datetime, datetime):
        return _retry(session)

    session["requested_datetime"] = requested_datetime

    parsed = parse_speech(
        speech_text,
        requested_date=session.get("requested_date"),
    )

    if parsed.get("preferred_period"):
        session["preferred_period"] = parsed["preferred_period"]

    return _check_calendar(session)


def _check_calendar(session: dict) -> str:
    result = check_requested_slot(session)

    error = clean(result.get("error"))

    if error == "calendar_unavailable":
        return _end(
            "I'm sorry, the booking calendar is temporarily unavailable. "
            f"Please contact {BUSINESS_NAME} directly. Goodbye."
        )

    slots = result.get("slots") or []

    if result.get("available") and slots:
        session["selected_slot"] = slots[0]
        session["available_slots"] = []
        return _move_to_next_stage(session)

    if slots:
        session["available_slots"] = slots

        set_stage(session, "slot_choice")
        reset_retries(session)

        return _listen(build_slot_offer(slots))

    session["requested_date"] = None
    session["requested_datetime"] = None
    session["selected_slot"] = None
    session["available_slots"] = []

    set_stage(session, "date")
    reset_retries(session)

    return _listen(
        "I couldn't find another available time that day. "
        "What other day would suit you?"
    )


def _handle_slot_choice(
    session: dict,
    speech_text: str,
) -> str:
    available_slots = session.get("available_slots") or []

    selected_slot = match_slot(
        speech_text,
        available_slots,
    )

    if not isinstance(selected_slot, datetime):
        return _retry(
            session,
            custom_message=(
                "Sorry, which available time would you like? "
                "You can say the time or say first, second, "
                "third, or fourth."
            ),
        )

    session["selected_slot"] = selected_slot
    session["requested_datetime"] = selected_slot
    session["available_slots"] = []

    return _move_to_next_stage(session)


def _handle_name(
    session: dict,
    speech_text: str,
) -> str:
    name = clean_direct_name(speech_text)

    if not name:
        return _retry(session)

    # Save what the caller said first.
    session["name"] = first_name(name)
    session["name_confirmed"] = False

    # The next response is expected to be the spelling.
    set_stage(session, "confirm_name")
    reset_retries(session)

    spoken_name = first_name(session["name"])

    return _listen(
        f"Thank you. I heard {spoken_name}. "
        "Please spell your first name, one letter at a time."
    )


def _handle_confirm_name(
    session: dict,
    speech_text: str,
) -> str:
    spelled_name = _parse_spelled_name(speech_text)

    if not spelled_name:
        return _retry(
            session,
            custom_message=(
                "Sorry, I didn't catch the spelling. "
                "Please spell your first name one letter at a time, "
                "for example, J A M E S."
            ),
        )

    # Critical fix:
    # Save the spelled name and mark it as confirmed.
    session["name"] = spelled_name
    session["name_confirmed"] = True

    reset_retries(session)

    # Do not return to the name stage.
    # Continue directly to the next required stage.
    return _move_to_next_stage(
        session,
        lead_message=f"Thank you, {first_name(spelled_name)}.",
    )


def _handle_summary(
    session: dict,
    speech_text: str,
) -> str:
    confirmation = extract_confirmation(speech_text)

    if confirmation == "yes":
        try:
            booking = create_from_session(session)
        except Exception as error:
            print("BOOKING CREATION ERROR:", repr(error))

            return _end(
                "I'm sorry, I couldn't complete the booking because "
                "the calendar is temporarily unavailable. "
                f"Please contact {BUSINESS_NAME} directly. Goodbye."
            )

        session["booking"] = booking
        set_stage(session, "complete")

        slot = (
            session.get("selected_slot")
            or session.get("requested_datetime")
        )

        if isinstance(slot, datetime):
            slot_text = (
                slot.astimezone(TIMEZONE)
                .strftime("%A %-d %B at %-I:%M %p")
                .replace(":00", "")
                .lower()
            )
        else:
            slot_text = "the requested time"

        customer_name = first_name(session.get("name"))
        goodbye_name = (
            f", {customer_name}"
            if customer_name
            else ""
        )

        SESSIONS.pop(
            clean(session.get("call_sid")),
            None,
        )

        return _end(
            f"Your booking is confirmed for {slot_text}"
            f"{goodbye_name}. "
            f"Thank you for calling {BUSINESS_NAME}. Goodbye."
        )

    if confirmation == "no":
        set_stage(session, "correction")
        reset_retries(session)

        return _listen(
            "No problem. What would you like to change? "
            "You can say the service, registration, date, time, "
            "or name."
        )

    return _retry(session)


def _handle_correction(
    session: dict,
    speech_text: str,
) -> str:
    text = clean(speech_text).lower()

    if "name" in text:
        session["name"] = ""
        session["name_confirmed"] = False

        set_stage(session, "name")
        reset_retries(session)

        return _listen(
            "No problem. What name should I use?"
        )

    if (
        "registration" in text
        or "number plate" in text
        or text == "reg"
    ):
        session["registration"] = ""
        session["registration_confirmed"] = False
        session["vehicle"] = {}
        session["vehicle_confirmed"] = False

        set_stage(session, "registration")
        reset_retries(session)

        return _listen(
            "No problem. Please say the correct registration."
        )

    if (
        "date" in text
        or "day" in text
    ):
        session["requested_date"] = None
        session["requested_datetime"] = None
        session["selected_slot"] = None
        session["available_slots"] = []

        set_stage(session, "date")
        reset_retries(session)

        return _listen(
            "No problem. What day would you prefer?"
        )

    if "time" in text:
        session["requested_datetime"] = None
        session["selected_slot"] = None
        session["available_slots"] = []

        set_stage(session, "time")
        reset_retries(session)

        return _listen(
            "No problem. What time would you prefer?"
        )

    if (
        "service" in text
        or "mot" in text
        or "oil" in text
        or "diagnostic" in text
        or "brake" in text
    ):
        session["service_key"] = ""
        session["selected_slot"] = None
        session["available_slots"] = []

        set_stage(session, "service")
        reset_retries(session)

        return _listen(
            "No problem. What service do you need instead?"
        )

    parsed = parse_speech(
        speech_text,
        requested_date=session.get("requested_date"),
    )

    before = {
        "service_key": session.get("service_key"),
        "requested_date": session.get("requested_date"),
        "requested_datetime": session.get("requested_datetime"),
    }

    apply_parsed(session, parsed)

    changed = any(
        session.get(key) != old_value
        for key, old_value in before.items()
    )

    if changed:
        session["selected_slot"] = None
        session["available_slots"] = []

        if isinstance(
            session.get("requested_datetime"),
            datetime,
        ):
            return _check_calendar(session)

        return _move_to_next_stage(session)

    return _retry(
        session,
        custom_message=(
            "Sorry, I didn't understand what you want to change. "
            "Please say service, registration, date, time, or name."
        ),
    )


def handle_voice_process(
    call_sid: str,
    caller_number: str,
    speech_text: str,
) -> str:
    session = _get_session(
        call_sid=call_sid,
        caller_number=caller_number,
    )

    stage = clean(session.get("stage")) or "service"
    speech_text = clean(speech_text)

    print(
        "VOICE PROCESS:",
        {
            "call_sid": call_sid,
            "stage": stage,
            "speech": speech_text,
        },
    )

    if not speech_text:
        return _retry(
            session,
            silence=True,
        )

    record_message(session, speech_text)

    handlers = {
        "service": _handle_service,
        "same_vehicle": _handle_same_vehicle,
        "registration": _handle_registration,
        "registration_confirm": _handle_registration_confirm,
        "vehicle_confirm": _handle_vehicle_confirm,
        "date": _handle_date,
        "time": _handle_time,
        "slot_choice": _handle_slot_choice,
        "name": _handle_name,
        "confirm_name": _handle_confirm_name,
        "summary": _handle_summary,
        "correction": _handle_correction,
    }

    handler = handlers.get(stage)

    if handler is None:
        print("UNKNOWN VOICE STAGE:", stage)

        set_stage(session, next_required_stage(session))
        return _listen(_prompt_for_stage(session))

    try:
        return handler(session, speech_text)
    except Exception as error:
        print(
            "VOICE HANDLER ERROR:",
            {
                "stage": stage,
                "error": repr(error),
            },
        )

        return _end(
            "I'm sorry, something went wrong while processing the booking. "
            f"Please contact {BUSINESS_NAME} directly. Goodbye."
        )