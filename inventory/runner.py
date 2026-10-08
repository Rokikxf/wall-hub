"""Running a wall-* tool and getting back a document that follows its contract.

Shared by the tasks for every tool. Per CONTRACT.md, stdout is parsed whatever the
exit code: a tool reports its own failures inside the document.
"""

import json
import subprocess
from typing import Any

from inventory.contracts import ContractError, validate

STDERR_LIMIT = 20_000  # keep the end of stderr, where the useful part usually is


class ToolRunError(Exception):
    """No valid document could be obtained from the tool."""

    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def run_tool(tool: str, command: list[str], timeout_s: int) -> tuple[dict[str, Any], str]:
    """Run command and return (validated document, stderr), or raise ToolRunError."""
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        raise ToolRunError(f"{command[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise ToolRunError(f"{tool} did not finish within {timeout_s} s") from None
    except OSError as exc:
        raise ToolRunError(f"Could not start {tool}: {exc}") from None

    stderr = proc.stderr[-STDERR_LIMIT:]
    try:
        document = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ToolRunError(
            f"{tool} exited with code {proc.returncode} without printing a JSON document",
            stderr,
        ) from None
    try:
        validate(tool, document)
    except ContractError as exc:
        raise ToolRunError(f"{tool} output does not follow its contract: {exc}", stderr) from None
    return document, stderr
