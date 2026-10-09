"""Warranty and licence expiry: what is due soon, and the daily reminder email.

Reminders are sent a fixed number of days before each date (by default 30, 7
and 1 days before, and on the day itself; WALL_EXPIRY_REMINDER_DAYS). Because the
rule depends only on today's date, nothing has to be stored to avoid repeats:
each item is in at most one digest per reminder day.
"""

import logging
import smtplib
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import QuerySet
from django.urls import reverse

from inventory.models import Device, Licence

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Expiry:
    what: str  # "Warranty" or "Licence"
    item: Device | Licence
    date: date

    def days_left(self, today: date) -> int:
        return (self.date - today).days

    def describe(self) -> str:
        if isinstance(self.item, Device):
            name = str(self.item)
            return name if name == self.item.ip else f"{name} ({self.item.ip})"
        seats = self.item.seats if self.item.seats is not None else "unlimited"
        return f"{self.item} ({self.item.seats_used}/{seats} seats)"


def _merge(devices: QuerySet, licences: QuerySet) -> list[Expiry]:
    items = [Expiry("Warranty", d, d.warranty_expires) for d in devices]
    items += [Expiry("Licence", lic, lic.expires) for lic in licences]
    return sorted(items, key=lambda e: (e.date, e.what, str(e.item)))


def between(start: date, end: date) -> list[Expiry]:
    """Warranties and licences ending between start and end, both included, soonest first."""
    return _merge(
        Device.objects.filter(warranty_expires__range=(start, end)),
        Licence.objects.filter(expires__range=(start, end)),
    )


def due_for_reminder(today: date, days_before: list[int]) -> list[Expiry]:
    dates = [today + timedelta(days=days) for days in days_before]
    return _merge(
        Device.objects.filter(warranty_expires__in=dates),
        Licence.objects.filter(expires__in=dates),
    )


def when(days: int) -> str:
    if days == 0:
        return "today"
    return f"in {days} day{'s' if days != 1 else ''}"


def reminder_text(items: list[Expiry], today: date) -> str:
    lines = ["These warranties and licences expire soon:", ""]
    for item in items:
        days = when(item.days_left(today))
        lines.append(f"  {item.date:%d %b %Y}  {days:<11} {item.what:<9} {item.describe()}")
    if settings.WALL_HUB_URL:
        lines += ["", settings.WALL_HUB_URL.rstrip("/") + reverse("expiring")]
    return "\n".join(lines) + "\n\n-- \nSent by wall-hub.\n"


def send_reminders(today: date) -> int:
    """Email today's digest, if anything is due. Returns the number of items due."""
    items = due_for_reminder(today, settings.WALL_EXPIRY_REMINDER_DAYS)
    if not items:
        return 0
    recipients = settings.WALL_ALERT_EMAILS
    if not recipients:
        log.info("expiry reminder not emailed (WALL_ALERT_EMAILS is empty): %d item(s)", len(items))
        return len(items)
    subject = f"[wall] Expiry reminder: {len(items)} item{'s' if len(items) != 1 else ''}"
    try:
        send_mail(subject, reminder_text(items, today), None, recipients)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("could not email the expiry reminder: %s", exc)
    return len(items)
