"""The network map: networks from the scans, the hub, gateways, and devices in their boxes."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from inventory.models import Device, Scan
from inventory.netmap import elements

pytestmark = pytest.mark.django_db

LAN = {"network": "10.180.103.0/24", "attached": True, "interface": "enp0s9",
       "address": "10.180.103.124", "gateway": "10.180.103.140"}  # fmt: skip
HOST_ONLY = {"network": "192.168.56.0/24", "attached": True, "interface": "enp0s8",
             "address": "192.168.56.10", "gateway": None}  # fmt: skip


def scan_with(networks=None, targets=None, devices=(), status="ok", minutes_ago=0):
    """A stored wall-scan document: schema 1.1 with networks, or 1.0 with only targets."""
    targets = targets or [entry["network"] for entry in networks or []]
    result = {"engine": {"name": "nmap", "version": "7.94"}, "hosts_scanned": 0,
              "devices": list(devices)}  # fmt: skip
    if networks is not None:
        result["networks"] = networks
    return Scan.objects.create(
        targets=" ".join(targets),
        status=status,
        started_at=timezone.now() - timedelta(minutes=minutes_ago),
        output={"params": {"targets": targets}, "result": result if status != "error" else None},
    )


def split(items):
    """(nodes by id, edges by id)."""
    nodes = {e["data"]["id"]: e for e in items if "source" not in e["data"]}
    edges = {e["data"]["id"]: e for e in items if "source" in e["data"]}
    return nodes, edges


def dev(device):
    return f"dev-{device.pk}"


def test_the_lab_vm(make_device):
    scan_with([LAN, HOST_ONLY])
    hub_lan = make_device("10.180.103.124")
    hotspot = make_device("10.180.103.140", hostname="hotspot")
    pc = make_device("10.180.103.231", mac="9a:b4:df:90:4d:dd", name="Reception PC")
    host = make_device("192.168.56.1")
    elsewhere = make_device("10.99.0.5")

    nodes, edges = split(elements())

    # The hub stands for its own addresses: they are not drawn as devices.
    assert dev(hub_lan) not in nodes
    assert {"ip": "10.180.103.124", "url": hub_lan.get_absolute_url()} in nodes["hub"]["data"][
        "addresses"
    ]
    assert edges["link-10.180.103.0/24"]["data"] == {
        "id": "link-10.180.103.0/24", "source": "hub", "target": "net-10.180.103.0/24",
        "label": "enp0s9 10.180.103.124",
    }  # fmt: skip
    assert edges["link-192.168.56.0/24"]["data"]["label"] == "enp0s8 192.168.56.10"
    # Devices sit in their network's box; the router leads to the internet.
    assert nodes[dev(pc)]["data"]["parent"] == "net-10.180.103.0/24"
    assert nodes[dev(pc)]["data"]["label"] == "Reception PC\n10.180.103.231"
    assert nodes[dev(host)]["data"]["parent"] == "net-192.168.56.0/24"
    assert "gateway" in nodes[dev(hotspot)]["classes"]
    assert edges[f"out-{dev(hotspot)}"]["data"]["target"] == "internet"
    assert "internet" in nodes
    # Outside every scanned network.
    assert nodes[dev(elsewhere)]["data"]["parent"] == "other"
    assert nodes["other"]["data"]["label"] == "Not in a scanned network"


def test_device_classes(make_device):
    scan_with([LAN])
    up = make_device("10.180.103.20", kind="printer", monitored=True, health="up")
    plain = make_device("10.180.103.21")

    nodes, _ = split(elements())

    assert nodes[dev(up)]["classes"] == "kind-printer health-up"
    assert nodes[dev(plain)]["classes"] == "kind-unknown unmonitored"
    assert nodes[dev(plain)]["data"]["health"] == "not monitored"


def test_devices_the_newest_scan_did_not_see_are_stale(make_device):
    gone = make_device("10.180.103.30")
    Device.objects.filter(pk=gone.pk).update(last_seen=timezone.now() - timedelta(hours=2))
    scan_with([LAN], minutes_ago=60)
    here = make_device("10.180.103.31")  # seen just now

    nodes, _ = split(elements())

    assert "stale" in nodes[dev(gone)]["classes"]
    assert nodes[dev(gone)]["data"]["seenInLastScan"] is False
    assert "stale" not in nodes[dev(here)]["classes"]


def test_a_failed_scan_does_not_make_devices_look_gone(make_device):
    scan_with([LAN], minutes_ago=60)
    device = make_device("10.180.103.30")
    Device.objects.filter(pk=device.pk).update(last_seen=timezone.now() - timedelta(minutes=30))
    scan_with(targets=["10.180.103.0/24"], status="error")  # newer, but found nothing

    nodes, _ = split(elements())

    assert "stale" not in nodes[dev(device)]["classes"]


def test_the_newest_scan_wins(make_device):
    scan_with([{**LAN, "gateway": "10.180.103.1"}], minutes_ago=90)
    scan_with([LAN])
    hotspot = make_device("10.180.103.140")

    nodes, edges = split(elements())

    assert "gateway" in nodes[dev(hotspot)]["classes"]
    assert set(edges) == {"link-10.180.103.0/24", f"out-{dev(hotspot)}"}


def test_a_1_0_scan(make_device):
    devices = [{"ip": "192.168.1.10", "discovery_reason": "localhost-response"},
               {"ip": "192.168.1.20", "discovery_reason": "arp-response"}]  # fmt: skip
    scan_with(targets=["192.168.1.0/24", "192.168.1.77"], devices=devices)
    hub = make_device("192.168.1.10")
    pc = make_device("192.168.1.20")

    nodes, edges = split(elements())

    assert nodes["net-192.168.1.0/24"]["data"]["label"] == "192.168.1.0/24"
    assert dev(hub) not in nodes  # recognised from nmap's localhost-response
    assert edges["link-192.168.1.0/24"]["data"]["label"] == "192.168.1.10"
    assert nodes[dev(pc)]["data"]["parent"] == "net-192.168.1.0/24"
    assert "internet" not in nodes  # no gateway known


def test_a_network_behind_a_router(make_device):
    remote = {"network": "10.20.0.0/24", "attached": False, "interface": "enp0s9",
              "address": None, "gateway": "10.180.103.140"}  # fmt: skip
    scan_with([LAN, remote])
    router = make_device("10.180.103.140")

    nodes, edges = split(elements())

    assert nodes["net-10.20.0.0/24"]["data"]["label"] == "10.20.0.0/24 (through a router)"
    assert "link-10.20.0.0/24" not in edges  # the hub is not on it
    assert edges["route-10.20.0.0/24"]["data"] == {
        "id": "route-10.20.0.0/24", "source": dev(router), "target": "net-10.20.0.0/24",
        "label": "route",
    }  # fmt: skip


def test_a_gateway_no_scan_found(make_device):
    scan_with([{**LAN, "gateway": "10.180.103.1"}])

    nodes, edges = split(elements())

    router = nodes["router-10.180.103.1"]
    assert router["data"]["parent"] == "net-10.180.103.0/24"
    assert router["classes"] == "router synthetic"
    assert edges["out-router-10.180.103.1"]["data"]["target"] == "internet"


def test_a_network_inside_another(make_device):
    half = {**LAN, "network": "10.180.103.0/25"}
    scan_with([LAN, half])
    device = make_device("10.180.103.5")

    nodes, _ = split(elements())

    assert nodes["net-10.180.103.0/25"]["data"]["parent"] == "net-10.180.103.0/24"
    assert nodes[dev(device)]["data"]["parent"] == "net-10.180.103.0/25"


def test_no_scans_yet():
    assert elements() == [
        {"data": {"id": "hub", "label": "wall-hub", "addresses": []}, "classes": "hub"}
    ]


def test_map_pages(logged_in, make_device):
    scan_with([LAN])
    make_device("10.180.103.231")

    page = logged_in.get(reverse("network-map")).content.decode()
    data = logged_in.get(reverse("network-map-data")).json()

    assert "vendor/cytoscape.min.js" in page and "js/network_map.js" in page
    assert f'data-url="{reverse("network-map-data")}"' in page
    assert {e["data"]["id"] for e in data["elements"]} >= {"hub", "net-10.180.103.0/24"}


@pytest.mark.parametrize("name", ["network-map", "network-map-data"])
def test_map_needs_a_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]
