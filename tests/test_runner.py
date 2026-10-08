"""run_tool: from a subprocess to a validated document, or a clear reason why not."""

import subprocess

import pytest

from inventory.runner import ToolRunError, run_tool

COMMAND = ["wall-scan", "192.168.1.0/24"]


def test_valid_document_and_stderr_are_returned(fake_tool, example):
    fake_tool(stdout=example("wall-scan", "ok.json"), stderr="nmap: a warning\n")

    document, stderr = run_tool("wall-scan", COMMAND, timeout_s=10)

    assert document == example("wall-scan", "ok.json")
    assert stderr == "nmap: a warning\n"
    assert fake_tool.calls == [COMMAND]


def test_error_document_is_returned_despite_exit_code_1(fake_tool, example):
    fake_tool(stdout=example("wall-scan", "error.json"), returncode=1)

    document, _ = run_tool("wall-scan", COMMAND, timeout_s=10)

    assert document["status"] == "error"


def test_no_json_on_stdout(fake_tool):
    fake_tool(returncode=2, stderr="usage: wall-scan ...\nwall-scan: error: bad target\n")

    with pytest.raises(ToolRunError, match="exited with code 2") as exc:
        run_tool("wall-scan", COMMAND, timeout_s=10)
    assert "bad target" in exc.value.stderr


def test_document_that_breaks_the_contract(fake_tool, example):
    document = example("wall-scan", "ok.json")
    document["result"]["devices"][0]["mac"] = "50:C7:BF:12:34:56"
    fake_tool(stdout=document)

    with pytest.raises(ToolRunError, match="does not follow its contract"):
        run_tool("wall-scan", COMMAND, timeout_s=10)


def test_newer_major_version(fake_tool, example):
    document = example("wall-scan", "ok.json") | {"schema_version": "2.0"}
    fake_tool(stdout=document)

    with pytest.raises(ToolRunError, match="not supported"):
        run_tool("wall-scan", COMMAND, timeout_s=10)


def test_tool_not_installed(fake_tool):
    fake_tool(raises=FileNotFoundError())

    with pytest.raises(ToolRunError, match="wall-scan is not installed"):
        run_tool("wall-scan", COMMAND, timeout_s=10)


def test_timeout(fake_tool):
    fake_tool(raises=subprocess.TimeoutExpired(COMMAND, 10))

    with pytest.raises(ToolRunError, match="did not finish within 10 s"):
        run_tool("wall-scan", COMMAND, timeout_s=10)
