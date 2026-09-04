from __future__ import annotations

import base64
import json
import os
import re
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent

RESEND_API_URL = "https://api.resend.com/emails"
TWILIO_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"


app = Flask(__name__)


def clean_text(value: str | None, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def send_lead_notification(lead: dict[str, str]) -> tuple[bool, str]:
    """
    Send a TrimTech AI demo enquiry notification through Resend.

    Required Render environment variables:
        RESEND_API_KEY
        MARKETING_LEAD_EMAIL

    Optional:
        RESEND_FROM_EMAIL

    Example RESEND_FROM_EMAIL after verifying your domain:
        TrimTech AI <hello@yourdomain.co.uk>
    """

    api_key = clean_text(os.getenv("RESEND_API_KEY"), 500)
    recipient = clean_text(os.getenv("MARKETING_LEAD_EMAIL"), 320)
    from_email = clean_text(
        os.getenv("RESEND_FROM_EMAIL"),
        320,
    ) or "TrimTech AI <onboarding@resend.dev>"

    if not api_key:
        return False, "RESEND_API_KEY is not configured."

    if not recipient:
        return False, "MARKETING_LEAD_EMAIL is not configured."

    name = escape(lead.get("name", ""))
    business_name = escape(lead.get("business_name", ""))
    phone = escape(lead.get("phone", ""))
    email = escape(lead.get("email", ""))
    contact_method = escape(lead.get("contact_method", ""))
    garage_size = escape(lead.get("garage_size", "") or "Not supplied")
    message = escape(lead.get("message", "") or "No additional message").replace(
        "\n",
        "<br>",
    )

    subject = f"New TrimTech AI demo enquiry — {lead.get('business_name') or lead.get('name')}"

    html_body = f"""
    <div style="margin:0;padding:24px;background:#07111f;font-family:Arial,sans-serif;color:#f7fbff;">
      <div style="max-width:680px;margin:0 auto;padding:28px;border-radius:22px;background:#0f2034;border:1px solid rgba(255,255,255,.12);">
        <div style="font-size:13px;font-weight:700;color:#22d3a7;margin-bottom:8px;">
          NEW TRIMTECH AI LEAD
        </div>

        <h1 style="margin:0 0 20px;font-size:28px;color:#ffffff;">
          Demo enquiry received
        </h1>

        <table style="width:100%;border-collapse:collapse;color:#dce7f0;font-size:15px;">
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;width:180px;">Name</td>
            <td style="padding:9px 0;font-weight:700;">{name}</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;">Garage / business</td>
            <td style="padding:9px 0;font-weight:700;">{business_name}</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;">Phone</td>
            <td style="padding:9px 0;font-weight:700;">{phone}</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;">Email</td>
            <td style="padding:9px 0;font-weight:700;">{email}</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;">Preferred contact</td>
            <td style="padding:9px 0;font-weight:700;">{contact_method}</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#8fa4b6;">Garage size</td>
            <td style="padding:9px 0;font-weight:700;">{garage_size}</td>
          </tr>
        </table>

        <div style="margin-top:22px;padding:18px;border-radius:14px;background:#0a1929;border:1px solid rgba(255,255,255,.08);">
          <div style="margin-bottom:8px;color:#8fa4b6;font-size:12px;font-weight:700;">
            MESSAGE
          </div>
          <div style="color:#dce7f0;line-height:1.65;">
            {message}
          </div>
        </div>

        <div style="margin-top:22px;font-size:12px;color:#71879b;">
          Submitted through the TrimTech AI marketing website.
        </div>
      </div>
    </div>
    """

    payload = {
        "from": from_email,
        "to": [recipient],
        "subject": subject,
        "html": html_body,
        "reply_to": lead.get("email") or recipient,
    }

    request_data = Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TrimTech-AI-Marketing/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request_data, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")

        print(
            "TRIMTECH MARKETING LEAD EMAIL SENT:",
            {
                "recipient": recipient,
                "response": response_body,
            },
            flush=True,
        )

        return True, ""

    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        error_message = f"Resend HTTP {error.code}: {body}"

    except URLError as error:
        error_message = f"Resend connection error: {error.reason}"

    except Exception as error:
        error_message = f"Unexpected Resend error: {repr(error)}"

    print(
        "TRIMTECH MARKETING LEAD EMAIL ERROR:",
        error_message,
        flush=True,
    )

    return False, error_message


def send_customer_confirmation(lead: dict[str, str]) -> tuple[bool, str]:
    """
    Send a branded confirmation email to the customer after a demo enquiry.

    This is deliberately separate from the owner notification. If the customer
    confirmation fails, the enquiry is still accepted and the owner notification
    remains unaffected.
    """

    api_key = clean_text(os.getenv("RESEND_API_KEY"), 500)
    recipient = clean_text(lead.get("email"), 320)
    owner_email = clean_text(os.getenv("MARKETING_LEAD_EMAIL"), 320)
    from_email = clean_text(
        os.getenv("RESEND_FROM_EMAIL"),
        320,
    ) or "TrimTech AI <onboarding@resend.dev>"

    if not api_key:
        return False, "RESEND_API_KEY is not configured."

    if not recipient:
        return False, "Customer email is not available."

    name = escape(lead.get("name", "") or "there")
    business_name = escape(lead.get("business_name", "") or "your garage")
    contact_method = escape(lead.get("contact_method", "") or "phone")

    subject = "Your TrimTech AI demo request is confirmed"

    html_body = f"""
    <div style="margin:0;padding:24px;background:#07111f;font-family:Arial,sans-serif;color:#f7fbff;">
      <div style="max-width:680px;margin:0 auto;padding:28px;border-radius:22px;background:#0f2034;border:1px solid rgba(255,255,255,.12);">
        <div style="font-size:13px;font-weight:700;color:#22d3a7;margin-bottom:8px;">
          TRIMTECH AI
        </div>

        <h1 style="margin:0 0 18px;font-size:30px;line-height:1.2;color:#ffffff;">
          Your demo request is confirmed
        </h1>

        <p style="margin:0 0 18px;color:#dce7f0;font-size:16px;line-height:1.7;">
          Hi {name},
        </p>

        <p style="margin:0 0 18px;color:#dce7f0;font-size:16px;line-height:1.7;">
          Thanks for requesting a TrimTech AI demonstration for
          <strong>{business_name}</strong>. We’ve received your details and will
          be in touch using your preferred contact method:
          <strong>{contact_method}</strong>.
        </p>

        <div style="margin:24px 0;padding:20px;border-radius:16px;background:#0a1929;border:1px solid rgba(255,255,255,.08);">
          <div style="margin-bottom:10px;color:#22d3a7;font-size:13px;font-weight:700;">
            WHAT HAPPENS NEXT?
          </div>
          <div style="color:#dce7f0;line-height:1.7;font-size:15px;">
            We’ll have a quick conversation about how your garage currently
            handles calls, bookings and customer follow-up, then show you how
            TrimTech AI could fit around the way your business already works.
          </div>
        </div>

        <p style="margin:0;color:#8fa4b6;font-size:14px;line-height:1.7;">
          TrimTech AI<br>
          AI reception built for busy UK garages<br>
          <a href="https://trimtechai.com" style="color:#22d3a7;text-decoration:none;">
            trimtechai.com
          </a>
        </p>
      </div>
    </div>
    """

    payload = {
        "from": from_email,
        "to": [recipient],
        "subject": subject,
        "html": html_body,
    }

    if owner_email:
        payload["reply_to"] = owner_email

    request_data = Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TrimTech-AI-Marketing/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request_data, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")

        print(
            "TRIMTECH CUSTOMER CONFIRMATION EMAIL SENT:",
            {
                "recipient": recipient,
                "response": response_body,
            },
            flush=True,
        )

        return True, ""

    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        error_message = f"Resend HTTP {error.code}: {body}"

    except URLError as error:
        error_message = f"Resend connection error: {error.reason}"

    except Exception as error:
        error_message = f"Unexpected Resend error: {repr(error)}"

    print(
        "TRIMTECH CUSTOMER CONFIRMATION EMAIL ERROR:",
        error_message,
        flush=True,
    )

    return False, error_message


def normalise_uk_phone(value: str) -> str:
    raw = clean_text(value, 80)
    if not raw:
        return ""
    compact = re.sub(r"[^\d+]", "", raw)
    if compact.startswith("0044"):
        compact = "+44" + compact[4:]
    elif compact.startswith("44") and not compact.startswith("+44"):
        compact = "+" + compact
    elif compact.startswith("0"):
        compact = "+44" + compact[1:]
    if not compact.startswith("+"):
        return ""
    digits = re.sub(r"\D", "", compact)
    if len(digits) < 10 or len(digits) > 15:
        return ""
    return "+" + digits


def send_whatsapp_demo_confirmation(lead: dict[str, str]) -> tuple[bool, str]:
    if clean_text(lead.get("contact_method"), 40).lower() != "whatsapp":
        return True, ""

    account_sid = clean_text(os.getenv("TWILIO_ACCOUNT_SID"), 200)
    auth_token = clean_text(os.getenv("TWILIO_AUTH_TOKEN"), 300)
    whatsapp_from = clean_text(os.getenv("TWILIO_WHATSAPP_FROM"), 100)
    content_sid = clean_text(os.getenv("TWILIO_DEMO_CONFIRMATION_CONTENT_SID"), 100)

    if not account_sid:
        return False, "TWILIO_ACCOUNT_SID is not configured."
    if not auth_token:
        return False, "TWILIO_AUTH_TOKEN is not configured."
    if not whatsapp_from:
        return False, "TWILIO_WHATSAPP_FROM is not configured."
    if not content_sid:
        return False, "TWILIO_DEMO_CONFIRMATION_CONTENT_SID is not configured."

    recipient = normalise_uk_phone(lead.get("phone", ""))
    if not recipient:
        return False, "Customer phone number could not be normalised for WhatsApp."

    from_value = whatsapp_from if whatsapp_from.startswith("whatsapp:") else f"whatsapp:{whatsapp_from}"
    to_value = f"whatsapp:{recipient}"
    content_variables = json.dumps({
        "1": clean_text(lead.get("name"), 120) or "there",
        "2": clean_text(lead.get("business_name"), 160) or "your business",
    })

    form_data = urlencode({
        "From": from_value,
        "To": to_value,
        "ContentSid": content_sid,
        "ContentVariables": content_variables,
    }).encode("utf-8")

    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    request_data = Request(
        TWILIO_MESSAGES_URL.format(account_sid=account_sid),
        data=form_data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TrimTech-AI-Marketing/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request_data, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
        print("TRIMTECH CUSTOMER WHATSAPP CONFIRMATION SENT:", {"recipient": recipient, "response": response_body}, flush=True)
        return True, ""
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        error_message = f"Twilio HTTP {error.code}: {body}"
    except URLError as error:
        error_message = f"Twilio connection error: {error.reason}"
    except Exception as error:
        error_message = f"Unexpected Twilio error: {repr(error)}"

    print("TRIMTECH CUSTOMER WHATSAPP CONFIRMATION ERROR:", error_message, flush=True)
    return False, error_message


@app.get("/")
def landing_page():
    return send_from_directory(BASE_DIR, "landing.html")


@app.route("/demo", methods=["GET", "POST"])
def demo_page():
    if request.method == "GET":
        return send_from_directory(BASE_DIR, "demo.html")

    name = clean_text(request.form.get("name"), 120)
    business_name = clean_text(request.form.get("business_name"), 160)
    phone = clean_text(request.form.get("phone"), 80)
    email = clean_text(request.form.get("email"), 180)
    contact_method = clean_text(request.form.get("contact_method"), 40)
    garage_size = clean_text(request.form.get("garage_size"), 80)
    message = clean_text(request.form.get("message"), 1000)

    missing_fields = [
        field_name
        for field_name, value in {
            "name": name,
            "business_name": business_name,
            "phone": phone,
            "email": email,
        }.items()
        if not value
    ]

    if missing_fields:
        return (
            """
            <!DOCTYPE html>
            <html lang="en-GB">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>Missing details | TrimTech AI</title>
              <style>
                body {
                  margin: 0;
                  min-height: 100vh;
                  display: grid;
                  place-items: center;
                  padding: 24px;
                  font-family: Arial, sans-serif;
                  color: #f7fbff;
                  background: #07111f;
                }
                .card {
                  width: min(100%, 620px);
                  padding: 32px;
                  border-radius: 24px;
                  border: 1px solid rgba(255,255,255,.12);
                  background: #0f2034;
                }
                h1 { margin-top: 0; }
                p { color: #9eb0c2; line-height: 1.6; }
                a {
                  display: inline-block;
                  margin-top: 12px;
                  padding: 13px 18px;
                  border-radius: 12px;
                  color: #04120f;
                  background: #22d3a7;
                  text-decoration: none;
                  font-weight: 800;
                }
              </style>
            </head>
            <body>
              <main class="card">
                <h1>We just need a few more details.</h1>
                <p>Please complete all required fields before requesting your demo.</p>
                <a href="/demo">← Back to demo form</a>
              </main>
            </body>
            </html>
            """,
            400,
        )

    lead = {
        "name": name,
        "business_name": business_name,
        "phone": phone,
        "email": email,
        "contact_method": contact_method or "phone",
        "garage_size": garage_size,
        "message": message,
    }

    print("TRIMTECH MARKETING LEAD:", lead, flush=True)

    notification_sent, notification_error = send_lead_notification(lead)

    if not notification_sent:
        print(
            "TRIMTECH MARKETING LEAD WARNING: enquiry accepted but email notification failed:",
            notification_error,
            flush=True,
        )

    confirmation_sent, confirmation_error = send_customer_confirmation(lead)

    if not confirmation_sent:
        print(
            "TRIMTECH CUSTOMER CONFIRMATION WARNING: enquiry accepted but customer confirmation failed:",
            confirmation_error,
            flush=True,
        )

    whatsapp_sent, whatsapp_error = send_whatsapp_demo_confirmation(lead)

    if not whatsapp_sent:
        print(
            "TRIMTECH CUSTOMER WHATSAPP WARNING: enquiry accepted but WhatsApp confirmation failed:",
            whatsapp_error,
            flush=True,
        )

    safe_name = escape(name)
    safe_business_name = escape(business_name)

    return f"""
    <!DOCTYPE html>
    <html lang="en-GB">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <meta name="theme-color" content="#07111f">
      <title>Demo Requested | TrimTech AI</title>

      <!-- Google tag (gtag.js) -->
      <script async src="https://www.googletagmanager.com/gtag/js?id=AW-18387727521"></script>
      <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag('js', new Date());
        gtag('config', 'AW-18387727521');
        gtag('event', 'conversion', {{
          'send_to': 'AW-18387727521/F9nPCLzi2OkcEKHp-b9E'
        }});
      </script>

      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Manrope:wght@700;800&display=swap" rel="stylesheet">

      <style>
        * {{ box-sizing: border-box; }}

        body {{
          margin: 0;
          min-height: 100vh;
          display: grid;
          place-items: center;
          padding: 24px;
          font-family: Inter, system-ui, sans-serif;
          color: #f7fbff;
          background:
            radial-gradient(circle at 10% 5%, rgba(34,211,167,.15), transparent 28rem),
            radial-gradient(circle at 90% 10%, rgba(99,168,255,.14), transparent 30rem),
            #07111f;
        }}

        .card {{
          width: min(100%, 720px);
          padding: 42px;
          text-align: center;
          border-radius: 28px;
          border: 1px solid rgba(255,255,255,.12);
          background: linear-gradient(180deg, rgba(17,35,56,.98), rgba(9,22,37,.98));
          box-shadow: 0 24px 70px rgba(0,0,0,.30);
        }}

        .mark {{
          width: 70px;
          height: 70px;
          display: grid;
          place-items: center;
          margin: 0 auto 22px;
          border-radius: 50%;
          background: linear-gradient(135deg, #63f0cb, #22d3a7);
          color: #04120f;
          font-size: 32px;
          font-weight: 900;
        }}

        h1 {{
          margin: 0 0 14px;
          font-family: Manrope, sans-serif;
          font-size: clamp(36px, 7vw, 58px);
          line-height: 1.05;
          letter-spacing: -.045em;
        }}

        p {{
          max-width: 560px;
          margin: 0 auto;
          color: #9eb0c2;
          font-size: 16px;
          line-height: 1.7;
        }}

        .business {{
          margin-top: 20px;
          color: #c8d6e1;
          font-weight: 800;
        }}

        .actions {{
          margin-top: 30px;
          display: flex;
          justify-content: center;
          gap: 12px;
          flex-wrap: wrap;
        }}

        a {{
          min-height: 48px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0 18px;
          border-radius: 13px;
          text-decoration: none;
          font-weight: 800;
        }}

        .primary {{
          color: #04120f;
          background: linear-gradient(135deg, #63f0cb, #22d3a7);
        }}

        .secondary {{
          color: white;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.045);
        }}

        @media (max-width: 560px) {{
          .card {{ padding: 30px 22px; }}
          .actions a {{ width: 100%; }}
        }}
      </style>
    </head>

    <body>
      <main class="card">
        <div class="mark">✓</div>
        <h1>Your TrimTech AI demo request is in.</h1>
        <p>
          Thanks {safe_name}. We’ve received your details and will use your preferred contact method
          to follow up about a TrimTech AI demonstration.
        </p>

        <div class="business">{safe_business_name}</div>

        <div class="actions">
          <a class="primary" href="/">Back to TrimTech AI</a>
          <a class="secondary" href="/demo">Submit another enquiry</a>
        </div>
      </main>
    </body>
    </html>
    """


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "trimtech-ai-marketing",
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)