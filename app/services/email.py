"""Sending email — Brevo HTTPS API, stdlib SMTP, or a console fallback.

Backend precedence:

1. BREVO_API_KEY set → Brevo's transactional HTTPS API (port 443). This is
   the backend that works on Render, whose network blocks outbound SMTP ports.
2. MAIL_SERVER set → plain SMTP with STARTTLS (any relay; local testing).
3. Neither → the message is logged instead of sent, so email-dependent flows
   stay usable in development.

No provider SDK on purpose — the API call is one urllib request.
"""

import json
import smtplib
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from flask import current_app

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


def send_email(to, subject, text, html=None):
    """Send an email; returns True on success.

    Failures are logged and swallowed — callers must not surface send success
    or failure to the browser where that would enable account enumeration.
    """
    if current_app.config.get('BREVO_API_KEY'):
        return _send_via_brevo_api(to, subject, text, html)
    if current_app.config.get('MAIL_SERVER'):
        return _send_via_smtp(to, subject, text, html)
    current_app.logger.info('Email (console backend) to %s — %s\n%s', to, subject, text)
    return True


def _sender():
    """MAIL_FROM parsed into Brevo's sender shape ('Name <a@b>' or bare address)."""
    raw = current_app.config.get('MAIL_FROM') or current_app.config.get('MAIL_USERNAME') or ''
    name, address = parseaddr(raw)
    sender = {'email': address or raw}
    if name:
        sender['name'] = name
    return sender


def _send_via_brevo_api(to, subject, text, html):
    payload = {
        'sender': _sender(),
        'to': [{'email': to}],
        'subject': subject,
        'textContent': text,
    }
    if html:
        payload['htmlContent'] = html
    request = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            'api-key': current_app.config['BREVO_API_KEY'],
            'content-type': 'application/json',
            'accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return 200 <= response.status < 300
    except OSError:  # URLError/HTTPError both subclass OSError
        current_app.logger.exception('Failed to send email to %s', to)
        return False


def _send_via_smtp(to, subject, text, html):
    message = EmailMessage()
    message['From'] = current_app.config.get('MAIL_FROM') or current_app.config.get('MAIL_USERNAME')
    message['To'] = to
    message['Subject'] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype='html')

    try:
        server = current_app.config['MAIL_SERVER']
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
