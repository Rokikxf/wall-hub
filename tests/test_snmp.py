"""SNMP details with wall-snmpinfo: which devices are read, what is stored, supply alerts."""

import copy
from datetime import UTC, datetime

import pytest
from django.template import Context, Template
from django.urls import reverse
from kombu.exceptions import OperationalError

from inventory.models import Alert, Device
from inventory.snmp import apply_snmp
from inventory.tasks import read_all_snmp, read_snmp, snmpinfo_command

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def printer_doc(example):
    return lambda: copy.deepcopy(example("wall-snmpinfo", "printer.json"))


def with_percent(document, index, percent):
    """The printer document with supply `index` measured at `percent`."""
    for supply in document["result"]["supplies"]:
        if supply["index"] == index:
            supply.update(level_state="measured", level=percent, max_capacity=100, percent=percent)
    return document


# --- which devices are read ---


@pytest.mark.parametrize(
    "fields, reads",
    [
        ({}, False),
        ({"kind": "printer"}, True),
        ({"kind": "network"}, True),
        ({"kind": "computer"}, False),
        ({"open_ports": [{"port": 9100, "protocol": "tcp", "service": "jetdirect"}]}, True),
        ({"open_ports": [{"port": 631, "protocol": "tcp", "service": "ipp"}]}, True),
        ({"open_ports": [{"port": 22, "protocol": "tcp", "service": "ssh"}]}, False),
        ({"kind": "printer", "snmp_enabled": False}, False),  # explicit setting wins
        ({"kind": "computer", "snmp_enabled": True}, True),
    ],
    ids=["unknown", "printer", "network", "computer", "jetdirect-port", "ipp-port",
         "ssh-port", "printer-switched-off", "computer-switched-on"],
)  # fmt: skip
def test_which_devices_are_read(make_device, fields, reads):
    assert make_device("192.168.1.50", **fields).reads_snmp is reads


def test_command_has_no_community_string(make_device, settings):
    settings.WALL_SNMP_TIMEOUT_MS = 1500
    device = make_device("192.168.1.50")

    command = snmpinfo_command(device)

    assert command == [
        "wall-snmpinfo", "192.168.1.50", "--snmp-version", "2c", "--timeout-ms", "1500",
        "--retries", "1",
    ]  # fmt: skip
    assert not any("public" in part or "community" in part for part in command)


# --- storing a read ---


def test_read_is_stored_and_fills_empty_asset_fields(make_device, printer_doc):
    device = make_device("192.168.1.50", serial_number="ENTERED-BY-HAND")

    apply_snmp(device, printer_doc(), T0)

    device.refresh_from_db()
    assert (device.snmp_status, device.snmp_read_at, device.snmp_message) == ("ok", T0, "")
    assert device.snmp_info["model"] == "HP Color LaserJet Pro M454dw"
    assert device.model_name == "HP Color LaserJet Pro M454dw"  # was empty: filled
    assert device.serial_number == "ENTERED-BY-HAND"  # never overwritten


def test_failed_read_keeps_the_last_good_result(make_device, printer_doc, example):
    device = make_device("192.168.1.50")
    apply_snmp(device, printer_doc(), T0)

    apply_snmp(device, example("wall-snmpinfo", "timeout.json"), T0)

    device.refresh_from_db()
    assert device.snmp_status == "error"
    assert device.snmp_message.startswith("No SNMP response")
    assert device.snmp_info["serial_number"] == "VNB3K12345"


# --- low supplies ---


def test_a_low_supply_is_reported_once_until_refilled(make_device, printer_doc, settings):
    settings.WALL_TONER_ALERT_PERCENT = 10
    device = make_device("192.168.1.50", name="Reception printer")

    assert apply_snmp(device, printer_doc(), T0) == []  # cyan is 12%: fine

    [alert] = apply_snmp(device, with_percent(printer_doc(), 2, 8), T0)
    assert alert.kind == Alert.Kind.SUPPLY
    assert (
        alert.message
        == "Reception printer (192.168.1.50): Cyan Cartridge HP 415A is low (8% left)."
    )
    assert apply_snmp(device, with_percent(printer_doc(), 2, 5), T0) == []  # still low: quiet

    apply_snmp(device, with_percent(printer_doc(), 2, 100), T0)  # replaced
    assert len(apply_snmp(device, with_percent(printer_doc(), 2, 9), T0)) == 1  # low again
    assert Alert.objects.filter(kind="supply").count() == 2


def test_waste_container_running_out_of_space_is_nearly_full(make_device, printer_doc):
    device = make_device("192.168.1.50")

    [alert] = apply_snmp(device, with_percent(printer_doc(), 5, 4), T0)

    assert "Toner Collection Unit is nearly full (4% space left)." in alert.message


def test_unmeasurable_levels_are_neither_low_nor_refilled(make_device, printer_doc):
    device = make_device("192.168.1.50")
    apply_snmp(device, with_percent(printer_doc(), 3, 2), T0)  # magenta low: reported
    assert device.low_supplies == [3]

    apply_snmp(device, printer_doc(), T0)  # magenta back to "some remaining"

    assert device.low_supplies == [3]  # not counted as a refill


def test_partial_read_without_supplies_keeps_the_low_list(make_device, printer_doc, example):
    device = make_device("192.168.1.51")
    apply_snmp(device, with_percent(printer_doc(), 1, 3), T0)

    assert apply_snmp(device, example("wall-snmpinfo", "partial.json"), T0) == []

    device.refresh_from_db()
    assert device.low_supplies == [1]
    assert device.snmp_status == "partial"


# --- the tasks ---


def test_read_snmp_task_emails_low_supplies(
    fake_tool, make_device, printer_doc, settings, mailoutbox
):
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    device = make_device("192.168.1.50", name="Reception printer")
    fake_tool(stdout=with_percent(with_percent(printer_doc(), 1, 3), 2, 7))

    assert read_snmp(device.pk) == "ok"

    [email] = mailoutbox
    assert email.subject == "[wall] 2 supplies low: Reception printer (192.168.1.50)"
    assert "Black Cartridge HP 415A is low (3% left)." in email.body
    assert set(Alert.objects.values_list("emailed_to", flat=True)) == {"it@example.com"}


def test_read_snmp_without_a_valid_document(fake_tool, make_device):
    device = make_device("192.168.1.50")
    fake_tool(raises=FileNotFoundError())

    assert read_snmp(device.pk) == "failed"

    device.refresh_from_db()
    assert device.snmp_message == "wall-snmpinfo is not installed"


def test_read_all_reads_only_the_devices_that_qualify(fake_tool, make_device, printer_doc):
    make_device("192.168.1.50", kind="printer")
    make_device("192.168.1.1", kind="network")
    make_device("192.168.1.20", kind="computer")
    fake_tool(stdout=printer_doc())

    assert read_all_snmp() == 2
    assert [call[1] for call in fake_tool.calls] == ["192.168.1.50", "192.168.1.1"]


def test_schedule(settings):
    from django.conf import settings as live

    entry = live.CELERY_BEAT_SCHEDULE["snmp-reads"]
    assert entry["task"] == "inventory.tasks.read_all_snmp"
    assert entry["schedule"] == live.WALL_SNMP_INTERVAL_H * 3600


# --- the device page ---


def test_device_page_shows_snmp_details(logged_in, make_device, printer_doc):
    device = make_device("192.168.1.50", kind="printer")
    apply_snmp(device, with_percent(printer_doc(), 2, 7), T0)

    content = logged_in.get(reverse("device-detail", args=[device.pk])).content.decode()

    assert "VNB3K12345" in content
    assert "10 days, 23 minutes" in content  # uptime 865432 s
    assert '<strong class="text-danger">7%</strong>' in content
    assert "some left" in content
    assert "Automatic (on for this device)" in content


@pytest.mark.parametrize("setting, value", [("on", True), ("off", False), ("auto", None)])
def test_snmp_setting(logged_in, make_device, setting, value):
    device = make_device("192.168.1.50", snmp_enabled=not value if value is not None else True)

    logged_in.post(reverse("device-detail", args=[device.pk]), {"snmp_setting": setting})

    device.refresh_from_db()
    assert device.snmp_enabled is value


def test_read_now(logged_in, make_device, monkeypatch):
    queued = []
    monkeypatch.setattr("inventory.views.read_snmp.delay", queued.append)
    device = make_device("192.168.1.50")

    response = logged_in.post(reverse("device-detail", args=[device.pk]), {"read_snmp": "1"})

    assert response.status_code == 302
    assert queued == [device.pk]


def test_read_now_with_redis_down(logged_in, make_device, monkeypatch):
    def down(pk):
        raise OperationalError("connection refused")

    monkeypatch.setattr("inventory.views.read_snmp.delay", down)
    device = make_device("192.168.1.50")

    response = logged_in.post(
        reverse("device-detail", args=[device.pk]), {"read_snmp": "1"}, follow=True
    )

    assert "is Redis running?" in response.content.decode()


def test_supply_alerts_are_listed(logged_in, make_device):
    device = make_device("192.168.1.50")
    Alert.objects.create(device=device, kind="supply", message="Cyan is low (8% left).")

    assert "Supply low" in logged_in.get(reverse("alert-list")).content.decode()


@pytest.mark.parametrize(
    "seconds, text",
    [(None, "—"), (0, "0 seconds"), (59, "59 seconds"), (3600, "1 hour"),
     (90061, "1 day, 1 hour"), (865432, "10 days, 23 minutes")],
)  # fmt: skip
def test_duration_filter(seconds, text):
    html = Template("{% load inventory_tags %}{{ s|duration }}").render(Context({"s": seconds}))
    assert html == text


def test_unread_device_page(logged_in, make_device):
    device = make_device("192.168.1.20", kind="computer")
    content = logged_in.get(reverse("device-detail", args=[device.pk])).content.decode()
    assert "Not read yet." in content
    assert "Automatic (off for this device)" in content
    assert Device.objects.get().snmp_info is None
