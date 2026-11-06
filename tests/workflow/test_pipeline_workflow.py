"""Workflow tests for the manager chain in the CLI entry point."""

from pathlib import Path

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
    logic_payload = dict(ai_payload)
    logic_payload["schedule"] = {
        "week_count": 14,
        "weeks": [],
        "unscheduled": [],
    }

    monkeypatch.setattr(
        main.io_manager,
        "parse_cli_arguments",
        lambda argv: {"payload_file": "payload.json"},
    )
    monkeypatch.setattr(main.data_manager, "is_configured", lambda: False)
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

    def fake_logic_process(payload, errors):
        assert payload is ai_payload
        assert errors is hard_errors
        return logic_payload, errors

    monkeypatch.setattr(main.logic_manager, "process_payload", fake_logic_process)

    async def fake_recommendation(payload, recommendation_type, preferences, errors):
        assert payload is logic_payload
        assert recommendation_type == "trimester_revision_plan"
        return {
            "recommendation_type": recommendation_type,
            "summary": "Automatic advice.",
            "highlights": [],
            "weeks": [],
        }, errors

    monkeypatch.setattr(
        main.ai_manager,
        "process_recommendation",
        fake_recommendation,
    )

    payload, errors = main.main([])

    assert payload["study_plan"]["summary"] == "Automatic advice."
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
    recommendation_called = False

    monkeypatch.setattr(
        main.io_manager,
        "parse_cli_arguments",
        lambda argv: {"payload_file": "payload.json"},
    )
    monkeypatch.setattr(main.data_manager, "is_configured", lambda: False)
    monkeypatch.setattr(
        main.io_manager,
        "process_cli_input",
        lambda cli_input: (None, hard_errors),
    )

    async def fake_ai_process(payload, errors):
        nonlocal ai_called
        ai_called = True

    monkeypatch.setattr(main.ai_manager, "process_payload", fake_ai_process)

    async def fake_recommendation(payload, recommendation_type, preferences, errors):
        nonlocal recommendation_called
        recommendation_called = True

    monkeypatch.setattr(
        main.ai_manager,
        "process_recommendation",
        fake_recommendation,
    )

    payload, errors = main.main([])

    assert payload is None
    assert errors is hard_errors
    assert ai_called is False
    assert recommendation_called is False


def test_pipeline_persists_successful_result(monkeypatch, tmp_path, database_url):
    """The manager chain finishes by storing its Logic Manager payload."""
    source = tmp_path / "module.png"
    source.write_bytes(b"validated-image")
    io_payload = {
        "module_count": 1,
        "modules": [
            {
                "module_title": "INF1104",
                "credit": 4,
                "stored_file_path": str(source),
            }
        ],
    }
    module = {
        "module_title": "INF1104",
        "credit": 4,
        "source_coverage": {"status": "appears_complete", "comment": None},
        "assessment_types": [],
        "notes": [],
        "follow_ups": [],
    }
    ai_payload = {"module_count": 1, "modules": [module]}
    final_payload = dict(ai_payload)
    final_payload["schedule"] = {
        "week_count": 14,
        "weeks": [],
        "unscheduled": [],
        "scheduled_assessment_count": 0,
        "unscheduled_assessment_count": 0,
    }
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STACKPLAN_PROJECT_NAME", "Stored workflow")
    monkeypatch.setattr(
        main.io_manager,
        "parse_cli_arguments",
        lambda argv: {"payload_file": Path("payload.json")},
    )
    monkeypatch.setattr(
        main.io_manager,
        "process_cli_input",
        lambda cli_input: (io_payload, []),
    )

    async def fake_ai_process(payload, errors):
        return ai_payload, errors

    monkeypatch.setattr(main.ai_manager, "process_payload", fake_ai_process)
    monkeypatch.setattr(
        main.logic_manager,
        "process_payload",
        lambda payload, errors: (final_payload, errors),
    )

    expected_recommendation = {
        "recommendation_type": "trimester_revision_plan",
        "summary": "Prepare steadily.",
        "highlights": [
            {
                "title": "Start here",
                "suggestion": "Keep Week 7 free for recess.",
            }
        ],
        "weeks": [],
        "flexible_items": [],
    }

    async def fake_recommendation(payload, recommendation_type, preferences, errors):
        assert payload is final_payload
        return expected_recommendation, errors

    monkeypatch.setattr(
        main.ai_manager,
        "process_recommendation",
        fake_recommendation,
    )

    payload, errors = main.main([])

    projects = main.data_manager.list_projects(database_url)
    assert payload["study_plan"] == expected_recommendation
    assert errors == []
    assert len(projects) == 1
    stored_result = main.data_manager.get_latest_pipeline_result(
        projects[0]["id"], database_url
    )
    assert stored_result["modules"] == [module]
    assert stored_result["schedule"] == final_payload["schedule"]
    stored_recommendations = main.data_manager.list_recommendations(
        projects[0]["id"], database_url
    )
    assert stored_recommendations[0]["recommendation_payload"] == expected_recommendation
