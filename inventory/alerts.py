"""Emailing alerts. An alert is always stored; the email is best effort.

A mail server that is down or slow must never stop monitoring or scanning, so
failures are recorded on the Alert (email_error) instead of being raised.
"""

import logging
import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from inventory.models import Alert, Device

log = logging.getLogger(__name__)

FOOTER = "\n\n-- \nSent by wall-hub.\n"


def device_link(device: Device) -> str | None:
    if not settings.WALL_HUB_URL:
        return None
    return settings.WALL_HUB_URL.rstrip("/") + reverse("device-detail", args=[device.pk])


def subject(alert: Alert) -> str:
    state = "DOWN" if alert.kind == Alert.Kind.DOWN else "back UP"
    return f"[wall] {alert.device} ({alert.device.ip}) is {state}"


def body(alert: Alert) -> str:
    text = alert.message
    link = device_link(alert.device)
    if link:
        text += f"\n\n{link}"
    return text + FOOTER


def deliver(subject_text: str, body_text: str, alerts: list[Alert]) -> None:
    """Send one email about these alerts and record the outcome on each of them."""
    recipients = settings.WALL_ALERT_EMAILS
    if not recipients:
        log.info("not emailed (WALL_ALERT_EMAILS is empty): %s", subject_text)
        return
    try:
        send_mail(subject_text, body_text, None, recipients)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("could not email %r: %s", subject_text, exc)
        for alert in alerts:
            alert.email_error = f"{type(exc).__name__}: {exc}"
    else:
        for alert in alerts:
            alert.emailed_to = ", ".join(recipients)
    for alert in alerts:
        alert.save(update_fields=["emailed_to", "email_error"])


def send(alert: Alert) -> None:
    """Email a device going down or coming back up."""
    deliver(subject(alert), body(alert), [alert])


def send_new_devices(new: list[Alert]) -> None:
    """One email for all the devices a scan saw for the first time."""
    if not new:
        return
    if len(new) == 1:
        subject_text = f"[wall] New device on the network: {new[0].device.ip}"
    else:
        subject_text = f"[wall] {len(new)} new devices on the network"
    lines = ["Seen on the network for the first time:", ""]
    for alert in new:
        lines.append("  " + alert.message.removeprefix("New device on the network: "))
        link = device_link(alert.device)
        if link:
            lines.append(f"    {link}")
    lines += ["", "If you do not recognise a device, find out who connected it."]
    deliver(subject_text, "\n".join(lines) + FOOTER, new)


def send_low_supplies(device: Device, low: list[Alert]) -> None:
    """One email for the supplies of one device that have just run low."""
    if not low:
        return
    count = f"{len(low)} supplies" if len(low) > 1 else "Supply"
    subject_text = f"[wall] {count} low: {device} ({device.ip})"
    lines = [alert.message for alert in low]
    link = device_link(device)
    if link:
        lines += ["", link]
    deliver(subject_text, "\n".join(lines) + FOOTER, low)
