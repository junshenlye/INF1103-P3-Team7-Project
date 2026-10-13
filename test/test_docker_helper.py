"""Workflow tests for safe Docker payload staging."""

import json

from PIL import Image

from helpers import docker_cli


def test_stage_payload_copies_images_and_rewrites_paths(tmp_path):
    """Docker receives a self-contained manifest without the original path."""
    source = tmp_path / "source.png"
    Image.new("RGB", (20, 20), "white").save(source)
    payload_path = tmp_path / "input.json"
    payload_path.write_text(
        json.dumps(
            {
                "module_count": 1,
                "modules": [
                    {
                        "module_title": "INF1104",
                        "credit": 4,
                        "file_path": "source.png",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    staged_path = docker_cli.stage_payload(payload_path, staging)
    staged = json.loads(staged_path.read_text(encoding="utf-8"))
    rewritten = staged["modules"][0]["file_path"]

    assert rewritten != "source.png"
    assert (staging / rewritten).is_file()
    command = docker_cli.build_compose_command(staging, project_id=7)
    assert command[-2:] == ["stackplan-cli", "/input/payload.json"]
    assert "STACKPLAN_PROJECT_ID=7" in command


def test_stage_payload_keeps_multiple_images_under_one_module(tmp_path):
    """Docker staging preserves a module's complete evidence set."""
    names = ["schedule.png", "weights.png"]
    for name in names:
        Image.new("RGB", (20, 20), "white").save(tmp_path / name)
    payload_path = tmp_path / "input.json"
    payload_path.write_text(
        json.dumps(
            {
                "module_count": 1,
                "modules": [
                    {
                        "module_title": "INF1102",
                        "credit": 6,
                        "file_paths": names,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    staged_path = docker_cli.stage_payload(payload_path, staging)
    staged = json.loads(staged_path.read_text(encoding="utf-8"))
    rewritten = staged["modules"][0]["file_paths"]

    assert len(rewritten) == 2
    assert all((staging / name).is_file() for name in rewritten)
