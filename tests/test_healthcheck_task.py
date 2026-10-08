"""The run_healthchecks task, with wall-healthcheck replaced by fake output."""

from datetime import timedelta

import pytest
from django.utils import timezone
from helpers import check

from inventory.models import Alert, Device, HealthRun
from inventory.tasks import healthcheck_time_limit, run_healthchecks

pytestmark = pytest.mark.django_db


def test_nothing_to_do_without_monitored_devices(fake_tool, make_device):
    make_device("192.168.1.1")

    assert run_healthchecks() == "no monitored devices"
    assert fake_tool.calls == []
    assert not HealthRun.objects.exists()


def test_run_updates_health_and_sends_alerts(
    fake_tool, make_device, healthcheck_doc, settings, mailoutbox
):
    settings.WALL_ALERT_AFTER_FAILURES = 1
    settings.WALL_ALERT_EMAILS = ["it@example.com"]
    router = make_device("192.168.1.1", monitored=True)
    pc = make_device("192.168.1.20", monitored=True, check_port=445, health="up")
    make_device("192.168.1.30")  # not monitored
    fake_tool(
        stdout=healthcheck_doc(
            check(router.ip), check(pc.ip, port=445, up=False, down_reason="refused")
        )
    )

    assert run_healthchecks() == "ok"

    targets = ["192.168.1.1", "192.168.1.20:445"]
    options = ["--attempts", "3", "--timeout-ms", "1000"]
    assert fake_tool.calls == [["wall-healthcheck", *targets, *options]]
    run = HealthRun.objects.get()
    assert (run.status, run.check_count) == ("ok", 2)
    assert run.finished_at is not None
    router.refresh_from_db()
    pc.refresh_from_db()
    assert (router.health, pc.health) == ("up", "down")
    assert Alert.objects.get().device == pc
    assert len(mailoutbox) == 1


def test_tool_failure_leaves_devices_alone(fake_tool, make_device):
    device = make_device("192.168.1.1", monitored=True, health="up")
    fake_tool(stdout="", returncode=1, stderr="Traceback (most recent call last):")

    assert run_healthchecks() == "failed"

    run = HealthRun.objects.get()
    assert "exited with code 1" in run.message
    assert run.stderr.startswith("Traceback")
    device.refresh_from_db()
    assert (device.health, device.consecutive_failures) == ("up", 0)


def test_tool_reporting_an_error(fake_tool, make_device, example):
    device = make_device("192.168.1.1", monitored=True)
    fake_tool(stdout=example("wall-healthcheck", "error.json"), returncode=1)

    assert run_healthchecks() == "error"

    assert "may not open ICMP sockets" in HealthRun.objects.get().message
    device.refresh_from_db()
    assert device.last_check_at is None


def test_results_for_other_devices_fail_the_run(fake_tool, make_device, healthcheck_doc):
    device = make_device("192.168.1.1", monitored=True)
    fake_tool(stdout=healthcheck_doc(check("192.168.1.99")))

    assert run_healthchecks() == "failed"

    assert "does not match" in HealthRun.objects.get().message
    device.refresh_from_db()
    assert device.health == "unknown"


def test_no_overlap_with_a_run_in_progress(fake_tool, make_device):
    make_device("192.168.1.1", monitored=True)
    HealthRun.objects.create()  # status "running"

    assert run_healthchecks() == "previous run still in progress"
    assert fake_tool.calls == []


def test_a_run_that_never_finished_is_closed(fake_tool, make_device, healthcheck_doc):
    device = make_device("192.168.1.1", monitored=True)
    stale = HealthRun.objects.create()
    HealthRun.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=1))
    fake_tool(stdout=healthcheck_doc(check(device.ip)))

    assert run_healthchecks() == "ok"

    stale.refresh_from_db()
    assert stale.status == "failed"
    assert stale.message.startswith("Never finished")


def test_old_runs_are_deleted(fake_tool, make_device, healthcheck_doc):
    device = make_device("192.168.1.1", monitored=True)
    old = HealthRun.objects.create(status="ok")
    HealthRun.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
    fake_tool(stdout=healthcheck_doc(check(device.ip)))

    run_healthchecks()

    assert not HealthRun.objects.filter(pk=old.pk).exists()
    assert HealthRun.objects.count() == 1


def test_time_limit_covers_the_worst_case():
    # 3 attempts of 1 s + 0.2 s pause, rounded up, plus 30 s margin.
    assert healthcheck_time_limit(1) == 34
    # wall-healthcheck checks 100 targets at a time: 250 devices take 3 rounds.
    assert healthcheck_time_limit(250) == 41


def test_devices_are_checked_in_a_stable_order(fake_tool, make_device, healthcheck_doc):
    second = make_device("192.168.1.2", monitored=True)
    first = Device.objects.create(
        ip="192.168.1.9", first_seen=second.first_seen, last_seen=second.last_seen, monitored=True
    )
    fake_tool(stdout=healthcheck_doc(check(second.ip), check(first.ip)))

    assert run_healthchecks() == "ok"
    assert fake_tool.calls[0][1:3] == ["192.168.1.2", "192.168.1.9"]
