"""The network map: the hub, the networks it scanned and the devices in them.

Everything comes from what the hub already has. The networks and how the hub
reaches them come from result.networks in recent wall-scan documents (schema
1.1): the interface, the hub's own address on each network and the network's
gateway. Older 1.0 documents give only the ranges in params.targets. Each
device is drawn inside the most specific network that contains its address.

The result is a list of Cytoscape.js elements; static/js/network_map.js draws
them. Nodes:
- "hub": the hub itself. Its own addresses are not drawn as devices.
- "net-<cidr>": a network, drawn as a box around its devices. A network inside
  another one (a /25 in a /24) is drawn inside it.
- "dev-<pk>": a device, with classes for its type, health and whether the
  newest scan of its network still saw it.
- "router-<ip>": a gateway that no scan has found as a device.
- "internet": where the networks' gateways lead.
"""

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils.timesince import timesince

from inventory.models import Device, Scan

# Scans to take networks from, newest first. With hourly automatic sweeps that
# is about two days, so a network that is no longer scanned drops off.
RECENT_SCANS = 50
# Scans whose devices are searched for the hub's own addresses: nmap reports the
# scanning host with discovery_reason "localhost-response". Only needed for 1.0
# documents, which have no result.networks.
SELF_SCANS = 3
OTHER = "other"  # the box for devices outside every known network


def finished_scans():
    """Scans that produced a result, newest first. A failed scan says nothing about
    which devices are there, so it must not make them look gone."""
    done = [Scan.Status.OK, Scan.Status.PARTIAL]
    return Scan.objects.filter(status__in=done, output__isnull=False).order_by("-pk")


@dataclass(frozen=True)
class Network:
    network: ipaddress.IPv4Network
    attached: bool | None
    interface: str | None
    address: str | None
    gateway: str | None
    scanned_at: datetime


def known_networks() -> list[Network]:
    """The newest details of every network in the recent scans, sorted by address."""
    rows = finished_scans().values_list(
        "output__result__networks", "output__params__targets", "started_at", "created_at"
    )[:RECENT_SCANS]
    found: dict[ipaddress.IPv4Network, Network] = {}
    for entries, targets, started_at, created_at in rows:
        if entries is None:  # a 1.0 document: only the ranges are known
            entries = [{"network": target} for target in targets or [] if "/" in target]
        for entry in entries:
            try:
                network = ipaddress.IPv4Network(entry["network"], strict=False)
            except (KeyError, ValueError):
                continue
            if network.prefixlen > 30 or network in found:  # newest first: keep the first
                continue
            found[network] = Network(
                network,
                entry.get("attached"),
                entry.get("interface"),
                entry.get("address"),
                entry.get("gateway"),
                started_at or created_at,
            )
    return sorted(found.values(), key=lambda n: (n.network.network_address, n.network.prefixlen))


def hub_addresses(networks: list[Network]) -> set[str]:
    addresses = {n.address for n in networks if n.address}
    for output in finished_scans().values_list("output", flat=True)[:SELF_SCANS]:
        for device in (output.get("result") or {}).get("devices", []):
            if device.get("discovery_reason") == "localhost-response":
                addresses.add(device["ip"])
    return addresses


def innermost(ip, networks: list[Network], exclude=None) -> Network | None:
    """The most specific network containing ip (an address or a network)."""
    containing = [
        n
        for n in networks
        if n is not exclude
        and (ip.subnet_of(n.network) if isinstance(ip, ipaddress.IPv4Network) else ip in n.network)
    ]
    return max(containing, key=lambda n: n.network.prefixlen, default=None)


def node_id(network: Network | None) -> str:
    return f"net-{network.network}" if network else OTHER


def device_label(device: Device) -> str:
    name = device.name or device.hostname
    return f"{name}\n{device.ip}" if name else device.ip


def device_node(device: Device, network: Network | None, gateway: bool) -> dict[str, Any]:
    classes = [f"kind-{device.kind}"]
    classes.append(f"health-{device.health}" if device.monitored else "unmonitored")
    seen_in_last_scan = network is None or device.last_seen >= network.scanned_at
    if not seen_in_last_scan:
        classes.append("stale")
    if gateway:
        classes.append("gateway")
    ports = ", ".join(str(port["port"]) for port in device.open_ports or [])
    return {
        "data": {
            "id": f"dev-{device.pk}",
            "parent": node_id(network),
            "label": device_label(device),
            "ip": device.ip,
            "mac": device.mac or "",
            "vendor": device.vendor,
            "hostname": device.hostname,
            "type": device.get_kind_display(),
            "health": device.get_health_display() if device.monitored else "not monitored",
            "lastSeen": f"{timesince(device.last_seen)} ago",
            "seenInLastScan": seen_in_last_scan,
            "ports": ports if device.open_ports is not None else "not scanned",
            "owner": str(device.owner or ""),
            "location": str(device.location or ""),
            "gateway": gateway,
            "url": device.get_absolute_url(),
        },
        "classes": " ".join(classes),
    }


def network_label(network: Network) -> str:
    label = str(network.network)
    if network.attached is False:
        label += " (through a router)"
    return label


def elements() -> list[dict[str, Any]]:
    """The whole map as Cytoscape.js elements: nodes first, then edges."""
    networks = known_networks()
    own = hub_addresses(networks)
    devices = list(Device.objects.select_related("owner", "location").order_by("pk"))
    gateways = {n.gateway for n in networks if n.gateway}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    hub_links = [{"ip": d.ip, "url": d.get_absolute_url()} for d in devices if d.ip in own]
    nodes.append(
        {
            "data": {"id": "hub", "label": "wall-hub", "addresses": hub_links},
            "classes": "hub",
        }
    )
    for network in networks:
        parent = innermost(network.network, networks, exclude=network)
        data = {"id": node_id(network), "label": network_label(network), "network": True}
        if parent:
            data["parent"] = node_id(parent)
        nodes.append({"data": data, "classes": "network"})
        # A 1.0 document has no address, but nmap may have reported the hub in it.
        address = network.address or next(
            (ip for ip in sorted(own) if ipaddress.IPv4Address(ip) in network.network), None
        )
        if network.attached is not False and (address or network.interface):
            # The hub's link to a network it sits on: interface and its own address.
            label = " ".join(part for part in [network.interface, address] if part)
            edges.append(
                {"data": {"id": f"link-{network.network}", "source": "hub",
                          "target": node_id(network), "label": label}}
            )  # fmt: skip

    for device in devices:
        if device.ip in own:
            continue  # the hub itself
        network = innermost(ipaddress.IPv4Address(device.ip), networks)
        nodes.append(device_node(device, network, device.ip in gateways))
    if any(node["data"].get("parent") == OTHER for node in nodes):
        nodes.append(
            {"data": {"id": OTHER, "label": "Not in a scanned network", "network": True},
             "classes": "network other"}
        )  # fmt: skip

    def router(ip: str) -> str:
        """The node id of the device at ip, adding a router node if no scan found one."""
        candidates = [d for d in devices if d.ip == ip and d.ip not in own]
        if candidates:
            return f"dev-{max(candidates, key=lambda d: d.last_seen).pk}"
        if ip in own:
            return "hub"
        node = f"router-{ip}"
        if not any(n["data"]["id"] == node for n in nodes):
            where = innermost(ipaddress.IPv4Address(ip), networks)
            nodes.append(
                {"data": {"id": node, "parent": node_id(where) if where else None,
                          "label": f"Router\n{ip}", "ip": ip, "gateway": True},
                 "classes": "router synthetic"}
            )  # fmt: skip
        return node

    internet_used = False
    for network in networks:
        if not network.gateway:
            continue
        source = router(network.gateway)
        if network.attached:
            # The way out of this network.
            internet_used = True
            edge_id = f"out-{source}"
            if not any(e["data"]["id"] == edge_id for e in edges):
                edges.append({"data": {"id": edge_id, "source": source, "target": "internet"}})
        else:
            # A network behind a router: the hub's traffic goes through that router.
            edges.append(
                {"data": {"id": f"route-{network.network}", "source": source,
                          "target": node_id(network), "label": "route"}}
            )  # fmt: skip
    if internet_used:
        nodes.append({"data": {"id": "internet", "label": "Internet"}, "classes": "internet"})
    for node in nodes:  # Cytoscape rejects a parent of None
        if node["data"].get("parent") is None:
            node["data"].pop("parent", None)
    return nodes + edges
