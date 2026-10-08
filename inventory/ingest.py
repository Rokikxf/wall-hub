"""Storing a validated wall-scan document: the scan's outcome and the device inventory.

The hard part is identity: deciding which known Device a scanned (ip, mac) pair is.
IP addresses change (DHCP) and MAC addresses are missing from unprivileged scans or
from devices behind a router, so neither alone is a reliable key. See find_device.
"""

from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from inventory.models import Device, Scan


def find_device(ip: str, mac: str | None) -> Device | None:
    """Which known device a scanned (ip, mac) pair belongs to, if any.

    1. A known MAC address identifies the device, whatever its IP address is now.
    2. Otherwise the device most recently seen at the same IP address is the same
       device, unless both have MAC addresses: different MACs mean a different
       device has taken over the address.

    Known limits: phones and laptops that randomise their MAC address show up as a
    new device whenever the address changes, and two devices that swap IP
    addresses between scans without MACs being visible are confused.
    """
    if mac:
        device = Device.objects.filter(mac=mac).first()
        if device is not None:
            return device
    for device in Device.objects.filter(ip=ip).order_by("-last_seen"):
        if mac is None or device.mac is None:
            return device
    return None


def record_device(found: dict[str, Any], scan: Scan, now: datetime) -> Device:
    """Create or update the Device for one entry of result.devices.

    Unknown values (null) do not erase known ones: an inventory keeps the last
    known hostname or vendor even if one scan could not see it.
    """
    device = find_device(found["ip"], found["mac"]) or Device(first_seen=now)
    device.ip = found["ip"]
    if found["mac"]:
        device.mac = found["mac"]
    if found["vendor"]:
        device.vendor = found["vendor"]
    if found["hostname"]:
        device.hostname = found["hostname"]
    if found["open_ports"] is not None:
        device.open_ports = found["open_ports"]
    device.last_seen = now
    device.last_scan = scan
    device.save()
    return device


def apply_scan(scan: Scan, document: dict[str, Any]) -> None:
    """Store a validated wall-scan document on the scan and update the inventory."""
    now = timezone.now()
    with transaction.atomic():
        scan.output = document
        scan.status = document["status"]
        scan.message = "; ".join(error["message"] for error in document["errors"])
        if document["result"] is not None:
            devices = document["result"]["devices"]
            for found in devices:
                record_device(found, scan, now)
            scan.device_count = len(devices)
        scan.finished_at = now
        scan.save()
