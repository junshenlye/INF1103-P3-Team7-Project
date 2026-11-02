"""Each interchangeable generator obeys the same async success/failure contract."""

import asyncio
import json

import pytest

from src.ai_manager import (
    AIManager,
    ChecklistGenerator,
    RevisionPlanGenerator,
    RecommendationGenerator,
    ResponseValidationError,
)
from src.ai_manager.qwen_client import QwenClient
from src.logic_manager import ModuleNormalizer, ScheduleBuilder, RecommendationValidator
from tests.fakes import FakeProvider, extraction


@pytest.mark.parametrize("generator", [ChecklistGenerator(), RevisionPlanGenerator()])
def test_generation_contract_accepts_same_inputs_and_returns_valid_advice(generator):
    module = ModuleNormalizer().normalize(
        {
            "module_title": "INF1103",
            "credit": 6,
            "ai_relevance": {"relevant": True},
            "ai_output": extraction(),
        }
    )
    project = {
        "modules": [module.to_record()],
        "schedule": ScheduleBuilder().build((module,), []).to_record(),
    }
    provider = FakeProvider()
    result = asyncio.run(generator.generate(QwenClient(provider), project, {}))
    plan = RecommendationValidator().validate(
        result, generator.recommendation_type, project, {}
    )
    assert plan.recommendation_type == generator.recommendation_type
    assert plan.summary == "Prepare steadily"
    assert not provider.closed  # The injected transport is borrowed.
    context = json.loads(
        provider.requests[0]["messages"][0]["content"].split("INPUT DATA:\n")[-1]
    )
    assert context["confirmed_project"] == project


@pytest.mark.parametrize("generator", [ChecklistGenerator(), RevisionPlanGenerator()])
@pytest.mark.parametrize("content", ["invalid JSON", "[]", "null"])
def test_generators_reject_invalid_output_with_same_failure_contract(
    generator, content
):
    class Transport:
        async def request(self, *args, **kwargs):
            return content

    with pytest.raises(ResponseValidationError):
        asyncio.run(generator.generate(Transport(), {}, {}))


def test_new_generator_is_registered_without_workflow_changes():
    class RegisteredGenerator(RecommendationGenerator):
        recommendation_type = "test_contract"

        def messages(self, project, preferences):
            return [{"role": "user", "content": "custom"}]

    class Provider:
        closed = False

        async def close(self):
            self.closed = True

    # A contract implementation can own generation as well as request construction.
    class CustomGenerator(RegisteredGenerator):
        async def generate(self, transport, project, preferences):
            return {
                "recommendation_type": self.recommendation_type,
                "summary": "custom",
            }

    provider = Provider()
    result, errors = asyncio.run(
        AIManager(lambda: provider, [CustomGenerator()]).process_recommendation(
            {}, "test_contract", {}, []
        )
    )
    assert result["summary"] == "custom" and errors == [] and provider.closed
