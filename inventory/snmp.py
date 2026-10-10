"""Storing a wall-snmpinfo document on its device, and low-supply alerts.

A supply is reported once when its percentage drops below
WALL_TONER_ALERT_PERCENT, and not again until it has been replaced: a reading at
or above the threshold re-arms it. The device's low_supplies field remembers
which supplies have been reported.

For waste containers (types waste_*), Printer-MIB reports the space left, so a
low percentage means "nearly full".
"""

from datetime import datetime
from typing import Any

from django.conf import settings

from inventory.models import Alert, Device


def describe_low_supply(device: Device, supply: dict[str, Any]) -> str:
    name = supply["description"] or supply["type"].replace("_", " ")
    if supply["type"].startswith("waste_"):
        state = f"nearly full ({supply['percent']}% space left)"
    else:
        state = f"low ({supply['percent']}% left)"
    return f"{device} ({device.ip}): {name} is {state}."


def check_supplies(device: Device, supplies: list[dict[str, Any]]) -> list[Alert]:
    """Alerts for supplies that have just dropped below the threshold (not saved yet)."""
    threshold = settings.WALL_TONER_ALERT_PERCENT
    reported = set(device.low_supplies)
    alerts = []
    for supply in supplies:
        percent = supply["percent"]
        if percent is None:  # level not measurable: neither low nor replaced
            continue
        if percent < threshold and supply["index"] not in reported:
            reported.add(supply["index"])
            alerts.append(
                Alert(
                    device=device,
                    kind=Alert.Kind.SUPPLY,
                    message=describe_low_supply(device, supply),
                )
            )
        elif percent >= threshold:
            reported.discard(supply["index"])  # replaced: report it again next time
    present = {supply["index"] for supply in supplies}
    device.low_supplies = sorted(reported & present)
    return alerts


def apply_snmp(device: Device, document: dict[str, Any], now: datetime) -> list[Alert]:
    """Store a validated wall-snmpinfo document on its device. Returns new supply alerts.

    A failed read keeps the last good result, so the device page still shows what
    was known; snmp_status and snmp_message say what happened this time. Asset
    fields that are empty are filled from SNMP, but never overwritten.
    """
    device.snmp_read_at = now
    device.snmp_status = document["status"]
    device.snmp_message = "; ".join(error["message"] for error in document["errors"])
    alerts = []
    result = document["result"]
    if result is not None:
        device.snmp_info = result
        if not device.model_name and result["model"]:
            device.model_name = result["model"][:100]
        if not device.serial_number and result["serial_number"]:
            device.serial_number = result["serial_number"][:100]
        if result["supplies"] is not None:
            alerts = check_supplies(device, result["supplies"])
    device.save()
    for alert in alerts:
        alert.save()
    return alerts
