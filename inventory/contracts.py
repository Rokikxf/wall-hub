"""The hub's own copies of the wall-* output contracts.

contracts/<tool>/v<major>.json is the schema for every <major>.x version of that
tool's output. A document is validated against the copy chosen by the major number
in its schema_version, so a tool can add fields (a minor version) without a hub
update, while a new major version is rejected until the hub has been taught it.
"""

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
MESSAGE_LIMIT = 300


class ContractError(Exception):
    """A tool's output does not follow a contract this hub supports."""


def contracts_dir() -> Path:
    return settings.BASE_DIR / "contracts"


@cache
def validator(tool: str, major: int) -> Draft202012Validator | None:
    path = contracts_dir() / tool / f"v{major}.json"
    if not path.is_file():
        return None
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate(tool: str, document: Any) -> None:
    """Raise ContractError unless document is valid output of tool."""
    if not isinstance(document, dict):
        raise ContractError("output is not a JSON object")
    version = document.get("schema_version")
    match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ContractError(f"missing or malformed schema_version: {version!r}")
    schema = validator(tool, int(match.group(1)))
    if schema is None:
        raise ContractError(f"{tool} schema version {version} is not supported by this hub")
    error = best_match(schema.iter_errors(document))
    if error is not None:
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        message = error.message
        if len(message) > MESSAGE_LIMIT:
            message = message[: MESSAGE_LIMIT - 3] + "..."
        raise ContractError(f"{where}: {message}")
