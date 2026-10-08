"""Emailing alerts. An alert is always stored; the email is best effort.

A mail server that is down or slow must never stop monitoring, so failures are
recorded on the Alert (email_error) instead of being raised.
"""

import logging
import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from inventory.models import Alert

log = logging.getLogger(__name__)


def subject(alert: Alert) -> str:
    state = "DOWN" if alert.kind == Alert.Kind.DOWN else "back UP"
    return f"[wall] {alert.device} ({alert.device.ip}) is {state}"


def body(alert: Alert) -> str:
    text = alert.message
    if settings.WALL_HUB_URL:
        link = settings.WALL_HUB_URL.rstrip("/") + reverse("device-detail", args=[alert.device.pk])
        text += f"\n\n{link}"
    return text + "\n\n-- \nSent by wall-hub monitoring.\n"


def send(alert: Alert) -> None:
    recipients = settings.WALL_ALERT_EMAILS
    if not recipients:
        log.info("alert not emailed (WALL_ALERT_EMAILS is empty): %s", alert.message)
        return
    try:
        send_mail(subject(alert), body(alert), None, recipients)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("could not email alert %s: %s", alert.pk, exc)
        alert.email_error = f"{type(exc).__name__}: {exc}"
    else:
        alert.emailed_to = ", ".join(recipients)
    alert.save(update_fields=["emailed_to", "email_error"])
