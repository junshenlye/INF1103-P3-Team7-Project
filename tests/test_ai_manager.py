"""Offline tests for asynchronous AI Manager behaviour."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src import ai_manager


def make_response(content):
    """Build the small response surface consumed by AI Manager."""
    if not isinstance(content, str):
        content = json.dumps(content)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_module(tmp_path, position):
    """Create one minimal IO-shaped module with a readable temporary file."""
    image_path = tmp_path / f"module-{position}.png"
    image_path.write_bytes(f"image-{position}".encode("utf-8"))
    return {
        "module_title": f"MODULE-{position}",
        "credit": 4,
        "stored_file_path": str(image_path),
    }


def get_request_details(request):
    """Read stage and module title from a fake multimodal request."""
    prompt = request["messages"][0]["content"][0]["text"]
    module_title = prompt.split("MODULE: ", 1)[1].splitlines()[0]
    if prompt.startswith("RELEVANCE GATE"):
        stage = "relevance"
    elif prompt.startswith("INTERPRETATION PASS"):
        stage = "interpretation"
    else:
        stage = "normalization"
    return stage, module_title


def make_normalization(module_title, position=0):
    """Return one valid schedule-ready normalization result."""
    return {
        "source_coverage": {
            "status": "appears_complete",
            "comment": None,
        },
        "assessment_types": [
            {
                "type": "quiz",
                "group_weight_percent": None,
                "group_weight_scope": "unknown",
                "group_weight_scope_name": None,
                "assessments": [
                    {
                        "name": f"{module_title} Quiz",
                        "count": 1,
                        "record_role": "assessment",
                        "weight_percent": 10,
                        "weight_scope": "module",
                        "weight_scope_name": None,
                        "schedule": {
                            "kind": "week",
                            "week": position + 1,
                            "start_week": None,
                            "end_week": None,
                            "date": None,
                            "day": None,
                            "raw": f"Week {position + 1}",
                        },
                        "parent_assessment": None,
                        "details": None,
                    }
                ],
            }
        ],
        "notes": [],
        "follow_ups": [],
    }


def test_concurrent_requests_are_limited_and_output_order_is_preserved(tmp_path):
    modules = [make_module(tmp_path, position) for position in range(6)]
    payload = {"module_count": len(modules), "modules": modules}
    call_state = {"active": 0, "maximum": 0}
    completed_stages = {}

    async def fake_create(**request):
        stage, module_title = get_request_details(request)
        call_state["active"] += 1
        call_state["maximum"] = max(
            call_state["maximum"], call_state["active"]
        )
        try:
            position = int(module_title.rsplit("-", 1)[1])
            await asyncio.sleep((6 - position) * 0.002)
            completed = completed_stages.setdefault(module_title, [])
            if stage == "relevance":
                assert request["extra_body"] == {"enable_thinking": False}
                assert request["response_format"] == {"type": "json_object"}
                completed.append(stage)
                return make_response({"relevant": True, "reason": "Relevant."})
            if stage == "interpretation":
                assert completed == ["relevance"]
                assert request["extra_body"] == {"enable_thinking": True}
                assert "response_format" not in request
                completed.append(stage)
                return make_response("Complete assessment evidence memo.")

            assert completed == ["relevance", "interpretation"]
            completed.append(stage)
            return make_response(
                make_normalization(module_title, position=position)
            )
        finally:
            call_state["active"] -= 1

    fake_create_mock = AsyncMock(side_effect=fake_create)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create_mock)
        )
    )
    previous_errors = ["IO Manager error: earlier module was rejected."]

    processed_payload, errors = asyncio.run(
        ai_manager.process_payload(payload, previous_errors, client=fake_client)
    )

    assert call_state["maximum"] == ai_manager.MAX_CONCURRENT_REQUESTS
    assert fake_create_mock.await_count == len(modules) * 3
    assert processed_payload["module_count"] == len(modules)
    assert [module["module_title"] for module in processed_payload["modules"]] == [
        module["module_title"] for module in modules
    ]
    assert all(
        stages == ["relevance", "interpretation", "normalization"]
        for stages in completed_stages.values()
    )
    assert errors is previous_errors
    assert errors == ["IO Manager error: earlier module was rejected."]


def test_irrelevant_and_failed_modules_do_not_stop_other_modules(tmp_path):
    modules = [make_module(tmp_path, position) for position in range(3)]
    payload = {"module_count": len(modules), "modules": modules}

    async def fake_create(**request):
        stage, module_title = get_request_details(request)
        if stage == "relevance":
            if module_title == "MODULE-1":
                return make_response(
                    {"relevant": False, "reason": "No assessment information."}
                )
            return make_response({"relevant": True, "reason": "Relevant."})
        if stage == "interpretation":
            if module_title == "MODULE-2":
                raise RuntimeError("Inference unavailable.")
            return make_response("Complete assessment evidence memo.")
        return make_response(make_normalization(module_title))

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=fake_create))
        )
    )

    processed_payload, errors = asyncio.run(
        ai_manager.process_payload(payload, [], client=fake_client)
    )

    assert processed_payload["module_count"] == 1
    assert processed_payload["modules"][0]["module_title"] == "MODULE-0"
    assert errors == [
        "AI Manager error: MODULE-1: No assessment information.",
        "AI Manager error: MODULE-2: Inference unavailable.",
    ]


def test_repeated_assessments_expand_and_preserve_group_weight():
    normalized = {
        "source_coverage": {
            "status": "appears_complete",
            "comment": None,
        },
        "assessment_types": [
            {
                "type": "tutorial",
                "group_weight_percent": 5,
                "group_weight_scope": "module",
                "group_weight_scope_name": None,
                "assessments": [
                    {
                        "name": "Tutorial",
                        "count": 10,
                        "record_role": "assessment",
                        # Simulates a model dividing the visible 5% total by 10.
                        "weight_percent": 0.5,
                        "weight_scope": "group",
                        "weight_scope_name": "Tutorials",
                        "schedule": {
                            "kind": "recurring",
                            "week": None,
                            "start_week": None,
                            "end_week": None,
                            "date": None,
                            "day": "Sunday",
                            "raw": "Weekly, every Sunday",
                        },
                        "parent_assessment": None,
                        "details": "One topic per tutorial.",
                    }
                ],
            }
        ],
        "notes": [],
        "follow_ups": [],
    }

    module = ai_manager.build_module_output("INF1104", 4, normalized)
    tutorial_group = module["assessment_types"][0]

    assert tutorial_group["declared_count"] == 10
    assert tutorial_group["group_weight_percent"] == 5
    assert [item["name"] for item in tutorial_group["assessments"]] == [
        f"Tutorial {position}" for position in range(1, 11)
    ]
    assert len(
        {item["assessment_id"] for item in tutorial_group["assessments"]}
    ) == 10
    assert all(
        item["weight_percent"] is None
        for item in tutorial_group["assessments"]
    )
    assert {(item["occurrence_number"], item["occurrence_count"])
            for item in tutorial_group["assessments"]} == {
        (position, 10) for position in range(1, 11)
    }
    assert {(item["schedule"]["kind"])
            for item in tutorial_group["assessments"]} == {"recurring"}
    assert {(follow_up["field"], follow_up["assessment"])
            for follow_up in module["follow_ups"]} == {
        ("schedule", "Tutorial"),
        ("weight_percent", "tutorial"),
    }


def test_parent_assessment_names_become_deterministic_ids():
    normalized = {
        "source_coverage": {
            "status": "appears_complete",
            "comment": None,
        },
        "assessment_types": [
            {
                "type": "project",
                "group_weight_percent": None,
                "group_weight_scope": "unknown",
                "group_weight_scope_name": None,
                "assessments": [
                    {
                        "name": "Research Project",
                        "count": 1,
                        "record_role": "group",
                        "weight_percent": 50,
                        "weight_scope": "module",
                        "weight_scope_name": None,
                        "schedule": {"kind": "unknown"},
                        "parent_assessment": None,
                        "details": None,
                    }
                ],
            },
            {
                "type": "proposal",
                "group_weight_percent": None,
                "group_weight_scope": "unknown",
                "group_weight_scope_name": None,
                "assessments": [
                    {
                        "name": "Technical Design Proposal",
                        "count": 1,
                        "record_role": "assessment",
                        "weight_percent": 30,
                        "weight_scope": "module",
                        "weight_scope_name": None,
                        "schedule": {
                            "kind": "week",
                            "week": 13,
                            "raw": "Week 13",
                        },
                        "parent_assessment": "Research Project",
                        "details": None,
                    }
                ],
            },
        ],
        "notes": [],
        "follow_ups": [
            {
                "assessment": "Research Project",
                "field": "schedule",
                "message": "Does the group need its own date?",
            },
            {
                "assessment": "Technical Design Proposal",
                "field": "schedule",
                "message": "Please confirm this unusual ordering.",
            },
        ],
    }

    module = ai_manager.build_module_output("UCS1001", 4, normalized)
    parent = module["assessment_types"][0]["assessments"][0]
    child = module["assessment_types"][1]["assessments"][0]

    assert parent["record_role"] == "group"
    assert child["parent_assessment_id"] == parent["assessment_id"]
    assert not [
        item for item in module["follow_ups"]
        if item["field"] == "schedule"
    ]


def test_all_failed_modules_return_none(tmp_path):
    module = make_module(tmp_path, 0)

    async def fake_create(**request):
        return make_response({"relevant": False, "reason": "Not relevant."})

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=fake_create))
        )
    )

    processed_payload, errors = asyncio.run(
        ai_manager.process_payload(
            {"module_count": 1, "modules": [module]},
            [],
            client=fake_client,
        )
    )

    assert processed_payload is None
    assert errors == ["AI Manager error: MODULE-0: Not relevant."]


def test_missing_configuration_adds_one_error(monkeypatch, tmp_path):
    module = make_module(tmp_path, 0)

    def missing_configuration():
        raise ValueError(
            "DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL must be configured."
        )

    monkeypatch.setattr(ai_manager, "create_client", missing_configuration)
    previous_errors = ["IO Manager error: earlier problem."]

    processed_payload, errors = asyncio.run(
        ai_manager.process_payload(
            {"module_count": 1, "modules": [module]},
            previous_errors,
        )
    )

    assert processed_payload is None
    assert errors is previous_errors
    assert errors == [
        "IO Manager error: earlier problem.",
        "AI Manager error: configuration: DASHSCOPE_API_KEY and "
        "DASHSCOPE_BASE_URL must be configured.",
    ]
