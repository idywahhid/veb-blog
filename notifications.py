"""
notifications.py — Gmail SMTP orqali email bildirishnoma yuborish
"""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import database


def get_smtp_settings() -> dict:
    s = database.get_settings_dict(["SMTP_EMAIL", "SMTP_APP_PASSWORD", "SMTP_NOTIFY_ENABLED"])
    return {
        "email": s.get("SMTP_EMAIL") or "",
        "app_password": s.get("SMTP_APP_PASSWORD") or "",
        "enabled": (s.get("SMTP_NOTIFY_ENABLED") or "0") == "1",
    }


def send_email(subject: str, body: str, to_addr: str = None) -> tuple[bool, str]:
    """Gmail SMTP orqali email yuboradi. (success, error_message) qaytaradi."""
    settings = get_smtp_settings()
    sender = settings["email"]
    app_password = settings["app_password"]
    recipient = to_addr or sender

    if not sender or not app_password:
        return False, "Gmail manzil yoki app-parol sozlanmagan."

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls(context=context)
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def notify_new_message(name: str, body: str, subject: str = None) -> None:
    """Yangi kontakt xabari kelganda bildirishnoma yuboradi (sozlangan bo'lsa)."""
    settings = get_smtp_settings()
    if not settings["enabled"] or not settings["email"] or not settings["app_password"]:
        return
    mail_subject = f"Blog: yangi xabar — {name}"
    mail_body = (
        f"Yangi xabar keldi.\n\n"
        f"Ism: {name}\n"
        f"Mavzu: {subject or '-'}\n\n"
        f"Matn:\n{body}\n"
    )
    try:
        send_email(mail_subject, mail_body)
    except Exception:
        pass  # bildirishnoma xatosi asosiy oqimni to'xtatmasligi kerak
