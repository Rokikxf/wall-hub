"""Scans without typed addresses (wall-scan --local), automatic scans, and new-device alerts."""

import copy
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from inventory.ingest import apply_scan, describe_new_device
from inventory.models import Alert, Device, Scan
from inventory.tasks import auto_scan, scan_command
from wallhub.settings import auto_scan_schedule

pytestmark = pytest.mark.django_db


def found(ip, mac=None, vendor=None, hostname=None, open_ports=None):
    return {
        "ip": ip,
        "mac": mac,
        "vendor": vendor,
        "hostname": hostname,
        "discovery_reason": "arp-response",
        "open_ports": open_ports,
    }


def scan_finding(*devices):
    """apply_scan for a new Scan whose result lists these devices; returns the new alerts."""
    scan = Scan.objects.create(local=True)
    document = {"status": "ok", "errors": [], "result": {"devices": list(devices)}}
    return apply_scan(scan, document)


# --- the wall-scan command line ---


@pytest.mark.parametrize(
    "fields, privileged, exclude, expected",
    [
        ({"targets": "192.168.1.0/24"}, False, [], ["192.168.1.0/24", "--timeout-s", "600"]),
        ({"local": True}, True, [], ["--local", "--timeout-s", "600", "--privileged"]),
        (
            {"local": True, "ports": False},
            True,
            ["enp0s3", "eth1"],
            [
                "--local",
                "--exclude-interface",
                "enp0s3",
                "--exclude-interface",
                "eth1",
                "--no-ports",
                "--timeout-s",
                "600",
                "--privileged",
            ],
        ),  # fmt: skip
        (
            {"targets": "10.0.0.5", "local": True},
            False,
            [],
            ["10.0.0.5", "--local", "--timeout-s", "600"],
        ),
    ],
    ids=["typed", "local", "local-discovery-excluding", "typed-and-local"],
)
def test_scan_command(settings, fields, privileged, exclude, expected):
    settings.WALL_SCAN_PRIVILEGED = privileged
    settings.WALL_SCAN_EXCLUDE_INTERFACES = exclude

    assert scan_command(Scan(**fields)) == ["wall-scan", *expected]


# --- automatic scans ---


def test_auto_scan_runs_a_local_scan(fake_tool, example, settings):
    settings.WALL_SCAN_PRIVILEGED = True
    fake_tool(stdout=example("wall-scan", "discovery-only.json"))

    assert auto_scan(ports=False) == "ok"

    scan = Scan.objects.get()
    assert (scan.local, scan.ports, scan.automatic, scan.targets) == (True, False, True, "")
    assert "--local" in fake_tool.calls[0] and "--no-ports" in fake_tool.calls[0]
    assert scan.scanned_networks == ["192.168.1.0/24"]


def test_auto_scan_waits_for_a_scan_in_progress(fake_tool):
    Scan.objects.create(targets="192.168.1.0/24", status="running")

    assert auto_scan(ports=True) == "another scan is in progress"
    assert fake_tool.calls == []
    assert Scan.objects.count() == 1


def test_a_scan_stuck_for_hours_does_not_block_auto_scans(fake_tool, example):
    stuck = Scan.objects.create(targets="192.168.1.0/24", status="running")
    Scan.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(hours=3))
    fake_tool(stdout=example("wall-scan", "discovery-only.json"))

    assert auto_scan(ports=False) == "ok"


def test_schedule_is_off_unless_configured():
    assert auto_scan_schedule(0, "") == {}

    entries = auto_scan_schedule(60, "2")

    assert entries["auto-discovery"]["schedule"] == 3600
    assert entries["auto-discovery"]["kwargs"] == {"ports": False}
    assert entries["auto-port-scan"]["schedule"].hour == {2}
    assert entries["auto-port-scan"]["kwargs"] == {"ports": True}


# --- new devices ---


def test_the_first_scan_is_the_baseline_and_alerts_nothing():
    assert scan_finding(found("192.168.1.1"), found("192.168.1.20")) == []
    assert Device.objects.count() == 2
    assert not Alert.objects.exists()


def test_a_device_seen_for_the_first_time_is_an_alert():
    scan_finding(found("192.168.1.1", mac="50:c7:bf:12:34:56"))

    new = scan_finding(
        found("192.168.1.1", mac="50:c7:bf:12:34:56"),  # known
        found("192.168.1.77", mac="6a:1f:3e:90:22:41", open_ports=[{"port": 22}]),
    )

    [alert] = new
    assert alert.kind == Alert.Kind.NEW
    assert alert.device.ip == "192.168.1.77"
    assert alert.message == (
        "New device on the network: 192.168.1.77 "
        "(MAC 6a:1f:3e:90:22:41, unknown vendor, open ports 22)."
    )


def test_new_device_alerts_can_be_turned_off(settings):
    settings.WALL_ALERT_NEW_DEVICES = False
    scan_finding(found("192.168.1.1"))

    assert scan_finding(found("192.168.1.2")) == []


def test_describe_new_device_with_everything():
    text = describe_new_device(
        found("192.168.1.50", "3c:52:82:ab:cd:ef", "Hewlett Packard", "npi1a2b3c.lan",
              [{"port": 80}, {"port": 9100}])
    )  # fmt: skip
    assert text == (
        "New device on the network: 192.168.1.50 (MAC 3c:52:82:ab:cd:ef, Hewlett Packard, "
        "hostname npi1a2b3c.lan, open ports 80, 9100)."
    )


def test_new_devices_are_emailed_once_per_scan(fake_tool, example, settings, mailoutbox):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    settings.WALL_HUB_URL = "http://192.168.56.10:8000"
    scan_finding(found("192.168.1.1"))  # baseline
    document = copy.deepcopy(example("wall-scan", "ok.json"))  # 5 devices, 4 of them new
    fake_tool(stdout=document)

    auto_scan(ports=True)

    [email] = mailoutbox
    assert email.subject == "[wall] 4 new devices on the network"
    assert "  192.168.1.77 (MAC 6a:1f:3e:90:22:41, unknown vendor)." in email.body
    new = Alert.objects.filter(kind="new")
    assert new.count() == 4
    assert set(new.values_list("emailed_to", flat=True)) == {"it@example.com"}
    pc = Device.objects.get(ip="192.168.1.20")
    assert f"http://192.168.56.10:8000/devices/{pc.pk}/" in email.body


def test_one_new_device_gets_its_own_subject(settings, mailoutbox):
    from inventory.alerts import send_new_devices

    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    scan_finding(found("192.168.1.1"))
    send_new_devices(scan_finding(found("192.168.1.99")))

    assert mailoutbox[0].subject == "[wall] New device on the network: 192.168.1.99"


def test_mail_failure_is_recorded_on_every_new_device(settings, monkeypatch):
    from inventory.alerts import send_new_devices

    settings.WALL_ALERT_EMAILS = ["it@example.com"]

    def broken(*args, **kwargs):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr("inventory.alerts.send_mail", broken)
    scan_finding(found("192.168.1.1"))
    send_new_devices(scan_finding(found("192.168.1.2"), found("192.168.1.3")))

    errors = set(Alert.objects.values_list("email_error", flat=True))
    assert len(errors) == 1 and errors.pop().startswith("ConnectionRefusedError")


# --- pages and the command line ---


def test_scan_local_networks_button(logged_in, monkeypatch):
    queued = []
    monkeypatch.setattr("inventory.views.run_scan.delay", queued.append)

    response = logged_in.post(reverse("scan-list"), {"local": "1"}, follow=True)

    scan = Scan.objects.get()
    assert (scan.local, scan.targets, scan.requested_by) == (True, "", logged_in.user)
    assert queued == [scan.pk]
    assert "Scan of local networks queued." in response.content.decode()


def test_scan_list_shows_local_and_automatic_scans(logged_in, example, settings):
    settings.WALL_AUTO_SCAN_INTERVAL_MIN = 60
    settings.WALL_AUTO_PORT_SCAN_HOUR = "2"
    scan = Scan.objects.create(local=True, ports=False, automatic=True)
    apply_scan(scan, example("wall-scan", "discovery-only.json"))

    content = logged_in.get(reverse("scan-list")).content.decode()

    assert "local networks" in content
    assert "discovery only" in content
    assert "192.168.1.0/24" in content  # what --local found
    assert "schedule" in content
    assert "a quick sweep every 60 min, a port scan daily at 2:30" in content


def test_new_device_alerts_are_listed(logged_in):
    scan_finding(found("192.168.1.1"))
    scan_finding(found("192.168.1.99"))

    content = logged_in.get(reverse("alert-list")).content.decode()

    assert "New device" in content
    assert "192.168.1.99" in content


def test_scan_command_with_local(monkeypatch):
    queued = []
    monkeypatch.setattr("inventory.views.run_scan.delay", queued.append)
    out = StringIO()

    call_command("scan", "--local", stdout=out)

    assert "queued: local networks" in out.getvalue()
    assert Scan.objects.get().local is True


def test_scan_command_needs_targets_or_local():
    with pytest.raises(CommandError, match="at least one target, or --local"):
        call_command("scan")
