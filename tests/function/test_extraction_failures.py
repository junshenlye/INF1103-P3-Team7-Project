"""Provider-stage contracts, deterministic ordering and owned client closure."""

import asyncio

import pytest
from PIL import Image

from src.ai_manager import (
    AIManager,
    ResponseParser,
    ResponseValidator,
    ResponseValidationError,
)
from tests.fakes import FakeProvider


@pytest.mark.parametrize("mode", ["malformed", "invalid_structure", "transport"])
def test_owned_clients_close_and_failed_modules_are_removed(tmp_path, mode):
    path = tmp_path / "evidence.png"
    Image.new("RGB", (20, 20)).save(path)
    options = (
        {"malformed_modules": ["INF1103"]}
        if mode == "malformed"
        else (
            {"invalid_structure": True}
            if mode == "invalid_structure"
            else {"fail_modules": ["INF1103"]}
        )
    )
    provider = FakeProvider(**options)
    payload, errors = asyncio.run(
        AIManager(lambda: provider).process_payload(
            {
                "modules": [
                    {
                        "module_title": "INF1103",
                        "credit": 6,
                        "stored_file_paths": [str(path)],
                    }
                ]
            },
            [],
        )
    )
    assert payload is None and len(errors) == 1
    assert provider.closed


def test_all_evidence_reaches_dependent_stages_in_order_with_bounded_requests(tmp_path):
    paths = []
    for i in range(2):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (20 + i, 20)).save(path)
        paths.append(str(path))
    provider = FakeProvider(delay=0.001)
    titles = [f"INF11{i:02}" for i in range(9)]
    payload, errors = asyncio.run(
        AIManager(lambda: provider).process_payload(
            {
                "modules": [
                    {"module_title": title, "credit": 6, "stored_file_paths": paths}
                    for title in titles
                ]
            },
            [],
        )
    )
    assert (
        errors == []
        and [module["module_title"] for module in payload["modules"]] == titles
    )
    assert provider.maximum == 4
    for title in titles:
        requests = [
            request
            for request in provider.requests
            if f"MODULE: {title}" in request["messages"][0]["content"][0]["text"]
        ]
        assert len(requests) == 3
        assert all(len(request["messages"][0]["content"]) == 3 for request in requests)
        assert (
            "INTERPRETATION MEMO:"
            not in requests[1]["messages"][0]["content"][0]["text"]
        )
        assert (
            "Source-faithful interpretation memo"
            in requests[2]["messages"][0]["content"][0]["text"]
        )


@pytest.mark.parametrize("value", [{}, {"relevant": "true"}, {"relevant": 1}])
def test_relevance_requires_boolean(value):
    with pytest.raises(ResponseValidationError):
        ResponseValidator().relevance(value)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        {"assessment_types": [None]},
        {"assessment_types": [{"type": "quiz", "assessments": [None]}]},
    ],
)
def test_normalization_structure_is_rejected_before_domain_use(value):
    with pytest.raises(ResponseValidationError):
        ResponseValidator().normalization(value)


def test_parser_accepts_single_markdown_fence():
    assert ResponseParser().parse('```json\n{"assessment_types": []}\n```') == {
        "assessment_types": []
    }


def test_client_close_failure_preserves_successful_extraction(tmp_path):
    class CloseFailure(FakeProvider):
        async def close(self):
            self.closed = True
            raise OSError("close failed")

    path = tmp_path / "quiz.png"
    Image.new("RGB", (20, 20)).save(path)
    provider = CloseFailure()
    result, errors = asyncio.run(
        AIManager(lambda: provider).process_payload(
            {
                "modules": [
                    {
                        "module_title": "INF1103",
                        "credit": 6,
                        "stored_file_path": str(path),
                    }
                ]
            },
            [],
        )
    )
    assert result["module_count"] == 1 and provider.closed
    assert errors == ["AI Manager error: client cleanup: close failed"]


def test_advice_configuration_failure_preserves_legacy_error_contract():
    def unavailable():
        raise ValueError("DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL must be configured.")

    result, errors = asyncio.run(
        AIManager(unavailable).process_recommendation({}, "work_checklist", {}, [])
    )
    assert result is None
    assert errors == [
        "AI Manager error: configuration: DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL must be configured."
    ]
