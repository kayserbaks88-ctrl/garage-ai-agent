from __future__ import annotations

import hmac
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from flask import Blueprint, Response, current_app, request
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from trimtech.core.registry import load_business_instance
from trimtech.modules.staff.agent import handle_message


staff_whatsapp_blueprint = Blueprint(
    "staff_whatsapp",
    __name__,
)

# Short alias for compatibility with other TrimTech blueprint modules.
staff_whatsapp_bp = staff_whatsapp_blueprint


def _clean_business_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    return "".join(
        character
        for character in slug
        if character.isalnum() or character in {"-", "_"}
    )[:100]


def _twilio_auth_token() -> str:
    return (
        os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        or os.getenv("AUTH_TOKEN", "").strip()
    )


def _public_request_urls() -> list[str]:
    """Return safe URL candidates for Twilio validation behind Render's proxy."""
    candidates = [request.url]
    parsed = urlsplit(request.url)

    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()

    if forwarded_proto in {"http", "https"} or forwarded_host:
        candidates.append(
            urlunsplit(
                (
                    forwarded_proto or parsed.scheme,
                    forwarded_host or parsed.netloc,
                    parsed.path,
                    parsed.query,
                    "",
                )
            )
        )

    configured_base = os.getenv("STAFF_WEBHOOK_BASE_URL", "").strip().rstrip("/")
    if configured_base:
        candidates.append(f"{configured_base}{parsed.path}")

    return list(dict.fromkeys(url for url in candidates if url))


def _valid_twilio_signature() -> bool:
    auth_token = _twilio_auth_token()
    supplied_signature = request.headers.get("X-Twilio-Signature", "").strip()

    if not auth_token or not supplied_signature:
        return False

    validator = RequestValidator(auth_token)
    form_parameters = request.form.to_dict(flat=True)

    for public_url in _public_request_urls():
        if validator.validate(public_url, form_parameters, supplied_signature):
            return True

    return False


def _twiml_reply(message: str, status_code: int = 200) -> Response:
    response = MessagingResponse()
    response.message(str(message or "Sorry, I couldn't process that message."))

    return Response(
        str(response),
        status=status_code,
        mimetype="application/xml",
    )


def _media_urls() -> list[str]:
    try:
        media_count = max(0, min(int(request.form.get("NumMedia", "0")), 10))
    except (TypeError, ValueError):
        media_count = 0

    photos: list[str] = []

    for index in range(media_count):
        media_url = str(request.form.get(f"MediaUrl{index}", "") or "").strip()
        content_type = str(
            request.form.get(f"MediaContentType{index}", "") or ""
        ).strip().lower()

        # Only image attachments may satisfy a site-photo request.
        if media_url and (not content_type or content_type.startswith("image/")):
            photos.append(media_url)

    return photos


@staff_whatsapp_blueprint.post("/staff/<business_slug>/whatsapp")
def staff_whatsapp(business_slug: str):
    """Receive a signed Twilio WhatsApp message for one Staff Manager tenant."""
    if not _twilio_auth_token():
        current_app.logger.error(
            "Staff WhatsApp is not configured: TWILIO_AUTH_TOKEN is missing."
        )
        return _twiml_reply(
            "Staff Manager messaging is not configured yet.",
            status_code=503,
        )

    if not _valid_twilio_signature():
        current_app.logger.warning(
            "Rejected Staff Manager webhook with an invalid Twilio signature."
        )
        return Response("Forbidden", status=403, mimetype="text/plain")

    clean_slug = _clean_business_slug(business_slug)
    if not clean_slug or not hmac.compare_digest(clean_slug, business_slug.lower()):
        return _twiml_reply("That Staff Manager business link is invalid.", 404)

    try:
        business = load_business_instance(clean_slug, refresh=True)
    except LookupError:
        current_app.logger.warning(
            "Staff WhatsApp business was not found: %s",
            clean_slug,
        )
        return _twiml_reply("That Staff Manager business could not be found.", 404)
    except Exception as error:
        current_app.logger.exception(
            "Staff WhatsApp could not load business %s: %r",
            clean_slug,
            error,
        )
        return _twiml_reply(
            "Staff Manager is temporarily unavailable. Please try again shortly.",
            503,
        )

    phone = request.form.get("From", "")
    incoming = request.form.get("Body", "")
    profile_name = request.form.get("ProfileName", "")

    if not phone:
        return _twiml_reply("I couldn't identify the sender of this message.", 400)

    reply = handle_message(
        business_id=business.business_id,
        phone=phone,
        text=incoming,
        profile_name=profile_name,
        media_urls=_media_urls(),
        location={
            "latitude": request.form.get("Latitude", ""),
            "longitude": request.form.get("Longitude", ""),
        },
    )

    return _twiml_reply(reply)
