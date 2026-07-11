from __future__ import annotations

"""
TrimTech Garage AI Voice Receptionist V2.

Public functions used by app.py:
    handle_voice_start(call_sid, caller_number)
    handle_voice_process(call_sid, caller_number, speech_text)
"""

from copy import deepcopy
from datetime import datetime
from typing import Any

from twilio.twiml.voice_response import Gather, VoiceResponse

from core.booking_engine import (
    build_slot_offer,
    format_slot_for_speech,
    get_next_slots_for_conversation,
    get_service_label,
    get_slots_for_conversation,
    match_spoken_slot,
    safely_create_booking,
)
from core.conversation_engine import (
    begin_confirmation,
    build_summary,
    choose_slot,
    confirm_conversation,
    conversation_snapshot,
    create_conversation,
    first_name,
    mark_completed,
    mark_same_vehicle,
    mark_vehicle_confirmed,
    next_missing_field,
    needs_same_vehicle_confirmation,
    register_retry,
    reset_retry,
    set_available_slots,
    set_awaiting,
    set_booking_result,
    set_vehicle,
    update_conversation,
)
from core.customer_memory import (
    build_new_customer_greeting,
    build_returning_customer_greeting,
    build_same_vehicle_question,
    load_customer_memory,
)
from core.dvla_helper import (
    build_vehicle_confirmation_question,
    safely_lookup_vehicle,
)
from core.fallback_engine import (
    calendar_unavailable_message,
    final_retry_message,
    misunderstood_correction_message,
    no_slots_message,
    retry_message,
    should_end_after_retry,
    slot_taken_message,
    temporary_problem_message,
)
from core.speech_parser import (
    clean_text,
    extract_confirmation,
    extract_name,
    extract_registration,
    extract_service_key,
    parse_speech,
)
from integrations.garage_config import BUSINESS_NAME, TIMEZONE
from integrations.garage_leads import save_garage_lead


VOICE_NAME = "Polly.Amy"
VOICE_LANGUAGE = "en-GB"
VOICE_PROCESS_URL = "/voice/process"

SESSIONS: dict[str, dict] = {}


def clean(value: Any) -> str:
    return str(value or "").strip()


def get_session(call_sid: str) -> dict | None:
    return SESSIONS.get(clean(call_sid))


def save_session(call_sid: str, conversation: dict) -> dict:
    SESSIONS[clean(call_sid)] = conversation
    return conversation


def clear_session(call_sid: str) -> None:
    SESSIONS.pop(clean(call_sid), None)


def current_time_greeting() -> str:
    hour = datetime.now(TIMEZONE).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def twiml_listen(message: str, timeout: int = 6) -> str:
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action=VOICE_PROCESS_URL,
        method="POST",
        speech_timeout="auto",
        timeout=timeout,
        language=VOICE_LANGUAGE,
        action_on_empty_result=True,
    )
    gather.say(message, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.append(gather)
    response.redirect(VOICE_PROCESS_URL, method="POST")
    return str(response)


def twiml_end(message: str) -> str:
    response = VoiceResponse()
    response.say(message, voice=VOICE_NAME, language=VOICE_LANGUAGE)
    response.hangup()
    return str(response)


def readable_registration(registration: str) -> str:
    compact = "".join(ch for ch in clean(registration).upper() if ch.isalnum())
    return " ".join(compact)


def preferred_time_text(conversation: dict) -> str:
    selected = conversation.get("selected_slot") or conversation.get("requested_datetime")
    if isinstance(selected, datetime):
        return format_slot_for_speech(selected)

    date_phrase = clean(conversation.get("date_phrase"))
    time_phrase = clean(conversation.get("time_phrase"))
    period = clean(conversation.get("preferred_period"))
    return " ".join(x for x in (date_phrase, time_phrase or period) if x)


def save_lead_safely(
    conversation: dict,
    status: str,
    extra_note: str = "",
) -> bool:
    booking = conversation.get("booking") or {}
    vehicle = conversation.get("vehicle") or {}

    notes = [
        clean(conversation.get("issue")),
        clean(extra_note),
    ]

    if vehicle.get("make_model"):
        notes.append(f"Vehicle: {vehicle['make_model']}")
    if booking.get("link"):
        notes.append(f"Calendar: {booking['link']}")

    try:
        save_garage_lead(
            name=clean(conversation.get("name")),
            phone=clean(conversation.get("phone")),
            vehicle_reg=clean(conversation.get("registration")),
            service_needed=get_service_label(clean(conversation.get("service_key"))),
            issue=clean(conversation.get("issue")),
            preferred_time=preferred_time_text(conversation),
            notes=" | ".join(item for item in notes if item),
            status=status,
        )
        return True
    except Exception as error:
        print("VOICE LEAD SAVE ERROR:", repr(error))
        return False


def question_for_field(field: str, conversation: dict) -> str:
    if field == "same_vehicle_confirmation":
        memory = conversation.get("customer_memory") or {}
        return (
            build_same_vehicle_question(memory)
            or "Is this call about the same vehicle as last time?"
        )

    if field == "service_key":
        return (
            "How can I help with the vehicle today? "
            "For example, an MOT, full service, oil change, "
            "brake check, or diagnostic."
        )

    if field == "registration":
        return (
            "Can I take the vehicle registration please? "
            "You can say each letter and number separately."
        )

    if field == "vehicle_confirmation":
        vehicle = conversation.get("vehicle") or {}
        return (
            build_vehicle_confirmation_question(vehicle)
            if vehicle
            else "Is that the correct vehicle?"
        )

    if field == "requested_date":
        return "What day would suit you best?"

    if field == "requested_datetime":
        if conversation.get("requested_date") and conversation.get("preferred_period"):
            return (
                f"What exact time in the {conversation['preferred_period']} "
                "would suit you best?"
            )
        if conversation.get("requested_date"):
            return "What time would suit you best on that day?"
        return "What day and time would suit you best?"

    if field == "name":
        return "Finally, can I take your name please?"

    if field == "summary_confirmation":
        return build_summary(
            conversation,
            service_label=get_service_label(clean(conversation.get("service_key"))),
        )

    if field == "correction":
        return (
            "No problem. What would you like me to change: "
            "the service, registration, day, time, or name?"
        )

    return "How can I help today?"


def ask_field(
    call_sid: str,
    conversation: dict,
    field: str,
    custom_message: str = "",
) -> str:
    message = custom_message or question_for_field(field, conversation)
    conversation = set_awaiting(conversation, field, message)
    save_session(call_sid, conversation)
    return twiml_listen(message)


def apply_correction(
    conversation: dict,
    speech_text: str,
) -> tuple[dict, bool]:
    parsed = parse_speech(speech_text)
    updated = deepcopy(conversation)
    changed = False

    if parsed.get("service_key"):
        updated["service_key"] = parsed["service_key"]
        updated["selected_slot"] = None
        updated["available_slots"] = []
        changed = True

    if parsed.get("registration"):
        updated["registration"] = parsed["registration"]
        updated["vehicle"] = {}
        updated["vehicle_confirmed"] = False
        changed = True

    if parsed.get("requested_date"):
        updated["requested_date"] = parsed["requested_date"]
        updated["requested_datetime"] = None
        updated["selected_slot"] = None
        updated["available_slots"] = []
        changed = True

    if parsed.get("requested_datetime"):
        updated["requested_datetime"] = parsed["requested_datetime"]
        updated["selected_slot"] = parsed["requested_datetime"]
        changed = True

    if parsed.get("name"):
        updated["name"] = parsed["name"]
        changed = True

    lower = clean(speech_text).lower()

    if not changed and "time" in lower:
        updated["requested_datetime"] = None
        updated["selected_slot"] = None
        updated["available_slots"] = []
        changed = True

    elif not changed and any(word in lower for word in ("day", "date")):
        updated["requested_date"] = None
        updated["requested_datetime"] = None
        updated["selected_slot"] = None
        updated["available_slots"] = []
        changed = True

    elif not changed and any(word in lower for word in ("registration", "reg", "plate")):
        updated["registration"] = ""
        updated["vehicle"] = {}
        updated["vehicle_confirmed"] = False
        changed = True

    elif not changed and any(word in lower for word in ("service", "job", "work")):
        updated["service_key"] = ""
        updated["selected_slot"] = None
        updated["available_slots"] = []
        changed = True

    elif not changed and "name" in lower:
        updated["name"] = ""
        changed = True

    if changed:
        updated["confirmation_pending"] = False
        updated["confirmed"] = False

    return updated, changed


def lookup_vehicle_if_possible(
    call_sid: str,
    conversation: dict,
) -> tuple[dict, str | None]:
    registration = clean(conversation.get("registration"))

    if not registration:
        return conversation, None

    if conversation.get("vehicle") and conversation.get("vehicle_confirmed"):
        return conversation, None

    result = safely_lookup_vehicle(registration)

    print(
        "VOICE DVLA RESULT:",
        {
            "success": result.get("success"),
            "reason": result.get("reason"),
            "registration": registration,
        },
    )

    if result.get("success"):
        vehicle = result.get("vehicle") or {}
        conversation = set_vehicle(conversation, vehicle, confirmed=False)
        conversation = set_awaiting(conversation, "vehicle_confirmation")
        save_session(call_sid, conversation)
        return conversation, twiml_listen(
            build_vehicle_confirmation_question(vehicle)
        )

    conversation["vehicle"] = {
        "reg": registration,
        "registration": registration,
        "make_model": "Vehicle not confirmed",
    }
    conversation["vehicle_confirmed"] = False
    save_session(call_sid, conversation)
    return conversation, None


def prepare_confirmation(call_sid: str, conversation: dict) -> str:
    conversation = begin_confirmation(conversation)
    save_session(call_sid, conversation)
    return twiml_listen(
        build_summary(
            conversation,
            service_label=get_service_label(clean(conversation.get("service_key"))),
        )
    )


def prepare_slots(call_sid: str, conversation: dict) -> str:
    requested = conversation.get("requested_datetime")

    if isinstance(requested, datetime):
        conversation["available_slots"] = [requested]
        conversation["selected_slot"] = requested
        save_session(call_sid, conversation)
        return prepare_confirmation(call_sid, conversation)

    slots = get_slots_for_conversation(conversation, limit=4)

    if not slots:
        slots = get_next_slots_for_conversation(
            conversation,
            days_to_check=7,
            limit=4,
        )

    if not slots:
        conversation = set_awaiting(conversation, "requested_date")
        save_session(call_sid, conversation)
        return twiml_listen(no_slots_message())

    conversation = set_available_slots(conversation, slots)

    if len(slots) == 1:
        conversation = choose_slot(conversation, slots[0])
        save_session(call_sid, conversation)
        return prepare_confirmation(call_sid, conversation)

    conversation = set_awaiting(conversation, "slot_selection")
    save_session(call_sid, conversation)
    return twiml_listen(build_slot_offer(slots))


def finish_booking(call_sid: str, conversation: dict) -> str:
    result = safely_create_booking(conversation)

    if result.get("success"):
        booking = result.get("booking") or {}
        conversation = set_booking_result(conversation, booking=booking, error="")
        conversation = mark_completed(conversation)
        save_lead_safely(conversation, status="Provisional Booking")
        clear_session(call_sid)

        slot = conversation.get("selected_slot") or conversation.get("requested_datetime")
        slot_text = (
            format_slot_for_speech(slot)
            if isinstance(slot, datetime)
            else "the requested time"
        )

        name = first_name(conversation.get("name"))
        name_text = f", {name}" if name else ""

        return twiml_end(
            f"Perfect{name_text}. "
            f"I've added a provisional booking for {slot_text}. "
            "The garage team will contact you shortly to confirm everything. "
            f"Thank you for calling {BUSINESS_NAME}. "
            "Have a lovely day. Goodbye."
        )

    error = clean(result.get("error"))
    conversation = set_booking_result(conversation, booking=None, error=error)

    if error == "slot_taken":
        conversation["selected_slot"] = None
        conversation["requested_datetime"] = None
        conversation["available_slots"] = []
        save_session(call_sid, conversation)
        return twiml_listen(
            slot_taken_message() + " What other time would suit you?"
        )

    save_lead_safely(
        conversation,
        status="Needs Confirmation",
        extra_note=f"Calendar error: {error or 'unknown'}",
    )
    clear_session(call_sid)

    return twiml_end(
        calendar_unavailable_message()
        + " I've saved all your details and the team will contact you "
          "to confirm the appointment. "
        + f"Thank you for calling {BUSINESS_NAME}. Goodbye."
    )


def continue_conversation(call_sid: str, conversation: dict) -> str:
    if needs_same_vehicle_confirmation(conversation):
        return ask_field(call_sid, conversation, "same_vehicle_confirmation")

    field = next_missing_field(conversation, require_exact_time=True)

    if field in {
        "service_key",
        "registration",
        "requested_date",
        "requested_datetime",
        "name",
    }:
        return ask_field(call_sid, conversation, field)

    if field == "summary_confirmation":
        if not conversation.get("selected_slot"):
            return prepare_slots(call_sid, conversation)
        return prepare_confirmation(call_sid, conversation)

    if field == "ready":
        return finish_booking(call_sid, conversation)

    return ask_field(call_sid, conversation, field)


def handle_silence(call_sid: str, conversation: dict) -> str:
    conversation = register_retry(conversation, silence=True)
    save_session(call_sid, conversation)

    if should_end_after_retry(
        conversation.get("retry_count", 0),
        conversation.get("silence_count", 0),
    ):
        save_lead_safely(
            conversation,
            status="Incomplete Call",
            extra_note="Call ended after repeated silence.",
        )
        clear_session(call_sid)
        return twiml_end(final_retry_message(BUSINESS_NAME))

    return twiml_listen(
        retry_message(
            awaiting=clean(conversation.get("awaiting")),
            retry_count=conversation.get("retry_count", 0),
            silence=True,
        )
    )


def handle_unrecognised(call_sid: str, conversation: dict) -> str:
    conversation = register_retry(conversation, silence=False)
    save_session(call_sid, conversation)

    if should_end_after_retry(
        conversation.get("retry_count", 0),
        conversation.get("silence_count", 0),
    ):
        save_lead_safely(
            conversation,
            status="Incomplete Call",
            extra_note="Call ended after repeated recognition failures.",
        )
        clear_session(call_sid)
        return twiml_end(final_retry_message(BUSINESS_NAME))

    return twiml_listen(
        retry_message(
            awaiting=clean(conversation.get("awaiting")),
            retry_count=conversation.get("retry_count", 0),
            silence=False,
        )
    )


def handle_voice_start(call_sid: str, caller_number: str) -> str:
    try:
        memory = load_customer_memory(caller_number)

        conversation = create_conversation(
            call_sid=call_sid,
            phone=caller_number,
            returning_customer=memory if memory.get("found") else None,
        )
        conversation["customer_memory"] = memory
        save_session(call_sid, conversation)

        greeting = (
            build_returning_customer_greeting(memory, BUSINESS_NAME)
            if memory.get("found")
            else build_new_customer_greeting(BUSINESS_NAME)
        )

        return twiml_listen(
            f"{current_time_greeting()}. {greeting}"
        )

    except Exception as error:
        print("VOICE START ERROR:", repr(error))

        conversation = create_conversation(
            call_sid=call_sid,
            phone=caller_number,
            returning_customer=None,
        )
        conversation["customer_memory"] = {}
        save_session(call_sid, conversation)

        return twiml_listen(
            f"{current_time_greeting()}. "
            f"Thanks for calling {BUSINESS_NAME}. "
            "The team are busy helping customers at the moment, "
            "but I can take your details. How can I help today?"
        )


def handle_voice_process(
    call_sid: str,
    caller_number: str,
    speech_text: str,
) -> str:
    try:
        conversation = get_session(call_sid)

        if not conversation:
            return handle_voice_start(call_sid, caller_number)

        speech_text = clean_text(speech_text)

        if not speech_text:
            return handle_silence(call_sid, conversation)

        awaiting = clean(conversation.get("awaiting"))
        confirmation = extract_confirmation(speech_text)

        print(
            "VOICE SPEECH:",
            {
                "call_sid": call_sid,
                "awaiting": awaiting,
                "speech": speech_text,
            },
        )

        if awaiting == "same_vehicle_confirmation":
            if confirmation == "yes":
                conversation = mark_same_vehicle(conversation, confirmed=True)
                conversation = reset_retry(conversation)
                save_session(call_sid, conversation)
                return continue_conversation(call_sid, conversation)

            if confirmation == "no":
                conversation = mark_same_vehicle(conversation, confirmed=False)
                conversation = reset_retry(conversation)
                save_session(call_sid, conversation)
                return ask_field(
                    call_sid,
                    conversation,
                    "registration",
                    "No problem. What is the registration of the vehicle "
                    "you are calling about today?",
                )

            return handle_unrecognised(call_sid, conversation)

        if awaiting == "vehicle_confirmation":
            if confirmation == "yes":
                conversation = mark_vehicle_confirmed(conversation, confirmed=True)
                conversation = reset_retry(conversation)
                save_session(call_sid, conversation)
                return continue_conversation(call_sid, conversation)

            if confirmation == "no":
                conversation = mark_vehicle_confirmed(conversation, confirmed=False)
                conversation = reset_retry(conversation)
                save_session(call_sid, conversation)
                return ask_field(
                    call_sid,
                    conversation,
                    "registration",
                    "No problem. Please say the registration again, "
                    "one character at a time.",
                )

            return handle_unrecognised(call_sid, conversation)

        if awaiting == "slot_selection":
            slots = list(conversation.get("available_slots") or [])
            selected = match_spoken_slot(speech_text, slots)

            if selected:
                conversation = choose_slot(conversation, selected)
                conversation = reset_retry(conversation)
                save_session(call_sid, conversation)
                return prepare_confirmation(call_sid, conversation)

            parsed = parse_speech(speech_text)
            updated = update_conversation(conversation, parsed, speech_text)

            if parsed.get("requested_date") or parsed.get("requested_datetime"):
                updated["available_slots"] = []
                updated["selected_slot"] = None
                updated["confirmation_pending"] = False
                save_session(call_sid, updated)
                return prepare_slots(call_sid, updated)

            return handle_unrecognised(call_sid, conversation)

        if awaiting == "summary_confirmation":
            if confirmation == "yes":
                conversation = confirm_conversation(conversation, confirmed=True)
                save_session(call_sid, conversation)
                return finish_booking(call_sid, conversation)

            if confirmation == "no":
                conversation = confirm_conversation(conversation, confirmed=False)
                save_session(call_sid, conversation)
                return twiml_listen(question_for_field("correction", conversation))

            return handle_unrecognised(call_sid, conversation)

        if awaiting == "correction":
            conversation, changed = apply_correction(conversation, speech_text)

            if not changed:
                save_session(call_sid, conversation)
                return twiml_listen(misunderstood_correction_message())

            conversation = reset_retry(conversation)
            save_session(call_sid, conversation)
            return continue_conversation(call_sid, conversation)

        parsed = parse_speech(speech_text)
        conversation = update_conversation(conversation, parsed, speech_text)
        conversation = reset_retry(conversation)

        if awaiting == "name" and not conversation.get("name"):
            direct_name = extract_name(f"My name is {speech_text}")
            if direct_name:
                conversation["name"] = direct_name

        if awaiting == "registration" and not conversation.get("registration"):
            direct_reg = extract_registration(speech_text)
            if direct_reg:
                conversation["registration"] = direct_reg

        if awaiting == "service_key" and not conversation.get("service_key"):
            direct_service = extract_service_key(speech_text)
            if direct_service:
                conversation["service_key"] = direct_service

        save_session(call_sid, conversation)

        if (
            conversation.get("registration")
            and not conversation.get("vehicle")
            and awaiting != "vehicle_confirmation"
        ):
            conversation, immediate_reply = lookup_vehicle_if_possible(
                call_sid,
                conversation,
            )
            if immediate_reply:
                return immediate_reply

        print("VOICE STATE:", conversation_snapshot(conversation))
        return continue_conversation(call_sid, conversation)

    except Exception as error:
        print("VOICE PROCESS ERROR:", repr(error))

        conversation = get_session(call_sid)
        if conversation:
            save_lead_safely(
                conversation,
                status="Technical Follow-Up",
                extra_note=f"Voice processing error: {error!r}",
            )

        clear_session(call_sid)
        return twiml_end(temporary_problem_message(BUSINESS_NAME))