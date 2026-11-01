"""The gate reports failure and cleans resources when a required stage cannot run."""

import json
import subprocess
import sys

import pytest

from tests import verify


def test_failed_stage_is_reported_with_logs_and_nonzero_status(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "REPORTS", tmp_path)
    gate = verify.Gate("fast")
    with pytest.raises(RuntimeError) as raised:
        gate.run(
            "required stage",
            [sys.executable, "-c", "print('useful diagnostic'); raise SystemExit(7)"],
        )
    gate.close(False, raised.value)
    summary = json.loads((tmp_path / "fast-summary.json").read_text())
    assert summary["status"] == "failed" and summary["failed_stage"] == "required stage"
    assert "useful diagnostic" in (tmp_path / "fast.log").read_text()
    assert "status 7" in summary["error"]


@pytest.mark.parametrize("error", [RuntimeError("check failed"), KeyboardInterrupt()])
def test_disposable_resources_are_cleaned_on_failure_and_interruption(
    tmp_path, monkeypatch, error
):
    monkeypatch.setattr(verify, "REPORTS", tmp_path)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(verify.subprocess, "run", execute)
    gate = verify.Gate("integration")
    with pytest.raises(type(error)):
        with gate.containers():
            raise error
    gate.close(False, error)
    assert any("logs" in command for command in calls)
    cleanup = next(command for command in calls if "down" in command)
    assert "--volumes" in cleanup
    assert "tests/deployment/compose.yaml" in cleanup
    assert "compose.yaml" not in cleanup


def test_diagnostic_timeout_cannot_prevent_resource_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "REPORTS", tmp_path)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if "logs" in command:
            raise subprocess.TimeoutExpired(command, 30)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(verify.subprocess, "run", execute)
    gate = verify.Gate("integration")
    with gate.containers():
        pass
    gate.close(True)
    assert any("down" in command for command in calls)
    assert "Could not collect" in next(tmp_path.glob("*-docker.log")).read_text()
