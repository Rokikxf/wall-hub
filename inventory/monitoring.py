"""Turning wall-healthcheck results into device health, and health changes into alerts.

A device is not declared down on its first failed check: a single lost ping on a
busy network would cause a false alarm. It goes down after
WALL_ALERT_AFTER_FAILURES consecutive failures (2 by default, so about two
minutes with a 60-second interval). One success brings it back up. Each change
to down or back to up creates exactly one Alert.
"""

from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.timesince import timesince

from inventory.models import Alert, Device


class MonitoringError(Exception):
    """The checks in a valid wall-healthcheck document do not match the devices sent."""


def describe_check(device: Device) -> str:
    return f"TCP port {device.check_port}" if device.check_port else "ping"


def update_health(device: Device, check: dict[str, Any], now: datetime) -> Alert | None:
    """Apply one entry of result.checks to its device. Returns the alert to send, if any."""
    device.last_check_at = now
    alert = None
    if check["up"]:
        if device.health == Device.Health.DOWN:
            outage = timesince(device.down_since, now) if device.down_since else "an outage"
            alert = Alert(
                device=device,
                kind=Alert.Kind.UP,
                message=(
                    f"{device} ({device.ip}) is back up after {outage} "
                    f"({describe_check(device)}, {check['rtt_ms']} ms)."
                ),
            )
        device.health = Device.Health.UP
        device.consecutive_failures = 0
        device.down_since = None
        device.last_rtt_ms = check["rtt_ms"]
        device.last_down_reason = ""
    else:
        device.consecutive_failures += 1
        device.down_since = device.down_since or now
        device.last_rtt_ms = None
        device.last_down_reason = check["down_reason"]
        threshold = settings.WALL_ALERT_AFTER_FAILURES
        if device.health != Device.Health.DOWN and device.consecutive_failures >= threshold:
            device.health = Device.Health.DOWN
            since = timezone.localtime(device.down_since).strftime("%H:%M")
            alert = Alert(
                device=device,
                kind=Alert.Kind.DOWN,
                message=(
                    f"{device} ({device.ip}) is down: no answer to {describe_check(device)} "
                    f"since {since} ({device.consecutive_failures} failed checks, "
                    f"last reason: {check['down_reason']})."
                ),
            )
    device.save()
    if alert is not None:
        alert.save()
    return alert


def apply_checks(devices: list[Device], document: dict[str, Any], now: datetime) -> list[Alert]:
    """Update every device from the check made for it. Returns the new alerts.

    wall-healthcheck reports checks in the order of its targets, which were built
    from `devices` in this order. The IP addresses are compared as well, so a
    tool that broke that promise could never update the wrong device.
    """
    checks = document["result"]["checks"]
    if len(checks) != len(devices):
        raise MonitoringError(f"{len(devices)} devices checked, but {len(checks)} results")
    for device, check in zip(devices, checks, strict=True):
        if check["ip"] != device.ip or check["port"] != device.check_port:
            raise MonitoringError(f"result for {check['ip']} does not match {device.check_target}")
    alerts = [
        update_health(device, check, now) for device, check in zip(devices, checks, strict=True)
    ]
    return [alert for alert in alerts if alert is not None]
