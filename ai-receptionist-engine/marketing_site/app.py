from __future__ import annotations

from pathlib import Path

from flask import Flask, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)


def clean_text(value: str | None, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


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
            f"""
            <!DOCTYPE html>
            <html lang="en-GB">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>Missing details | TrimTech AI</title>
              <style>
                body {{
                  margin: 0;
                  min-height: 100vh;
                  display: grid;
                  place-items: center;
                  padding: 24px;
                  font-family: Arial, sans-serif;
                  color: #f7fbff;
                  background: #07111f;
                }}
                .card {{
                  width: min(100%, 620px);
                  padding: 32px;
                  border-radius: 24px;
                  border: 1px solid rgba(255,255,255,.12);
                  background: #0f2034;
                }}
                h1 {{ margin-top: 0; }}
                p {{ color: #9eb0c2; line-height: 1.6; }}
                a {{
                  display: inline-block;
                  margin-top: 12px;
                  padding: 13px 18px;
                  border-radius: 12px;
                  color: #04120f;
                  background: #22d3a7;
                  text-decoration: none;
                  font-weight: 800;
                }}
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
          Thanks {name}. We’ve received your details and will use your preferred contact method
          to follow up about a TrimTech AI demonstration.
        </p>

        <div class="business">{business_name}</div>

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