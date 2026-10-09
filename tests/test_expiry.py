"""Warranty and licence expiry: the overview page, badges and the daily reminder email."""

import smtplib
from datetime import date

import pytest
from django.template import Context, Template
from django.urls import reverse

from inventory import expiry, tasks
from inventory.models import Licence

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 8)


@pytest.fixture
def due(make_device):
    """Items ending 0, 1, 2, 7, 30 and 31 days from TODAY, and one 3 days ago."""
    make_device("192.168.1.50", name="Reception printer", warranty_expires=date(2026, 10, 8))
    make_device("192.168.1.20", warranty_expires=date(2026, 10, 9))
    make_device("192.168.1.21", warranty_expires=date(2026, 10, 10))
    Licence.objects.create(name="Antivirus", seats=10, expires=date(2026, 10, 15))
    Licence.objects.create(name="Microsoft 365", seats=None, expires=date(2026, 11, 7))
    Licence.objects.create(name="Backup", expires=date(2026, 11, 8))
    make_device("192.168.1.22", warranty_expires=date(2026, 10, 5))


def test_between_includes_both_ends_and_sorts_by_date(due):
    items = expiry.between(date(2026, 10, 8), date(2026, 10, 15))

    assert [(i.date.day, i.what) for i in items] == [
        (8, "Warranty"),
        (9, "Warranty"),
        (10, "Warranty"),
        (15, "Licence"),
    ]


def test_reminders_are_due_on_the_configured_days_only(due):
    items = expiry.due_for_reminder(TODAY, [30, 7, 1, 0])

    assert [i.describe() for i in items] == [
        "Reception printer (192.168.1.50)",  # today
        "192.168.1.20",  # in 1 day
        "Antivirus (0/10 seats)",  # in 7 days
        "Microsoft 365 (0/unlimited seats)",  # in 30 days
    ]


def test_reminder_email(due, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    settings.WALL_HUB_URL = "http://192.168.1.10:8000"

    assert expiry.send_reminders(TODAY) == 4

    [email] = mailoutbox
    assert email.subject == "[wall] Expiry reminder: 4 items"
    assert email.to == ["it@example.com"]
    lines = email.body.splitlines()
    assert "  08 Oct 2026  today       Warranty  Reception printer (192.168.1.50)" in lines
    assert "  09 Oct 2026  in 1 day    Warranty  192.168.1.20" in lines
    assert "  15 Oct 2026  in 7 days   Licence   Antivirus (0/10 seats)" in lines
    assert "http://192.168.1.10:8000/expiring/" in lines


def test_no_email_when_nothing_is_due(make_device, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    make_device("192.168.1.20", warranty_expires=date(2026, 10, 10))  # in 2 days

    assert expiry.send_reminders(TODAY) == 0
    assert mailoutbox == []


def test_no_email_without_recipients(due, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = []

    assert expiry.send_reminders(TODAY) == 4
    assert mailoutbox == []


def test_mail_failure_is_logged_not_raised(due, monkeypatch, settings, caplog):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]

    def broken(*args, **kwargs):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr("inventory.expiry.send_mail", broken)

    assert expiry.send_reminders(TODAY) == 4
    assert "could not email the expiry reminder" in caplog.text


def test_task_uses_the_local_date(due, monkeypatch, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    monkeypatch.setattr(tasks.timezone, "localdate", lambda: TODAY)

    assert tasks.send_expiry_reminders() == 4
    assert len(mailoutbox) == 1


def test_beat_runs_the_reminder_daily():
    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["expiry-reminders"]
    assert entry["task"] == "inventory.tasks.send_expiry_reminders"
    assert entry["schedule"].hour == {settings.WALL_EXPIRY_REMINDER_HOUR}


@pytest.mark.parametrize(
    "days, expected",
    [
        (-3, "Ended"),
        (0, "today"),
        (5, "in 5 days"),
        (60, ""),  # plain date, no badge
    ],
)
def test_expiry_badge(monkeypatch, days, expected):
    monkeypatch.setattr("inventory.templatetags.inventory_tags.timezone.localdate", lambda: TODAY)
    when = date.fromordinal(TODAY.toordinal() + days)

    html = Template("{% load inventory_tags %}{% expiry_badge when %}").render(
        Context({"when": when})
    )

    assert expected in html
    assert ("badge" in html) == (days <= 30)


def test_expiry_badge_without_a_date():
    html = Template('{% load inventory_tags %}{% expiry_badge None "Does not expire" %}').render(
        Context()
    )
    assert "Does not expire" in html


def test_expiring_page(logged_in, due, monkeypatch):
    monkeypatch.setattr("inventory.asset_views.timezone.localdate", lambda: TODAY)

    response = logged_in.get(reverse("expiring"))

    upcoming = [(item.describe(), days) for item, days in response.context["upcoming"]]
    ended = [(item.describe(), days) for item, days in response.context["ended"]]
    assert upcoming[0] == ("Reception printer (192.168.1.50)", 0)
    assert len(upcoming) == 6
    assert ended == [("192.168.1.22", 3)]
    assert "30, 7, 1, 0 days before" in response.content.decode()
