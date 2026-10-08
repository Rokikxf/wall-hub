"""Alert emails: what they say, and that a broken mail server never stops monitoring."""

import smtplib

import pytest

from inventory.alerts import send
from inventory.models import Alert

pytestmark = pytest.mark.django_db


@pytest.fixture
def alert(make_device):
    device = make_device("192.168.1.50", hostname="printer.lan")
    return Alert.objects.create(
        device=device, kind=Alert.Kind.DOWN, message="printer.lan (192.168.1.50) is down: ..."
    )


def test_alert_email(alert, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = ["it@example.com", "owner@example.com"]
    settings.WALL_HUB_URL = "http://192.168.1.10:8000/"

    send(alert)

    [email] = mailoutbox
    assert email.subject == "[wall] printer.lan (192.168.1.50) is DOWN"
    assert email.to == ["it@example.com", "owner@example.com"]
    assert email.body.startswith("printer.lan (192.168.1.50) is down: ...")
    assert f"http://192.168.1.10:8000/devices/{alert.device.pk}/" in email.body
    alert.refresh_from_db()
    assert alert.emailed_to == "it@example.com, owner@example.com"


def test_no_recipients_means_no_email(alert, mailoutbox, settings):
    settings.WALL_ALERT_EMAILS = []

    send(alert)

    assert mailoutbox == []
    alert.refresh_from_db()
    assert (alert.emailed_to, alert.email_error) == ("", "")


@pytest.mark.parametrize(
    "error",
    [smtplib.SMTPAuthenticationError(535, b"bad credentials"), ConnectionRefusedError(111)],
    ids=["smtp-error", "server-down"],
)
def test_mail_server_problems_are_recorded_not_raised(alert, monkeypatch, settings, error):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr("inventory.alerts.send_mail", broken)

    send(alert)

    alert.refresh_from_db()
    assert alert.emailed_to == ""
    assert alert.email_error.startswith(type(error).__name__)
