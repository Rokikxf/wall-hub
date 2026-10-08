"""Storing scan results, and matching scanned devices to known ones."""

from typing import Any

import pytest

from inventory.ingest import apply_scan
from inventory.models import Device, Scan

pytestmark = pytest.mark.django_db


def found(ip, mac=None, vendor=None, hostname=None, open_ports=None) -> dict[str, Any]:
    return {
        "ip": ip,
        "mac": mac,
        "vendor": vendor,
        "hostname": hostname,
        "discovery_reason": "arp-response",
        "open_ports": open_ports,
    }


def scan_with(*devices, status="ok", errors=()) -> Scan:
    """Run apply_scan for a new Scan whose result lists the given devices."""
    scan = Scan.objects.create(targets="192.168.1.0/24")
    document = {
        "status": status,
        "errors": list(errors),
        "result": {"devices": list(devices)},
    }
    apply_scan(scan, document)
    return scan


MAC_A = "d4:81:d7:0a:1b:2c"
MAC_B = "aa:bb:cc:00:11:22"


def test_example_document(example):
    scan = Scan.objects.create(targets="192.168.1.0/24")

    apply_scan(scan, example("wall-scan", "ok.json"))

    scan.refresh_from_db()
    assert scan.status == "ok"
    assert scan.device_count == 5
    assert scan.finished_at is not None
    assert Device.objects.count() == 5
    printer = Device.objects.get(ip="192.168.1.50")
    assert (printer.mac, printer.vendor, printer.hostname) == (
        "3c:52:82:ab:cd:ef",
        "Hewlett Packard",
        "npi1a2b3c.lan",
    )
    assert [p["port"] for p in printer.open_ports] == [80, 443, 9100]
    assert printer.first_seen == printer.last_seen
    assert printer.last_scan == scan


def test_known_mac_at_a_new_ip_is_the_same_device():
    scan_with(found("192.168.1.20", MAC_A))
    scan_with(found("192.168.1.30", MAC_A))

    device = Device.objects.get()
    assert device.ip == "192.168.1.30"


def test_unprivileged_scan_matches_by_ip_and_keeps_the_mac():
    scan_with(found("192.168.1.20", MAC_A, vendor="Dell"))
    scan_with(found("192.168.1.20"))

    device = Device.objects.get()
    assert (device.mac, device.vendor) == (MAC_A, "Dell")


def test_mac_seen_for_the_first_time_joins_the_device_known_by_ip():
    scan_with(found("192.168.1.20"))
    scan_with(found("192.168.1.20", MAC_A))

    assert Device.objects.get().mac == MAC_A


def test_different_mac_at_a_known_ip_is_a_new_device():
    scan_with(found("192.168.1.20", MAC_A))
    scan_with(found("192.168.1.20", MAC_B))

    assert sorted(Device.objects.values_list("mac", flat=True)) == [MAC_B, MAC_A]


def test_unknown_values_do_not_erase_known_ones():
    first = scan_with(found("192.168.1.20", hostname="pc.lan", open_ports=[{"port": 22}]))
    scan_with(found("192.168.1.20"))  # discovery only, no reverse DNS this time

    device = Device.objects.get()
    assert device.hostname == "pc.lan"
    assert device.open_ports == [{"port": 22}]
    assert device.first_seen == first.finished_at

    scan_with(found("192.168.1.20", open_ports=[]))  # ports scanned, none open now
    device.refresh_from_db()
    assert device.open_ports == []


def test_error_document(example):
    scan = Scan.objects.create(targets="192.168.1.0/24")

    apply_scan(scan, example("wall-scan", "error.json"))

    assert scan.status == "error"
    assert scan.message == "nmap executable not found: nmap"
    assert scan.device_count is None
    assert not Device.objects.exists()


def test_partial_document_keeps_devices_and_explains():
    error = {"code": "some_problem", "message": "Part of the range was skipped", "target": None}

    scan = scan_with(found("192.168.1.20"), status="partial", errors=[error])

    assert scan.status == "partial"
    assert scan.message == "Part of the range was skipped"
    assert Device.objects.count() == 1
