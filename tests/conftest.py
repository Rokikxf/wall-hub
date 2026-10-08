import json
import subprocess

import pytest
from django.conf import settings


@pytest.fixture(scope="session")
def example():
    """Load a contract example: example("wall-scan", "ok.json")."""

    def load(tool: str, name: str) -> dict:
        path = settings.BASE_DIR / "contracts" / tool / "examples" / name
        return json.loads(path.read_text(encoding="utf-8"))

    return load


@pytest.fixture
def fake_tool(monkeypatch):
    """Replace subprocess.run in inventory.runner, so no real tool runs.

    Call the fixture to set what the fake tool does; the commands it was given
    are collected in its .calls list. A dict passed as stdout is printed as JSON.
    """

    def configure(stdout="", returncode=0, stderr="", raises=None):
        if isinstance(stdout, dict):
            stdout = json.dumps(stdout)

        def fake_run(command, **kwargs):
            configure.calls.append(command)
            if raises:
                raise raises
            return subprocess.CompletedProcess(command, returncode, stdout, stderr)

        monkeypatch.setattr("inventory.runner.subprocess.run", fake_run)
        return configure

    configure.calls = []
    return configure


@pytest.fixture
def logged_in(client, django_user_model):
    user = django_user_model.objects.create_user("admin", password="not-used")
    client.force_login(user)
    client.user = user
    return client
