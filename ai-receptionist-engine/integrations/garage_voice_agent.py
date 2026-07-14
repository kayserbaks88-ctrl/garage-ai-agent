from __future__ import annotations

from datetime import datetime
from typing import Any

from twilio.twiml.voice_response import Gather, VoiceResponse

from core.booking_engine import (
    build_slot_offer,
    check_requested_slot,
    create_from_session,
    format_slot,
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
from core.dvla_helper import safely_lookup_vehicle, vehicle_confirmation_question
from core.fallback_engine import final_message, retry_message, should_end
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
from integrations.garage_leads import save_garage_lead


VOICE_NAME = "Polly.Emma"
VOICE_LANGUAGE = "en-GB"
PROCESS_URL = "/voice/process"
SESSIONS: dict[str, dict] = {}


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
    gather.say(message, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.append(gather)
    response.redirect(PROCESS_URL, method="POST")
    return str(response)


def _end(message: str) -> str:
    response = VoiceResponse()
    response.say(message, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.hangup()
    return str(response)


def _spoken_reg(reg: str) -> str:
    return " ".join(ch for ch in clean(reg).replace(" ", "").upper())


def _save_lead(session: dict, status: str, note: str = "") -> None:
    try:
        slot = session.get("selected_slot") or session.get("requested_datetime")
        preferred = format_slot(slot) if isinstance(slot, datetime) else ""
        vehicle = session.get("vehicle") or {}
        notes = " | ".join(
            value for value in (
                clean(session.get("issue")),
                clean(note),
                f"Vehicle: {vehicle.get('make_model')}" if vehicle.get("make_model") else "",
            )
            if value
        )
        save_garage_lead(
            name=session.get("name", ""),
            phone=session.get("phone", ""),
            vehicle_reg=session.get("registration", ""),
            service_needed=service_label(session.get("service_key", "")),
            issue=session.get("issue", ""),
            preferred_time=preferred,
            notes=notes,
            status=status,
        )
    except Exception as error:
        print("LEAD SAVE ERROR:", repr(error))


def _question_for_stage(session: dict) -> str:
    stage = session["stage"]

    if stage == "service":
        return "How can I help with the vehicle today?"

    if stage == "same_vehicle":
        return (
            f"Is this call about the same vehicle as last time, registration "
            f"{_spoken_reg(session['previous_registration'])}?"
        )

    if stage == "registration":
        return (
            "Please say the vehicle registration slowly, one character at a time. "
            "For example, M C six five X L N."
        )

    if stage == "registration_confirm":
        return (
            f"I heard {_spoken_reg(session['registration'])}. "
            "Is that registration correct?"
        )

    if stage == "vehicle_confirm":
        return vehicle_confirmation_question(session["vehicle"])

    if stage == "date":
        return "What day would you like to bring the vehicle in?"

    if stage == "time":
        period = session.get("preferred_period")
        if period:
            return f"What exact time in the {period} would suit you?"
        return "What exact time would suit you on that day?"

    if stage == "name":
        return "Finally, can I take your name please?"

    if stage == "summary":
        return summary_text(session, service_label(session["service_key"]))

    if stage == "correction":
        return "What would you like me to change: the service, registration, day, time, or name?"

    return "How can I help today?"


def _advance(call_sid: str, session: dict) -> str:
    stage = next_required_stage(session)
    set_stage(session, stage)

    if stage == "summary":
        result = check_requested_slot(session)

        if result["error"] == "calendar_unavailable":
            _save_lead(session, "Needs Confirmation", "Calendar unavailable")
            SESSIONS.pop(call_sid, None)
            return _end(
                "I can't check the live diary at the moment, but I've saved your details. "
                "The garage team will contact you to confirm. Goodbye."
            )

        if result["available"]:
            session["selected_slot"] = result["slots"][0]
        else:
            session["available_slots"] = result["slots"]
            if result["slots"]:
                set_stage(session, "slot_choice")
                SESSIONS[call_sid] = session
                return _listen(build_slot_offer(result["slots"]))
            session["requested_date"] = None
            session["requested_datetime"] = None
            set_stage(session, "date")
            SESSIONS[call_sid] = session
            return _listen(
                "I couldn't find availability that day. What other day would suit you?"
            )

    SESSIONS[call_sid] = session
    return _listen(_question_for_stage(session))


def _retry(call_sid: str, session: dict, silence: bool = False) -> str:
    add_retry(session, silence=silence)
    SESSIONS[call_sid] = session

    if should_end(session):
        _save_lead(session, "Incomplete Call", "Repeated silence or recognition failure")
        SESSIONS.pop(call_sid, None)
        return _end(final_message(BUSINESS_NAME))

    return _listen(
        retry_message(
            session.get("stage", ""),
            session.get("retry_count", 0),
            silence=silence,
        )
    )


def handle_voice_start(call_sid: str, caller_number: str) -> str:
    memory = load_customer_memory(caller_number)
    session = create_session(
        call_sid=call_sid,
        phone=caller_number,
        customer=memory if memory.get("found") else None,
    )
    SESSIONS[call_sid] = session

    hour = datetime.now(TIMEZONE).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

    if memory.get("found"):
        return _listen(
            f"{greeting}. Welcome back, {first_name(memory.get('name'))}. "
            f"Thanks for calling {BUSINESS_NAME}. How can I help today?"
        )

    return _listen(
        f"{greeting}. Thanks for calling {BUSINESS_NAME}. "
        "The team are busy helping customers, but I can help arrange an appointment. "
        "How can I help today?"
    )


def handle_voice_process(call_sid: str, caller_number: str, speech_text: str) -> str:
    session = SESSIONS.get(call_sid)
    if not session:
        return handle_voice_start(call_sid, caller_number)

    speech_text = clean(speech_text)
    if not speech_text:
        return _retry(call_sid, session, silence=True)

    record_message(session, speech_text)
    stage = session["stage"]
    confirmation = extract_confirmation(speech_text)

    print("VOICE INPUT:", {"stage": stage, "speech": speech_text})

    if stage == "same_vehicle":
        if confirmation == "yes":
            session["registration"] = session["previous_registration"]
            session["registration_confirmed"] = True
        elif confirmation == "no":
            session["returning_customer"] = False
            session["registration"] = ""
            set_stage(session, "registration")
            SESSIONS[call_sid] = session
            return _listen(_question_for_stage(session))
        else:
            return _retry(call_sid, session)

    elif stage == "registration_confirm":
        if confirmation == "yes":
            session["registration_confirmed"] = True
            result = safely_lookup_vehicle(session["registration"])
            print("DVLA RESULT:", {"success": result["success"], "reason": result["reason"]})

            if result["success"]:
                session["vehicle"] = result["vehicle"]
                session["vehicle_confirmed"] = False
                set_stage(session, "vehicle_confirm")
                reset_retries(session)
                SESSIONS[call_sid] = session
                return _listen(_question_for_stage(session))
        elif confirmation == "no":
            session["registration"] = ""
            session["registration_confirmed"] = False
            set_stage(session, "registration")
            SESSIONS[call_sid] = session
            return _listen(_question_for_stage(session))
        else:
            return _retry(call_sid, session)

    elif stage == "vehicle_confirm":
        if confirmation == "yes":
            session["vehicle_confirmed"] = True
        elif confirmation == "no":
            session["registration"] = ""
            session["registration_confirmed"] = False
            session["vehicle"] = {}
            session["vehicle_confirmed"] = False
            set_stage(session, "registration")
            SESSIONS[call_sid] = session
            return _listen(_question_for_stage(session))
        else:
            return _retry(call_sid, session)

    elif stage == "registration":
        reg = extract_registration(speech_text)
        if not registration_is_valid(reg):
            return _retry(call_sid, session)
        session["registration"] = reg
        session["registration_confirmed"] = False
        set_stage(session, "registration_confirm")
        reset_retries(session)
        SESSIONS[call_sid] = session
        return _listen(_question_for_stage(session))

    elif stage == "date":
        parsed_date = parse_requested_date(speech_text)
        if not parsed_date:
            return _retry(call_sid, session)
        session["requested_date"] = parsed_date
        session["preferred_period"] = parse_speech(speech_text).get("preferred_period", "")
        parsed_time = parse_requested_time(speech_text, requested_date=parsed_date)
        if parsed_time:
            session["requested_datetime"] = parsed_time

    elif stage == "time":
        parsed_time = parse_requested_time(
            speech_text,
            requested_date=session.get("requested_date"),
        )
        if not parsed_time:
            return _retry(call_sid, session)
        session["requested_datetime"] = parsed_time

    elif stage == "name":
        name = clean_direct_name(speech_text)
        if not name:
            return _retry(call_sid, session)
        session["name"] = name

    elif stage == "slot_choice":
        selected = match_slot(speech_text, session.get("available_slots", []))
        if not selected:
            return _retry(call_sid, session)
        session["selected_slot"] = selected
        set_stage(session, "summary")
        reset_retries(session)
        SESSIONS[call_sid] = session
        return _listen(_question_for_stage(session))

    elif stage == "summary":
        if confirmation == "yes":
            try:
                booking = create_from_session(session)
                session["booking"] = booking
                _save_lead(session, "Provisional Booking")
                SESSIONS.pop(call_sid, None)
                return _end(
                    f"Perfect, {first_name(session.get('name'))}. "
                    f"I've added a provisional booking for "
                    f"{format_slot(session.get('selected_slot') or session['requested_datetime'])}. "
                    "The garage team will contact you shortly to confirm. "
                    f"Thank you for calling {BUSINESS_NAME}. Goodbye."
                )
            except ValueError as error:
                if str(error) == "slot_taken":
                    session["selected_slot"] = None
                    session["requested_datetime"] = None
                    set_stage(session, "time")
                    SESSIONS[call_sid] = session
                    return _listen("That time has just become unavailable. What other time would suit you?")
                raise
            except Exception as error:
                print("BOOKING ERROR:", repr(error))
                _save_lead(session, "Needs Confirmation", "Calendar booking failed")
                SESSIONS.pop(call_sid, None)
                return _end(
                    "I couldn't complete the diary booking, but I've saved all your details. "
                    "The team will contact you to confirm. Goodbye."
                )

        if confirmation == "no":
            set_stage(session, "correction")
            SESSIONS[call_sid] = session
            return _listen(_question_for_stage(session))

        return _retry(call_sid, session)

    elif stage == "correction":
        lower = speech_text.lower()
        parsed = parse_speech(
            speech_text,
            requested_date=session.get("requested_date"),
        )

        if parsed.get("service_key"):
            session["service_key"] = parsed["service_key"]
        elif parsed.get("registration"):
            session["registration"] = parsed["registration"]
            session["registration_confirmed"] = False
            session["vehicle"] = {}
            set_stage(session, "registration_confirm")
            SESSIONS[call_sid] = session
            return _listen(_question_for_stage(session))
        elif parsed.get("requested_date"):
            session["requested_date"] = parsed["requested_date"]
            session["requested_datetime"] = None
        elif parsed.get("requested_datetime"):
            session["requested_datetime"] = parsed["requested_datetime"]
        elif "time" in lower:
            session["requested_datetime"] = None
        elif "day" in lower or "date" in lower:
            session["requested_date"] = None
            session["requested_datetime"] = None
        elif "name" in lower:
            session["name"] = ""
        elif "service" in lower:
            session["service_key"] = ""
        else:
            return _retry(call_sid, session)

    else:
        parsed = parse_speech(
            speech_text,
            requested_date=session.get("requested_date"),
        )
        apply_parsed(session, parsed)

    reset_retries(session)
    return _advance(call_sid, session)
