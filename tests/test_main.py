"""Tests for the manager chain in the CLI entry point."""

import asyncio

from src import main


def test_pipeline_flushes_hard_errors_and_keeps_soft_comments(monkeypatch):
    io_payload = {
        "module_count": 1,
        "modules": [
            {
                "module_title": "INF1104",
                "credit": 4,
                "stored_file_path": "/tmp/inf1104.png",
            }
        ],
    }
    hard_errors = ["IO Manager error: an earlier module was removed."]
    ai_payload = {
        "module_count": 1,
        "modules": [
            {
                "module_title": "INF1104",
                "follow_ups": [
                    {
                        "field": "schedule",
                        "message": "Tutorial week range is not stated.",
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr(
        main.io_manager,
        "parse_cli_arguments",
        lambda argv: {"payload_file": "payload.json"},
    )
    monkeypatch.setattr(
        main.io_manager,
        "process_cli_input",
        lambda cli_input: (io_payload, hard_errors),
    )

    async def fake_ai_process(payload, errors):
        assert payload is io_payload
        assert errors is hard_errors
        errors.append("AI Manager error: INF1103: inference unavailable.")
        return ai_payload, errors

    monkeypatch.setattr(main.ai_manager, "process_payload", fake_ai_process)

    payload, errors = asyncio.run(main.run_pipeline([]))

    assert payload is ai_payload
    assert errors is hard_errors
    assert errors == [
        "IO Manager error: an earlier module was removed.",
        "AI Manager error: INF1103: inference unavailable.",
    ]
    assert payload["modules"][0]["follow_ups"] == [
        {
            "field": "schedule",
            "message": "Tutorial week range is not stated.",
        }
    ]


def test_pipeline_stops_when_io_has_no_payload(monkeypatch):
    hard_errors = ["IO Manager error: no usable modules."]
    ai_called = False

    monkeypatch.setattr(
        main.io_manager,
        "parse_cli_arguments",
        lambda argv: {"payload_file": "payload.json"},
    )
    monkeypatch.setattr(
        main.io_manager,
        "process_cli_input",
        lambda cli_input: (None, hard_errors),
    )

    async def fake_ai_process(payload, errors):
        nonlocal ai_called
        ai_called = True

    monkeypatch.setattr(main.ai_manager, "process_payload", fake_ai_process)

    payload, errors = asyncio.run(main.run_pipeline([]))

    assert payload is None
    assert errors is hard_errors
    assert ai_called is False
