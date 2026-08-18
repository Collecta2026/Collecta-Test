"""Email sending via SMTP. Settings come from the Settings table (editable in
the app) and fall back to environment variables. Designed to fail gracefully
so the app never crashes if email is not configured yet."""
import os
import smtplib
from email.message import EmailMessage

from models import get_setting


def _cfg(key, env, default=""):
    return get_setting(key) or os.environ.get(env, default)


def email_configured():
    return bool(_cfg("smtp_host", "SMTP_HOST"))


def send_email(to_addr, subject, html_body):
    """Return (ok: bool, message: str)."""
    host = _cfg("smtp_host", "SMTP_HOST")
    if not host:
        return False, "Email is not configured (set SMTP details in Settings)."
    if not to_addr:
        return False, "Customer has no email address on file."
    port = int(_cfg("smtp_port", "SMTP_PORT", "587") or 587)
    user = _cfg("smtp_user", "SMTP_USER")
    pw = _cfg("smtp_pass", "SMTP_PASS")
    sender = _cfg("smtp_from", "SMTP_FROM") or user
    use_tls = str(_cfg("smtp_tls", "SMTP_TLS", "1")) not in ("0", "false", "False")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content("This message requires an HTML-capable email client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            if use_tls:
                s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(msg)
        return True, f"Email sent to {to_addr}."
    except Exception as e:  # noqa: BLE001
        return False, f"Email failed: {e}"
