"""Sending email via stdlib SMTP, with a console fallback for development.

No provider SDK on purpose: plain SMTP works with any free relay (Brevo, a
Gmail app password, …), and when MAIL_SERVER is unset the message is logged
instead so email-dependent flows stay usable locally.
"""

import smtplib
from email.message import EmailMessage

from flask import current_app


def send_email(to, subject, text, html=None):
    """Send an email; returns True on success.

    Failures are logged and swallowed — callers must not surface send success
    or failure to the browser where that would enable account enumeration.
    """
    server = current_app.config.get('MAIL_SERVER')
    if not server:
        current_app.logger.info('Email (console backend) to %s — %s\n%s', to, subject, text)
        return True

    message = EmailMessage()
    message['From'] = current_app.config.get('MAIL_FROM') or current_app.config.get('MAIL_USERNAME')
    message['To'] = to
    message['Subject'] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype='html')

    try:
        port = current_app.config.get('MAIL_PORT', 587)
        with smtplib.SMTP(server, port, timeout=15) as smtp:
            smtp.starttls()
            username = current_app.config.get('MAIL_USERNAME')
            if username:
                smtp.login(username, current_app.config.get('MAIL_PASSWORD') or '')
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception('Failed to send email to %s', to)
        return False
