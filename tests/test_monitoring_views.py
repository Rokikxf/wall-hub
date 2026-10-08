"""Monitoring in the web pages: device page and settings, health on the list, alerts."""

import pytest
from django.urls import reverse
from django.utils import timezone

from inventory.models import Alert, HealthRun

pytestmark = pytest.mark.django_db


def test_device_page(logged_in, make_device):
    device = make_device("192.168.1.20", hostname="office-pc01.lan")

    content = logged_in.get(reverse("device-detail", args=[device.pk])).content.decode()

    assert "office-pc01.lan" in content
    assert "Monitor this device" in content
    assert "No alerts." in content


def test_turning_monitoring_on_resets_health(logged_in, make_device):
    device = make_device("192.168.1.20", health="down", consecutive_failures=3)

    response = logged_in.post(
        reverse("device-detail", args=[device.pk]), {"monitored": "on", "check_port": "445"}
    )

    assert response.status_code == 302
    device.refresh_from_db()
    assert (device.monitored, device.check_port) == (True, 445)
    assert (device.health, device.consecutive_failures) == ("unknown", 0)


def test_saving_unchanged_settings_keeps_health(logged_in, make_device):
    device = make_device("192.168.1.20", monitored=True, health="up")

    logged_in.post(reverse("device-detail", args=[device.pk]), {"monitored": "on"})

    device.refresh_from_db()
    assert device.health == "up"


def test_invalid_port_is_rejected(logged_in, make_device):
    device = make_device("192.168.1.20")

    response = logged_in.post(
        reverse("device-detail", args=[device.pk]), {"monitored": "on", "check_port": "70000"}
    )

    assert response.status_code == 200
    assert "65535" in response.content.decode()
    device.refresh_from_db()
    assert device.monitored is False


def test_device_list_shows_health(logged_in, make_device):
    make_device("192.168.1.1", monitored=True, health="up", last_rtt_ms=1.42)
    make_device("192.168.1.50", monitored=True, health="down", down_since=timezone.now())
    make_device("192.168.1.77")

    content = logged_in.get(reverse("device-list")).content.decode()

    assert "Up · 1.4 ms" in content
    assert "Down since" in content
    assert "not monitored" in content
    assert "2 monitored. Waiting for the first health check." in content
    assert 'hx-trigger="every 30s"' in content


def test_device_list_shows_a_failing_monitor(logged_in, make_device):
    make_device("192.168.1.1", monitored=True)
    HealthRun.objects.create(status="error", message="This user may not open ICMP sockets.")

    content = logged_in.get(reverse("device-list")).content.decode()

    assert "Error: This user may not open ICMP sockets." in content


def test_alert_list(logged_in, make_device):
    device = make_device("192.168.1.50", hostname="printer.lan")
    Alert.objects.create(device=device, kind="down", message="is down", emailed_to="it@example.com")
    Alert.objects.create(device=device, kind="up", message="is back up", email_error="SMTP 421")

    content = logged_in.get(reverse("alert-list")).content.decode()

    assert reverse("device-detail", args=[device.pk]) in content
    assert "it@example.com" in content
    assert "failed" in content
