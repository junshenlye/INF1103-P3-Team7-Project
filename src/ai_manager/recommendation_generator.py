"""Interchangeable asynchronous generators for the two existing advice types."""

from abc import ABC, abstractmethod
import json
from ..ai_prompts import WORK_CHECKLIST_PROMPT, TRIMESTER_REVISION_PROMPT
from .qwen_client import REASONING_MODEL
from .response_parser import ResponseParser, ResponseValidator, ResponseValidationError


class RecommendationGenerator(ABC):
    """Return a parsed advice object or raise; callers own domain validation."""

    @property
    @abstractmethod
    def recommendation_type(self):
        raise NotImplementedError

    @abstractmethod
    def messages(self, project, preferences):
        raise NotImplementedError

    async def generate(self, transport, project, preferences):
        content = await transport.request(
            REASONING_MODEL,
            self.messages(project, preferences),
            True,
            f"{self.recommendation_type} recommendation",
        )
        response = ResponseValidator().object(
            ResponseParser().parse(content), "Recommendation"
        )
        return self.validate_response(response)

    def validate_response(self, response):
        return response


class ChecklistGenerator(RecommendationGenerator):
    recommendation_type = "work_checklist"

    def validate_response(self, response):
        if response.get(
            "recommendation_type"
        ) != self.recommendation_type or not isinstance(response.get("items"), list):
            raise ResponseValidationError(
                "Checklist response must contain the requested type and item array."
            )
        return response

    def messages(self, project, preferences):
        context = {"confirmed_project": project, "study_preferences": preferences}
        return [
            {
                "role": "user",
                "content": f"{WORK_CHECKLIST_PROMPT}\n\nINPUT DATA:\n{json.dumps(context)}",
            }
        ]


class RevisionPlanGenerator(RecommendationGenerator):
    recommendation_type = "trimester_revision_plan"

    def validate_response(self, response):
        if response.get(
            "recommendation_type"
        ) != self.recommendation_type or not isinstance(response.get("weeks"), list):
            raise ResponseValidationError(
                "Revision response must contain the requested type and week array."
            )
        return response

    def messages(self, project, preferences):
        context = {"confirmed_project": project, "study_preferences": preferences}
        return [
            {
                "role": "user",
                "content": f"{TRIMESTER_REVISION_PROMPT}\n\nINPUT DATA:\n{json.dumps(context)}",
            }
        ]
