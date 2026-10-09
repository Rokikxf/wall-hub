"""Storing a validated wall-scan document: the scan's outcome and the device inventory.

The hard part is identity: deciding which known Device a scanned (ip, mac) pair is.
IP addresses change (DHCP) and MAC addresses are missing from unprivileged scans or
from devices behind a router, so neither alone is a reliable key. See find_device.
"""

from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inventory.models import Alert, Device, Scan


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


def record_device(found: dict[str, Any], scan: Scan, now: datetime) -> tuple[Device, bool]:
    """Create or update the Device for one entry of result.devices.

    Returns the device and whether it is new. Unknown values (null) do not erase
    known ones: an inventory keeps the last known hostname or vendor even if one
    scan could not see it.
    """
    known = find_device(found["ip"], found["mac"])
    device = known or Device(first_seen=now)
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
    return device, known is None


def describe_new_device(found: dict[str, Any]) -> str:
    details = [f"MAC {found['mac']}" if found["mac"] else "no MAC address"]
    details.append(found["vendor"] or "unknown vendor")
    if found["hostname"]:
        details.append(f"hostname {found['hostname']}")
    if found["open_ports"]:
        details.append("open ports " + ", ".join(str(p["port"]) for p in found["open_ports"]))
    return f"New device on the network: {found['ip']} ({', '.join(details)})."


def apply_scan(scan: Scan, document: dict[str, Any]) -> list[Alert]:
    """Store a validated wall-scan document on the scan and update the inventory.

    Returns an Alert for each device seen for the first time, for the caller to
    email once the database work is done. The very first scan, into an empty
    inventory, is the baseline: it reports nothing as new, or every device in the
    office would be an alert.
    """
    now = timezone.now()
    new_devices = []
    with transaction.atomic():
        baseline = not Device.objects.exists()
        scan.output = document
        scan.status = document["status"]
        scan.message = "; ".join(error["message"] for error in document["errors"])
        if document["result"] is not None:
            devices = document["result"]["devices"]
            for found in devices:
                device, new = record_device(found, scan, now)
                if new and not baseline and settings.WALL_ALERT_NEW_DEVICES:
                    new_devices.append(
                        Alert.objects.create(
                            device=device, kind=Alert.Kind.NEW, message=describe_new_device(found)
                        )
                    )
            scan.device_count = len(devices)
        scan.finished_at = now
        scan.save()
    return new_devices
