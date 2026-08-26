from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent

RESEND_API_URL = "https://api.resend.com/emails"


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