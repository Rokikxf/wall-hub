"""Builders for test data, shared by several test modules."""

from typing import Any


def check(
    ip: str,
    up: bool = True,
    port: int | None = None,
    rtt_ms: float = 1.5,
    down_reason: str = "timeout",
) -> dict[str, Any]:
    """One valid entry of wall-healthcheck's result.checks."""
    return {
        "ip": ip,
        "method": "tcp" if port else "icmp",
        "port": port,
        "up": up,
        "successes": 3 if up else 0,
        "rtt_ms": rtt_ms if up else None,
        "down_reason": None if up else down_reason,
    }
