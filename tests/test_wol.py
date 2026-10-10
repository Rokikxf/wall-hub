"""Wake-on-LAN with wall-wol: where the packets go, the follow-up checks, the device page."""

from datetime import timedelta
from ipaddress import IPv4Network

import pytest
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError

from inventory import wol
from inventory.models import Scan, Wake
from inventory.tasks import check_wake, wake_device, wol_command

pytestmark = pytest.mark.django_db

MAC = "3c:52:82:4a:1f:07"
IP = "10.180.103.231"


def scan_of(*targets: str) -> Scan:
    """A finished scan of these targets, as wall-scan reports them in params.targets."""
    return Scan.objects.create(
        targets=" ".join(targets), status="ok", output={"params": {"targets": list(targets)}}
    )


def check(up: bool, port: int | None = None) -> dict:
    """One wall-healthcheck check of IP."""
    return {
        "ip": IP,
        "method": "tcp" if port else "icmp",
        "port": port,
        "up": up,
        "successes": 3 if up else 0,
        "rtt_ms": 1.2 if up else None,
        "down_reason": None if up else "timeout",
    }


@pytest.fixture
def scheduled(monkeypatch):
    """The follow-up checks queued with check_wake.apply_async, as (wake id, countdown)."""
    calls = []

    def apply_async(args, countdown):
        calls.append((args[0], countdown))

    monkeypatch.setattr("inventory.tasks.check_wake.apply_async", apply_async)
    return calls


@pytest.fixture
def wake_of(make_device):
    """A Wake of a new device at IP: wake_of(status="waiting", device={"check_port": 445})."""

    def make(device=None, **fields) -> Wake:
        target = make_device(IP, mac=MAC, **(device or {}))
        return Wake.objects.create(device=target, mac=MAC, **fields)

    return make


@pytest.fixture
def waiting(wake_of):
    """A wake whose packets went out `seconds_ago`."""

    def make(seconds_ago: int, **device) -> Wake:
        sent_at = timezone.now() - timedelta(seconds=seconds_ago)
        return wake_of(status="waiting", broadcast="10.180.103.255", sent_at=sent_at, device=device)

    return make


# --- where the packets go ---


def test_broadcast_of_the_network_the_device_was_found_on(make_device):
    device = make_device(IP, last_scan=scan_of("10.180.103.0/24", "192.168.56.0/24"))

    assert wol.wake_broadcast(device) == ("10.180.103.255", IPv4Network("10.180.103.0/24"))


def test_the_most_specific_network_wins(make_device):
    device = make_device("10.0.5.7", last_scan=scan_of("10.0.0.0/16", "10.0.5.0/24"))

    assert wol.wake_broadcast(device)[0] == "10.0.5.255"


def test_a_scan_of_one_address_falls_back_to_an_earlier_network_scan(make_device):
    scan_of("192.168.1.0/24")
    Scan.objects.create(targets="192.168.1.0/24", status="failed")  # no output: ignored
    device = make_device("192.168.1.50", last_scan=scan_of("192.168.1.50"))

    assert wol.wake_broadcast(device)[0] == "192.168.1.255"


def test_unknown_network_uses_the_setting(make_device, settings):
    settings.WALL_WOL_BROADCAST = "192.168.1.255"
    scan_of("10.0.0.0/24")  # another network
    device = make_device("192.168.1.50", last_scan=scan_of("192.168.1.50/31"))  # no broadcast

    assert wol.wake_broadcast(device) == ("192.168.1.255", None)


def test_command(wake_of):
    wake = wake_of(broadcast="10.180.103.255")

    assert wol_command(wake) == ["wall-wol", MAC, "--broadcast", "10.180.103.255", "--port", "9"]


# --- sending ---


def test_wake_sends_and_schedules_the_first_check(fake_tool, wake_of, example, scheduled):
    wake = wake_of(device={"last_scan": scan_of("10.180.103.0/24")})
    fake_tool(stdout=example("wall-wol", "wake.json"))

    assert wake_device(wake.pk) == "waiting"

    wake.refresh_from_db()
    assert fake_tool.calls == [["wall-wol", MAC, "--broadcast", "10.180.103.255", "--port", "9"]]
    assert (wake.broadcast, wake.source_ip, wake.message) == ("10.180.103.255", "192.168.1.10", "")
    assert wake.sent_at is not None and wake.finished_at is None
    assert scheduled == [(wake.pk, 15)]


def test_wake_without_a_known_network_says_where_the_packets_went(
    fake_tool, wake_of, example, scheduled
):
    wake = wake_of()
    fake_tool(stdout=example("wall-wol", "wake.json"))

    wake_device(wake.pk)

    wake.refresh_from_db()
    assert wake.broadcast == "255.255.255.255"
    assert wake.message.startswith(
        f"No scan has covered the network of {IP}, so the packets went to 255.255.255.255 "
        "and left from 192.168.1.10."
    )


def test_partly_sent_is_still_checked(fake_tool, wake_of, example, scheduled):
    wake = wake_of(device={"last_scan": scan_of("10.180.103.0/24")})
    fake_tool(stdout=example("wall-wol", "partial.json"))

    assert wake_device(wake.pk) == "waiting"

    wake.refresh_from_db()
    assert "No buffer space available" in wake.message
    assert len(scheduled) == 1


def test_nothing_sent(fake_tool, wake_of, example, scheduled):
    wake = wake_of()
    fake_tool(stdout=example("wall-wol", "unreachable.json"), returncode=1)

    assert wake_device(wake.pk) == "error"

    wake.refresh_from_db()
    assert wake.message.startswith("No route to 10.20.0.255")
    assert wake.finished_at is not None and wake.sent_at is None
    assert scheduled == []


def test_wall_wol_missing(fake_tool, wake_of, scheduled):
    wake = wake_of()
    fake_tool(raises=FileNotFoundError())

    assert wake_device(wake.pk) == "failed"

    wake.refresh_from_db()
    assert wake.message == "wall-wol is not installed"
    assert scheduled == []


def test_sending_without_checking(fake_tool, wake_of, example, scheduled, settings):
    settings.WALL_WOL_WAIT_S = 0
    wake = wake_of()
    fake_tool(stdout=example("wall-wol", "wake.json"))

    assert wake_device(wake.pk) == "sent"
    assert scheduled == []


# --- the checks after sending ---


def test_device_answers(fake_tool, healthcheck_doc, waiting, scheduled):
    wake = waiting(seconds_ago=45)
    fake_tool(stdout=healthcheck_doc(check(up=True)))

    assert check_wake(wake.pk) == "awake"

    wake.refresh_from_db()
    assert fake_tool.calls == [["wall-healthcheck", IP, "--attempts", "3", "--timeout-ms", "1000"]]
    assert (wake.checks, wake.answered_after_s, scheduled) == (1, 45, [])


def test_device_with_a_check_port_is_checked_on_that_port(fake_tool, healthcheck_doc, waiting):
    wake = waiting(seconds_ago=15, check_port=445)
    fake_tool(stdout=healthcheck_doc(check(up=True, port=445)))

    assert check_wake(wake.pk) == "awake"
    assert fake_tool.calls[0][1] == f"{IP}:445"


def test_no_answer_yet_checks_again(fake_tool, healthcheck_doc, waiting, scheduled):
    wake = waiting(seconds_ago=30)
    fake_tool(stdout=healthcheck_doc(check(up=False)))

    assert check_wake(wake.pk) == "waiting"

    wake.refresh_from_db()
    assert (wake.checks, scheduled) == (1, [(wake.pk, 15)])


def test_no_answer_in_time(fake_tool, healthcheck_doc, waiting, scheduled):
    wake = waiting(seconds_ago=180)
    fake_tool(stdout=healthcheck_doc(check(up=False)))

    assert check_wake(wake.pk) == "no_answer"

    wake.refresh_from_db()
    assert wake.message.startswith("No answer to ping within 3 minutes. Windows blocks ping")
    assert scheduled == []


def test_no_answer_on_a_tcp_port(fake_tool, healthcheck_doc, waiting):
    wake = waiting(seconds_ago=200, check_port=445)
    fake_tool(stdout=healthcheck_doc(check(up=False, port=445)))

    check_wake(wake.pk)

    wake.refresh_from_db()
    assert wake.message.startswith("No answer to TCP port 445 within 3 minutes. If it is still")


def test_a_check_long_after_the_deadline_proves_nothing(fake_tool, healthcheck_doc, waiting):
    wake = waiting(seconds_ago=3600)
    fake_tool(stdout=healthcheck_doc(check(up=True)))

    assert check_wake(wake.pk) == "sent"

    wake.refresh_from_db()
    assert wake.message == "Not checked: the check ran too late (worker restarted?)."


def test_a_check_that_cannot_run(fake_tool, example, waiting, scheduled):
    wake = waiting(seconds_ago=15)
    document = example("wall-healthcheck", "error.json")
    fake_tool(stdout=document, returncode=1)

    assert check_wake(wake.pk) == "sent"

    wake.refresh_from_db()
    assert wake.message == f"Not checked: {document['errors'][0]['message']}"
    assert scheduled == []


def test_a_finished_wake_is_not_checked_again(fake_tool, wake_of):
    wake = wake_of(status="awake")
    fake_tool(stdout="")

    assert check_wake(wake.pk) == "awake"
    assert fake_tool.calls == []


# --- the device page ---


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr("inventory.views.wake_device.delay", calls.append)
    return calls


def post_wake(client, device):
    url = reverse("device-detail", args=[device.pk])
    return client.post(url, {"wake": "1"}, follow=True).content.decode()


def test_wake_button(logged_in, make_device, queued):
    device = make_device(IP, mac=MAC)

    content = post_wake(logged_in, device)

    [wake] = Wake.objects.all()
    assert queued == [wake.pk]
    assert (wake.device, wake.mac, wake.requested_by) == (device, MAC, logged_in.user)
    assert f"Magic packets for {MAC} queued." in content
    assert 'hx-trigger="every 3s"' in content  # the section follows the wake


def test_no_wake_without_a_mac(logged_in, make_device, queued):
    device = make_device(IP)

    content = post_wake(logged_in, device)

    assert Wake.objects.count() == 0
    assert "it cannot be woken" in content
    assert 'disabled title="No MAC address known"' in content


def test_one_wake_at_a_time(logged_in, waiting, queued):
    wake = waiting(seconds_ago=20)

    content = post_wake(logged_in, wake.device)

    assert Wake.objects.count() == 1
    assert "This device is already being woken." in content


def test_a_lost_wake_does_not_block_a_new_one(logged_in, waiting, queued):
    wake = waiting(seconds_ago=20)
    Wake.objects.update(created_at=timezone.now() - timedelta(hours=1))  # its worker stopped

    post_wake(logged_in, wake.device)

    assert Wake.objects.count() == 2


def test_wake_with_redis_down(logged_in, make_device, monkeypatch):
    def down(pk):
        raise OperationalError("connection refused")

    monkeypatch.setattr("inventory.views.wake_device.delay", down)
    device = make_device(IP, mac=MAC)

    content = post_wake(logged_in, device)

    assert Wake.objects.get().status == "failed"
    assert "Could not queue the wake (is Redis running?)" in content


def test_the_section_stops_polling_when_the_wake_is_over(logged_in, waiting):
    wake = waiting(seconds_ago=45)
    url = reverse("device-wakes", args=[wake.device.pk])

    content = logged_in.get(url).content.decode()
    assert 'hx-trigger="every 3s"' in content
    assert "Waiting for the device" in content

    wake.status, wake.finished_at = "awake", timezone.now()
    wake.save()
    content = logged_in.get(url).content.decode()
    assert "hx-trigger" not in content
    assert "answered 45 seconds after the packets were sent" in content
    assert "10.180.103.255" in content
