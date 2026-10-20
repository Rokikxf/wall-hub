"""The run_scan task, with wall-scan replaced by fake output."""

from datetime import timedelta

import pytest
from django.utils import timezone

from inventory.models import Device, Scan
from inventory.tasks import prune_scans, run_scan

pytestmark = pytest.mark.django_db


def test_successful_scan(fake_tool, example, settings):
    settings.WALL_SCAN_PRIVILEGED = True
    fake_tool(stdout=example("wall-scan", "ok.json"))
    scan = Scan.objects.create(targets="192.168.1.0/24")

    assert run_scan(scan.pk) == "ok"

    scan.refresh_from_db()
    assert scan.status == "ok"
    assert scan.started_at <= scan.finished_at
    assert scan.device_count == 5
    assert Device.objects.count() == 5
    assert fake_tool.calls == [
        ["wall-scan", "192.168.1.0/24", "--timeout-s", "600", "--privileged"]
    ]


def test_several_targets_unprivileged(fake_tool, example, settings):
    settings.WALL_SCAN_PRIVILEGED = False
    settings.WALL_SCAN_COMMAND = "/opt/wall/bin/wall-scan"
    fake_tool(stdout=example("wall-scan", "discovery-only.json"))
    scan = Scan.objects.create(targets="10.0.0.1 10.0.1.0/24")

    run_scan(scan.pk)

    assert fake_tool.calls == [
        ["/opt/wall/bin/wall-scan", "10.0.0.1", "10.0.1.0/24", "--timeout-s", "600"]
    ]


def test_scan_that_wall_scan_reports_as_failed(fake_tool, example):
    fake_tool(stdout=example("wall-scan", "error.json"), returncode=1)
    scan = Scan.objects.create(targets="192.168.1.0/24")

    assert run_scan(scan.pk) == "error"

    scan.refresh_from_db()
    assert scan.message == "nmap executable not found: nmap"


def test_scan_without_a_valid_document(fake_tool):
    fake_tool(stdout="", returncode=1, stderr="Traceback (most recent call last):\n  ...\n")
    scan = Scan.objects.create(targets="192.168.1.0/24")

    assert run_scan(scan.pk) == "failed"

    scan.refresh_from_db()
    assert "exited with code 1" in scan.message
    assert scan.stderr.startswith("Traceback")
    assert scan.finished_at is not None


# --- scan history ---


def old_scan(days, status="ok"):
    scan = Scan.objects.create(targets="192.168.1.0/24", status=status)
    Scan.objects.filter(pk=scan.pk).update(created_at=timezone.now() - timedelta(days=days))
    return scan


def test_old_scans_are_deleted_but_a_devices_last_scan_is_kept(make_device, settings):
    settings.WALL_SCAN_RETENTION_DAYS = 90
    gone, still_linked, recent = old_scan(100), old_scan(200), old_scan(10)
    unfinished = old_scan(100, status="queued")  # a worker may still pick it up
    make_device("192.168.1.9", last_scan=still_linked)
    make_device("192.168.1.8")  # no last scan: its NULL must not hide every scan

    assert prune_scans(timezone.now()) == 1

    assert set(Scan.objects.values_list("pk", flat=True)) == {
        still_linked.pk,
        recent.pk,
        unfinished.pk,
    }
    assert gone.pk not in Scan.objects.values_list("pk", flat=True)


def test_scan_history_kept_forever_with_zero(settings):
    settings.WALL_SCAN_RETENTION_DAYS = 0
    old_scan(1000)

    assert prune_scans(timezone.now()) == 0
    assert Scan.objects.count() == 1


def test_every_scan_prunes_the_history(fake_tool, example, settings):
    settings.WALL_SCAN_RETENTION_DAYS = 90
    old_scan(100)
    fake_tool(raises=FileNotFoundError())  # also when the scan itself fails
    scan = Scan.objects.create(targets="192.168.1.0/24")

    run_scan(scan.pk)

    assert list(Scan.objects.values_list("pk", flat=True)) == [scan.pk]


def test_scan_list_leaves_the_output_in_the_database(fake_tool, example, django_assert_num_queries):
    fake_tool(stdout=example("wall-scan", "ok.json"))
    scan = Scan.objects.create(targets="192.168.1.0/24")
    run_scan(scan.pk)

    listed = Scan.objects.for_list().get(pk=scan.pk)

    assert {"output", "stderr"} <= listed.get_deferred_fields()
    with django_assert_num_queries(0):
        assert listed.scanned_networks == ["192.168.1.0/24"]
