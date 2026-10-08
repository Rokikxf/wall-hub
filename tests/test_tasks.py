"""The run_scan task, with wall-scan replaced by fake output."""

import pytest

from inventory.models import Device, Scan
from inventory.tasks import run_scan

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
