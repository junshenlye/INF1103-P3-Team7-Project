"""Compatibility adapters; new workflows inject AIManager."""

import time
from .manager import (
    AIManager,
    format_ai_error,
    PROMPT_VERSION,
    RECOMMENDATION_PROMPT_VERSION,
)
from .qwen_client import (
    QwenClient,
    create_client,
    RELEVANCE_MODEL,
    REASONING_MODEL,
    MAX_CONCURRENT_REQUESTS,
    AITransportError,
)
from .request_builder import RequestBuilder
from .response_parser import ResponseParser, ResponseValidator, ResponseValidationError
from .recommendation_generator import (
    RecommendationGenerator,
    ChecklistGenerator,
    RevisionPlanGenerator,
)


def image_to_data_url(path):
    return RequestBuilder().image_to_data_url(path)


def create_image_messages(prompt, module_title, image_data, extra_text=None):
    return RequestBuilder().create_image_messages(
        prompt, module_title, image_data, extra_text
    )


def parse_json_content(content):
    return ResponseParser().parse(content)


def validate_json_object(value, response_name):
    return ResponseValidator().object(value, response_name)


async def call_model(
    client, model, messages, thinking, semaphore, task_name, json_mode=False
):
    return await QwenClient(client, semaphore).request(
        model, messages, thinking, task_name, json_mode
    )


async def process_payload(payload, errors, client=None):
    return await AIManager(client_factory=create_client).process_payload(
        payload, errors, client
    )


async def process_recommendation(
    project_payload, recommendation_type, preferences, errors, client=None
):
    return await AIManager(client_factory=create_client).process_recommendation(
        project_payload, recommendation_type, preferences, errors, client
    )
