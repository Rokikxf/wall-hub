"""The hub's copies of the contracts, in contracts/<tool>/v1.json.

Each contract accepts its examples, rejects deliberately broken documents and
accepts what a later 1.x version may add. The shared envelope must be identical
in all of them, since there is no shared library to keep it in sync.
"""

import copy
import json

import pytest
from django.conf import settings

from inventory.contracts import ContractError, validate

CONTRACTS = settings.BASE_DIR / "contracts"
TOOLS = sorted(p.name for p in CONTRACTS.iterdir() if p.is_dir())
EXAMPLES = sorted(CONTRACTS.glob("*/examples/*.json"))
ENVELOPE_KEYS = ["required", "properties", "allOf"]
ENVELOPE_DEFS = ["schema_version", "tool", "timestamp", "error"]

DELETE = object()
ERR = {"code": "test_error", "message": "test", "target": None}

# (tool, example, what the change breaks, {dotted.path: new value})
MUST_FAIL = [
    ("wall-scan", "ok.json", "status ok but errors not empty", {"errors": [ERR]}),
    (
        "wall-scan",
        "ok.json",
        "status error but result present",
        {"status": "error", "errors": [ERR]},
    ),
    ("wall-scan", "ok.json", "status partial without errors", {"status": "partial"}),
    ("wall-scan", "ok.json", "timestamp not in UTC", {"started_at": "2026-10-08T10:30:00+01:00"}),
    ("wall-scan", "ok.json", "impossible date", {"started_at": "2026-13-45T09:30:00Z"}),
    ("wall-scan", "ok.json", "uppercase MAC", {"result.devices.0.mac": "50:C7:BF:12:34:56"}),
    (
        "wall-scan",
        "ok.json",
        "field omitted instead of null",
        {"result.devices.0.hostname": DELETE},
    ),
    ("wall-scan", "ok.json", "invalid IPv4 address", {"result.devices.0.ip": "192.168.1.300"}),
    ("wall-scan", "ok.json", "port out of range", {"result.devices.0.open_ports.0.port": 70000}),
    ("wall-scan", "ok.json", "timeout missing from params", {"params.timeout_s": DELETE}),
    ("wall-scan", "error.json", "error code not snake_case", {"errors.0.code": "Nmap Not Found"}),
    ("wall-healthcheck", "ok.json", "up without rtt", {"result.checks.0.rtt_ms": None}),
    ("wall-healthcheck", "ok.json", "tcp check without port", {"result.checks.1.port": None}),
    ("wall-healthcheck", "ok.json", "icmp check with port", {"result.checks.0.port": 80}),
    ("wall-healthcheck", "ok.json", "down without reason", {"result.checks.3.down_reason": None}),
    ("wall-healthcheck", "ok.json", "down with successes", {"result.checks.3.successes": 1}),
    ("wall-snmpinfo", "printer.json", "percent unmeasured", {"result.supplies.2.percent": 50}),
    ("wall-snmpinfo", "printer.json", "percent above 100", {"result.supplies.0.percent": 150}),
    (
        "wall-snmpinfo",
        "printer.json",
        "unknown level_state",
        {"result.supplies.0.level_state": "low"},
    ),
    ("wall-snmpinfo", "printer.json", "OID not dotted", {"result.system.object_id": "iso.3.6.1"}),
    ("wall-snmpinfo", "printer.json", "empty string not null", {"result.system.name": ""}),
    ("wall-wol", "wake.json", "MAC with dashes", {"result.targets.0.mac": "3c-52-82-4a-1f-07"}),
    ("wall-wol", "wake.json", "zero packets requested", {"params.count": 0}),
    ("wall-wol", "wake.json", "no targets", {"result.targets": []}),
    ("wall-wol", "wake.json", "IPv6 source address", {"result.source_ip": "fe80::1"}),
]

# Changes a later 1.x version may make; the v1 contract must still accept them.
MUST_PASS = [
    ("wall-scan", "ok.json", "newer minor version", {"schema_version": "1.4"}),
    ("wall-scan", "ok.json", "new field on a device", {"result.devices.0.os_guess": "Linux 5.x"}),
    ("wall-snmpinfo", "printer.json", "new field in result", {"result.manufacturer": "HP"}),
    ("wall-wol", "wake.json", "new field on a target", {"result.targets.0.secureon": False}),
    (
        "wall-healthcheck",
        "ok.json",
        "error code never seen before",
        {"status": "partial", "errors": [{"code": "new_code", "message": "x", "target": None}]},
    ),
]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def changed(tool, example, changes):
    doc = copy.deepcopy(load(CONTRACTS / tool / "examples" / example))
    for path, value in changes.items():
        *parents, last = [int(p) if p.isdigit() else p for p in path.split(".")]
        node = doc
        for key in parents:
            node = node[key]
        if value is DELETE:
            del node[last]
        else:
            node[last] = value
    return doc


def test_all_four_tools_have_a_contract():
    assert TOOLS == ["wall-healthcheck", "wall-scan", "wall-snmpinfo", "wall-wol"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_examples_follow_their_contract(path):
    validate(path.parent.parent.name, load(path))


@pytest.mark.parametrize(
    "tool, example, label, changes", MUST_FAIL, ids=[case[2] for case in MUST_FAIL]
)
def test_broken_documents_are_rejected(tool, example, label, changes):
    with pytest.raises(ContractError):
        validate(tool, changed(tool, example, changes))


@pytest.mark.parametrize(
    "tool, example, label, changes", MUST_PASS, ids=[case[2] for case in MUST_PASS]
)
def test_later_minor_versions_are_accepted(tool, example, label, changes):
    validate(tool, changed(tool, example, changes))


def test_envelope_is_identical_in_every_contract():
    schemas = {tool: load(CONTRACTS / tool / "v1.json") for tool in TOOLS}
    reference = schemas["wall-scan"]
    for tool, schema in schemas.items():
        for key in ENVELOPE_KEYS:
            assert schema[key] == reference[key], f"{tool}: {key} differs from wall-scan"
        for name in ENVELOPE_DEFS:
            assert schema["$defs"][name] == reference["$defs"][name], f"{tool}: $defs/{name}"


def test_unsupported_major_version():
    with pytest.raises(ContractError, match="2.0 is not supported"):
        validate("wall-scan", changed("wall-scan", "ok.json", {"schema_version": "2.0"}))


def test_unknown_tool():
    with pytest.raises(ContractError, match="not supported"):
        validate("wall-nothing", changed("wall-scan", "ok.json", {}))


@pytest.mark.parametrize("version", [None, 1, "1", "v1.0", "1.0.0"])
def test_malformed_schema_version(version):
    with pytest.raises(ContractError, match="schema_version"):
        validate("wall-scan", changed("wall-scan", "ok.json", {"schema_version": version}))


def test_output_that_is_not_an_object():
    with pytest.raises(ContractError, match="not a JSON object"):
        validate("wall-scan", [])
