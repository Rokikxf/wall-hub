"""manage.py scan, and the startup checks in inventory/checks.py."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from jsonschema import Draft202012Validator

from inventory.checks import contracts_are_valid_schemas, date_time_values_are_checked
from inventory.models import Scan
from inventory.tasks import run_scan

# --- manage.py scan ---


@pytest.fixture
def worker(monkeypatch):
    """Run queued scans immediately in this process instead of in a Celery worker."""
    monkeypatch.setattr("inventory.views.run_scan.delay", run_scan)


@pytest.mark.django_db
def test_scan_command_waits_for_the_result(worker, fake_tool, example):
    fake_tool(stdout=example("wall-scan", "ok.json"))
    out = StringIO()

    call_command("scan", "192.168.1.0/24", "--wait", stdout=out)

    assert "finished: ok, 5 device(s)" in out.getvalue()


@pytest.mark.django_db
def test_scan_command_fails_when_the_scan_fails(worker, fake_tool):
    fake_tool(raises=FileNotFoundError())

    with pytest.raises(CommandError, match="failed"):
        call_command("scan", "192.168.1.0/24", "--wait", stdout=StringIO())


@pytest.mark.django_db
def test_scan_command_without_wait_only_queues(monkeypatch):
    queued = []
    monkeypatch.setattr("inventory.views.run_scan.delay", queued.append)

    call_command("scan", "10.0.0.0/24", stdout=StringIO())

    assert queued == [Scan.objects.get().pk]


@pytest.mark.django_db
def test_scan_command_rejects_public_targets():
    with pytest.raises(CommandError, match="not a private address range"):
        call_command("scan", "8.8.8.8")
    assert not Scan.objects.exists()


# --- startup checks ---


def test_all_checks_pass():
    call_command("check")


def test_missing_rfc3339_validator_is_an_error(monkeypatch):
    monkeypatch.delitem(Draft202012Validator.FORMAT_CHECKER.checkers, "date-time")

    assert [e.id for e in date_time_values_are_checked(None)] == ["inventory.E001"]


def test_broken_or_missing_contracts_are_errors(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    assert [e.id for e in contracts_are_valid_schemas(None)] == ["inventory.E002"]

    (tmp_path / "contracts" / "wall-broken").mkdir(parents=True)
    (tmp_path / "contracts" / "wall-broken" / "v1.json").write_text('{"type": 5}')
    assert [e.id for e in contracts_are_valid_schemas(None)] == ["inventory.E003"]
