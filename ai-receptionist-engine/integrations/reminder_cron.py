from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REMINDER_URL = (
    "https://garage-voice.onrender.com/internal/run-reminders"
)


def _reminder_url() -> str:
    return (
        os.getenv("REMINDER_CRON_URL", "").strip()
        or DEFAULT_REMINDER_URL
    )


def _cron_secret() -> str:
    secret = os.getenv("REMINDER_CRON_SECRET", "").strip()

    if not secret:
        raise RuntimeError("REMINDER_CRON_SECRET is missing.")

    return secret


def run() -> dict:
    """Trigger the protected reminder endpoint from Render Cron."""
    request = Request(
        _reminder_url(),
        data=b'{"source":"render_cron"}',
        method="POST",
        headers={
            "Authorization": f"Bearer {_cron_secret()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TrimTech-Reminder-Cron/1.0",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            raw_body = response.read().decode(
                "utf-8",
                errors="replace",
            )
            result = json.loads(raw_body) if raw_body else {}
            print("REMINDER CRON SUCCESS:")
            print(json.dumps(result, indent=2))
            return result

    except HTTPError as error:
        body = error.read().decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"Reminder endpoint returned {error.code}: {body}"
        ) from error

    except URLError as error:
        raise RuntimeError(
            "Reminder endpoint could not be reached: "
            f"{error.reason}"
        ) from error


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        print(
            "REMINDER CRON FAILED:",
            repr(error),
            file=sys.stderr,
        )
        raise SystemExit(1)