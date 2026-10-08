"""Startup checks (manage.py check, runserver, migrate): refuse to run with
contract validation that would silently pass invalid documents."""

import json

from django.core.checks import Error, register
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from inventory.contracts import contracts_dir


@register()
def date_time_values_are_checked(app_configs, **kwargs):
    # Without rfc3339-validator, jsonschema silently skips "format": "date-time".
    if "date-time" in Draft202012Validator.FORMAT_CHECKER.checkers:
        return []
    return [
        Error(
            "jsonschema cannot check date-time values",
            hint="Install rfc3339-validator (it is in requirements.txt).",
            id="inventory.E001",
        )
    ]


@register()
def contracts_are_valid_schemas(app_configs, **kwargs):
    errors = []
    paths = sorted(contracts_dir().glob("*/v*.json"))
    if not paths:
        errors.append(Error(f"no contracts found in {contracts_dir()}", id="inventory.E002"))
    for path in paths:
        try:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, SchemaError) as exc:
            errors.append(Error(f"{path.name} of {path.parent.name}: {exc}", id="inventory.E003"))
    return errors
