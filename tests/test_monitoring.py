"""Device health from check results: when a device counts as down, and the alerts."""

from datetime import UTC, datetime, timedelta

import pytest
from helpers import check

from inventory.models import Alert, Device
from inventory.monitoring import MonitoringError, apply_checks, update_health

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_first_success_means_up_without_an_alert(make_device):
    device = make_device("192.168.1.50", monitored=True)

    assert update_health(device, check(device.ip, rtt_ms=1.42), T0) is None

    device.refresh_from_db()
    assert device.health == "up"
    assert device.last_rtt_ms == 1.42
    assert device.last_check_at == T0


def test_down_after_the_threshold_with_exactly_one_alert(make_device, settings):
    settings.WALL_ALERT_AFTER_FAILURES = 2
    device = make_device("192.168.1.50", hostname="printer.lan", monitored=True, health="up")

    assert update_health(device, check(device.ip, up=False), at(0)) is None
    assert device.health == "up"  # one lost check is not an outage yet
    assert device.down_since == at(0)

    alert = update_health(device, check(device.ip, up=False), at(1))
    assert alert.kind == Alert.Kind.DOWN
    assert alert.message == (
        "printer.lan (192.168.1.50) is down: no answer to ping since 09:30 "
        "(2 failed checks, last reason: timeout)."
    )

    assert update_health(device, check(device.ip, up=False), at(2)) is None  # no repeats
    device.refresh_from_db()
    assert (device.health, device.consecutive_failures, device.down_since) == ("down", 3, at(0))
    assert Alert.objects.count() == 1


def test_recovery_alert(make_device):
    device = make_device(
        "192.168.1.20",
        hostname="office-pc01.lan",
        check_port=445,
        monitored=True,
        health="down",
        consecutive_failures=5,
        down_since=at(0),
    )

    alert = update_health(device, check(device.ip, port=445, rtt_ms=0.88), at(12))

    assert alert.kind == Alert.Kind.UP
    assert alert.message == (
        "office-pc01.lan (192.168.1.20) is back up after 12\xa0minutes (TCP port 445, 0.88 ms)."
    )
    device.refresh_from_db()
    assert (device.health, device.consecutive_failures, device.down_since) == ("up", 0, None)


def test_a_single_lost_check_is_not_an_outage(make_device):
    device = make_device("192.168.1.50", monitored=True, health="up")

    update_health(device, check(device.ip, up=False), at(0))
    update_health(device, check(device.ip), at(1))

    assert not Alert.objects.exists()
    assert device.down_since is None


def test_threshold_of_one_alerts_on_the_first_failure(make_device, settings):
    settings.WALL_ALERT_AFTER_FAILURES = 1
    device = make_device("192.168.1.50", monitored=True)

    alert = update_health(device, check(device.ip, up=False, down_reason="host_unreachable"), T0)

    assert alert.kind == Alert.Kind.DOWN
    assert "last reason: host_unreachable" in alert.message


def test_apply_checks_updates_devices_in_order(make_device, healthcheck_doc):
    router = make_device("192.168.1.1", monitored=True)
    pc = make_device("192.168.1.20", monitored=True, check_port=445)
    document = healthcheck_doc(check(router.ip), check(pc.ip, port=445, up=False))

    assert apply_checks([router, pc], document, T0) == []

    router.refresh_from_db()
    pc.refresh_from_db()
    assert router.health == "up"
    assert (pc.health, pc.consecutive_failures) == ("unknown", 1)


@pytest.mark.parametrize(
    "checks",
    [
        [check("192.168.1.1")],
        [check("192.168.1.1"), check("192.168.1.99")],
        [check("192.168.1.1"), check("192.168.1.20")],  # ping, but port 445 was asked
    ],
    ids=["missing-result", "other-ip", "other-method"],
)
def test_results_that_do_not_match_the_devices_are_rejected(make_device, healthcheck_doc, checks):
    devices = [
        make_device("192.168.1.1", monitored=True),
        make_device("192.168.1.20", monitored=True, check_port=445),
    ]

    with pytest.raises(MonitoringError):
        apply_checks(devices, healthcheck_doc(*checks), T0)

    assert set(Device.objects.values_list("health", flat=True)) == {"unknown"}
