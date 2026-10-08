"""The web pages: login, device list, scan form and scan status."""

import pytest
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError

from inventory.ingest import apply_scan
from inventory.models import Device, Scan

pytestmark = pytest.mark.django_db


@pytest.fixture
def queued(monkeypatch):
    """Capture scans handed to Celery instead of sending them to Redis."""
    scan_ids = []
    monkeypatch.setattr("inventory.views.run_scan.delay", scan_ids.append)
    return scan_ids


@pytest.mark.parametrize("name", ["device-list", "scan-list"])
def test_pages_need_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_login_page(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert b"Log in" in response.content


def test_logout(logged_in):
    response = logged_in.post(reverse("logout"))
    assert response.status_code == 302
    assert logged_in.get(reverse("device-list")).status_code == 302


def test_empty_device_list(logged_in):
    response = logged_in.get(reverse("device-list"))
    assert b"No devices yet" in response.content


def test_devices_are_listed_in_numeric_ip_order(logged_in):
    now = timezone.now()
    for ip in ["192.168.1.100", "192.168.1.9", "192.168.1.10"]:
        Device.objects.create(ip=ip, first_seen=now, last_seen=now)

    content = logged_in.get(reverse("device-list")).content.decode()

    positions = [content.index(ip + "<") for ip in ["192.168.1.9", "192.168.1.10", "192.168.1.100"]]
    assert positions == sorted(positions)


def test_scan_form_queues_a_scan(logged_in, queued):
    response = logged_in.post(reverse("scan-list"), {"targets": "192.168.1.0/24, 10.0.0.5"})

    assert response.status_code == 302
    scan = Scan.objects.get()
    assert scan.targets == "192.168.1.0/24 10.0.0.5"
    assert scan.requested_by == logged_in.user
    assert scan.status == "queued"
    assert queued == [scan.pk]


@pytest.mark.parametrize(
    "targets, error",
    [
        ("8.8.8.8", "not a private address range"),
        ("10.0.0.0/8", "larger than a /16"),
        ("printer", "not an IPv4 address"),
    ],
)
def test_scan_form_rejects_bad_targets(logged_in, queued, targets, error):
    response = logged_in.post(reverse("scan-list"), {"targets": targets})

    assert response.status_code == 200
    assert error in response.content.decode()
    assert not Scan.objects.exists()
    assert queued == []


def test_scan_fails_cleanly_when_redis_is_down(logged_in, monkeypatch):
    def broker_down(scan_id):
        raise OperationalError("Error 111 connecting to localhost:6379. Connection refused.")

    monkeypatch.setattr("inventory.views.run_scan.delay", broker_down)

    response = logged_in.post(reverse("scan-list"), {"targets": "192.168.1.0/24"}, follow=True)

    scan = Scan.objects.get()
    assert scan.status == "failed"
    assert "is Redis running?" in scan.message
    assert "is Redis running?" in response.content.decode()


def test_unfinished_scan_rows_poll_and_finished_rows_stop(logged_in):
    scan = Scan.objects.create(targets="192.168.1.0/24", status="running")
    url = reverse("scan-row", args=[scan.pk])

    assert 'hx-trigger="every 2s"' in logged_in.get(url).content.decode()

    scan.status = "ok"
    scan.save()
    assert "hx-trigger" not in logged_in.get(url).content.decode()


def test_scan_detail(logged_in, example):
    scan = Scan.objects.create(targets="192.168.1.0/24")
    apply_scan(scan, example("wall-scan", "ok.json"))

    content = logged_in.get(reverse("scan-detail", args=[scan.pk])).content.decode()

    assert "Devices found (5)" in content
    assert "3c:52:82:ab:cd:ef" in content
    assert "Raw output" in content


def test_detail_of_a_failed_scan(logged_in):
    scan = Scan.objects.create(
        targets="192.168.1.0/24",
        status="failed",
        message="wall-scan exited with code 1 without printing a JSON document",
        stderr="Traceback (most recent call last):",
    )

    content = logged_in.get(reverse("scan-detail", args=[scan.pk])).content.decode()

    assert "without printing a JSON document" in content
    assert "Traceback" in content
