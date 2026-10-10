"""Wake-on-LAN: where the magic packets go, and whether the device woke up.

Where: the directed broadcast address of the network a scan found the device
on, e.g. 10.180.103.255 for 10.180.103.0/24. 255.255.255.255 leaves through
the network card with the default route (on the lab VM, VirtualBox's NAT
adapter), but a directed broadcast always leaves through the card on that
network. When no scan covered a network the device is in, WALL_WOL_BROADCAST
is used.

Whether it woke: Wake-on-LAN has no reply. So after sending, the device is
checked with wall-healthcheck (ping, or its TCP check port) every
WALL_WOL_CHECK_INTERVAL_S seconds, until it answers or WALL_WOL_WAIT_S has
passed.
"""

import ipaddress
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings

from inventory.models import Device, Scan, Wake
from inventory.monitoring import describe_check
from inventory.templatetags.inventory_tags import duration

# Scans to look through for the device's network, newest first.
RECENT_SCANS = 50
# A check that runs later than this after the deadline (queued tasks wait while
# the worker restarts) says nothing about whether the device woke in time.
LATE_CHECK = timedelta(seconds=60)


def device_network(device: Device) -> ipaddress.IPv4Network | None:
    """The most specific scanned network that contains the device's address.

    The device's last scan is looked at first. If that scanned only single
    addresses, the most recent scan that covered a whole network it is in.
    """
    ip = ipaddress.IPv4Address(device.ip)
    target_lists = [device.last_scan.scanned_networks] if device.last_scan else []
    recent = Scan.objects.filter(output__isnull=False).order_by("-pk")
    target_lists += recent.values_list("output__params__targets", flat=True)[:RECENT_SCANS]
    for targets in target_lists:
        networks = []
        for target in targets or []:
            try:
                network = ipaddress.IPv4Network(target, strict=False)
            except ValueError:
                continue
            # A /31 or /32 has no broadcast address.
            if ip in network and network.prefixlen <= 30:
                networks.append(network)
        if networks:
            return max(networks, key=lambda network: network.prefixlen)
    return None


def wake_broadcast(device: Device) -> tuple[str, ipaddress.IPv4Network | None]:
    """Where to send the magic packets, and the network that address belongs to."""
    network = device_network(device)
    if network is None:
        return settings.WALL_WOL_BROADCAST, None
    return str(network.broadcast_address), network


def add_note(wake: Wake, note: str) -> None:
    wake.message = " ".join(part for part in [wake.message, note] if part)


def finish(wake: Wake, status: str, note: str, now: datetime) -> None:
    """End a wake (not saved). The note is added to what the wake already says."""
    wake.status = status
    add_note(wake, note)
    wake.finished_at = now


def record_send(
    wake: Wake, document: dict[str, Any], network: ipaddress.IPv4Network | None, now: datetime
) -> bool:
    """Store the wall-wol document on its wake. Returns True if the device is to be checked."""
    wake.output = document
    wake.message = " ".join(error["message"] for error in document["errors"])
    result = document["result"]
    if result is None:  # nothing was sent
        finish(wake, Wake.Status.ERROR, "", now)
        wake.save()
        return False

    wake.source_ip = result["source_ip"]
    wake.sent_at = now
    if network is None:
        left = f" and left from {wake.source_ip}" if wake.source_ip else ""
        add_note(
            wake,
            f"No scan has covered the network of {wake.device.ip}, so the packets went to "
            f"{wake.broadcast}{left}. If the device does not wake, scan its network, so the "
            "hub can use that network's broadcast address.",
        )
    if settings.WALL_WOL_WAIT_S > 0:
        wake.status = Wake.Status.WAITING
    else:
        finish(wake, Wake.Status.SENT, "", now)
    wake.save()
    return wake.status == Wake.Status.WAITING


def no_answer_note(device: Device) -> str:
    note = f"No answer to {describe_check(device)} within {duration(settings.WALL_WOL_WAIT_S)}."
    if not device.check_port:
        note += (
            " Windows blocks ping by default: set a TCP port such as 445 under Monitoring, "
            "then wake it again to check."
        )
    return (
        note + " If it is still off, check that Wake-on-LAN is on in its firmware and network card."
    )


def record_check(wake: Wake, document: dict[str, Any], now: datetime) -> bool:
    """Store one wall-healthcheck check of a woken device. Returns True if the wake is over."""
    wake.checks += 1
    deadline = wake.sent_at + timedelta(seconds=settings.WALL_WOL_WAIT_S)
    result = document["result"]
    # The check of this device; the address is compared in case the tool broke its promises.
    check = next(
        (check for check in (result or {}).get("checks", []) if check["ip"] == wake.device.ip),
        None,
    )
    if now > deadline + LATE_CHECK:
        finish(
            wake, Wake.Status.SENT, "Not checked: the check ran too late (worker restarted?).", now
        )
    elif check is None:
        reasons = "; ".join(error["message"] for error in document["errors"]) or "no result"
        finish(wake, Wake.Status.SENT, f"Not checked: {reasons}", now)
    elif check["up"]:
        wake.message = ""  # whatever the send noted no longer matters
        finish(wake, Wake.Status.AWAKE, "", now)
    elif now >= deadline:
        finish(wake, Wake.Status.NO_ANSWER, no_answer_note(wake.device), now)
    wake.save()
    return wake.is_finished
