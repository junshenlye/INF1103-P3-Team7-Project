"""Call Qwen for assessment extraction and study recommendations.

Each relevant module uses two Qwen reasoning passes. The first builds a
source-faithful evidence memo without the final schema. The second converts
that memo into small assessment prototypes. This manager stops at parsed JSON;
Logic Manager owns deterministic normalization, validation and scheduling.
"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
import time

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .ai_prompts import (
    INTERPRETATION_PROMPT,
    NORMALIZATION_PROMPT,
    RELEVANCE_PROMPT,
    TRIMESTER_REVISION_PROMPT,
    WORK_CHECKLIST_PROMPT,
)


RELEVANCE_MODEL = "qwen3.7-flash"
REASONING_MODEL = "qwen3.7-plus"
MAX_CONCURRENT_REQUESTS = 4
PROMPT_VERSION = "2026-10-12-v3"
RECOMMENDATION_PROMPT_VERSION = "2026-10-13-r5"
LOGGER = logging.getLogger(__name__)

RECOMMENDATION_TYPES = {
    "work_checklist": WORK_CHECKLIST_PROMPT,
    "trimester_revision_plan": TRIMESTER_REVISION_PROMPT,
}


def format_ai_error(module_title, error):
    """Return one hard-error string for a module or AI configuration issue.

    Hard errors leave the module payload and are appended to the shared pipeline
    error list. Soft uncertainties use module ``follow_ups`` instead.
    """
    return f"AI Manager error: {module_title}: {error}"


def create_client():
    """Create the shared asynchronous Qwen client.

    The API key and compatible endpoint come from the environment. Missing
    configuration raises ``ValueError`` before any module requests are started.
    """
    load_dotenv()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_BASE_URL")
    if not api_key or not base_url:
        raise ValueError(
            "DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL must be configured."
        )

    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def image_to_data_url(file_path):
    """Return an IO-validated image as a Base64 data URL for Qwen.

    File type, size and readability are not checked again here because those
    checks belong to IO Manager.
    """
    image_path = Path(file_path)
    mime_type, _ = mimetypes.guess_type(image_path.name)
    encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_image}"


def create_image_messages(prompt, module_title, image_data, extra_text=None):
    """Build one multimodal message containing all module evidence images.

    The normalization pass also supplies the earlier interpretation memo.
    A string is accepted for backwards compatibility with existing callers.
    """
    text = f"{prompt}\n\nMODULE: {module_title}"
    if extra_text is not None:
        text += f"\n\nINTERPRETATION MEMO:\n{extra_text}"

    if isinstance(image_data, str):
        image_data = [image_data]

    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                *[
                    {"type": "image_url", "image_url": {"url": image}}
                    for image in image_data
                ],
            ]
        }
    ]


async def call_model(
    client,
    model,
    messages,
    thinking,
    semaphore,
    task_name,
    json_mode=False,
):
    """Send one Qwen request and return its non-empty text response.

    ``semaphore`` enforces the pipeline-wide concurrency limit. Timing starts
    after the semaphore is acquired, so logs measure the HTTP request rather
    than queue time. ``json_mode`` is used only when the provider supports it.
    """
    request = {
        "model": model,
        "messages": messages,
        "extra_body": {"enable_thinking": thinking},
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}

    async with semaphore:
        LOGGER.info("HTTP task started: %s [%s]", task_name, model)
        started_at = time.perf_counter()
        try:
            response = await client.chat.completions.create(**request)
        except Exception:
            elapsed_seconds = time.perf_counter() - started_at
            LOGGER.info(
                "HTTP task failed: %s [%s] after %.2f seconds",
                task_name,
                model,
                elapsed_seconds,
            )
            raise

        elapsed_seconds = time.perf_counter() - started_at
        LOGGER.info(
            "HTTP task completed: %s [%s] in %.2f seconds",
            task_name,
            model,
            elapsed_seconds,
        )

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as error:
        raise ValueError("Model returned no readable content.") from error
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model returned no readable content.")
    return content.strip()


def parse_json_content(content):
    """Decode model text as JSON and return the resulting Python value.

    A single surrounding Markdown fence is accepted because models sometimes
    add it despite the prompt. Any other malformed output is a hard failure.
    """
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(stripped)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Model returned invalid JSON.") from error


def validate_json_object(value, response_name):
    """Return a parsed model response only when its root is a JSON object.

    AI Manager validates the transport-level response contract. Logic Manager
    remains responsible for domain fields, business rules and scheduling.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{response_name} response must be a JSON object.")
    return value


async def check_relevance(client, module_title, image_data, semaphore):
    """Return Qwen Flash's parsed relevance output for one module image.

    This inexpensive, non-thinking request prevents unrelated images from
    reaching the two reasoning passes. Logic Manager validates the returned
    structure and decides whether the module is accepted.
    """
    content = await call_model(
        client,
        RELEVANCE_MODEL,
        create_image_messages(RELEVANCE_PROMPT, module_title, image_data),
        thinking=False,
        semaphore=semaphore,
        task_name=f"{module_title} relevance",
        json_mode=True,
    )
    return validate_json_object(parse_json_content(content), "Relevance")


async def interpret_assessments(client, module_title, image_data, semaphore):
    """Return a free-form evidence memo from the first reasoning pass.

    Keeping this pass outside the final schema gives Qwen room to understand
    multiplicity, hierarchy and uncertainty before normalization.
    """
    return await call_model(
        client,
        REASONING_MODEL,
        create_image_messages(INTERPRETATION_PROMPT, module_title, image_data),
        thinking=True,
        semaphore=semaphore,
        task_name=f"{module_title} interpretation",
    )


async def normalize_assessments(
    client,
    module_title,
    image_data,
    interpretation,
    semaphore,
):
    """Return structured assessment prototypes from the evidence memo.

    Qwen rechecks the image while converting the memo. Local functions later
    validate and expand these prototypes into the final scheduler payload.
    """
    content = await call_model(
        client,
        REASONING_MODEL,
        create_image_messages(
            NORMALIZATION_PROMPT,
            module_title,
            image_data,
            extra_text=interpretation,
        ),
        thinking=True,
        semaphore=semaphore,
        task_name=f"{module_title} normalization",
    )
    return validate_json_object(parse_json_content(content), "Normalization")


async def process_module(module, client, semaphore):
    """Parse one IO-validated module and return ``(module, error)``.

    Relevance runs first. Relevant modules continue through interpretation and
    normalization because each stage depends on the previous response. Parsed
    records are returned to Logic Manager for schema and ownership validation.
    """
    module_title = module["module_title"]
    LOGGER.info("AI Manager processing %s", module_title)

    try:
        stored_paths = module.get("stored_file_paths")
        if not isinstance(stored_paths, list) or not stored_paths:
            # Keep direct callers using the original single-image contract.
            stored_paths = [module["stored_file_path"]]
        image_data = [image_to_data_url(path) for path in stored_paths]
        relevance = await check_relevance(
            client,
            module_title,
            image_data,
            semaphore,
        )
        module_output = {
            "module_title": module_title,
            "credit": module["credit"],
            "ai_relevance": relevance,
            "ai_output": None,
        }
        if not isinstance(relevance, dict) or relevance.get("relevant") is not True:
            # The relevance pass is still AI output. Logic Manager owns the
            # schema check and accept/reject decision for this record.
            LOGGER.info("AI Manager completed relevance pass for %s", module_title)
            return module_output, None

        interpretation = await interpret_assessments(
            client,
            module_title,
            image_data,
            semaphore,
        )
        normalized = await normalize_assessments(
            client,
            module_title,
            image_data,
            interpretation,
            semaphore,
        )
        # Logic Manager turns these prototypes into concrete assessments.
        module_output["ai_output"] = normalized
        LOGGER.info("AI Manager completed %s", module_title)
        return module_output, None
    except Exception as error:
        # A failed module must not stop other concurrent module requests.
        failure = format_ai_error(module_title, error)
        LOGGER.warning("%s", failure)
        return None, failure


async def process_payload(payload, errors, client=None):
    """Process all modules and return the next payload with the same error list.

    Module tasks run concurrently but share a four-request semaphore. Request
    and JSON parsing failures append hard errors. Parsed records keep input
    order and continue to Logic Manager for acceptance checks. ``client`` may
    be injected by tests, otherwise this function creates and closes it.
    """
    if payload is None:
        return None, errors

    LOGGER.info(
        "AI Manager started with %d module(s)",
        len(payload["modules"]),
    )

    # Reuse an injected client in tests; own and close clients created here.
    owns_client = client is None
    if owns_client:
        try:
            client = create_client()
        except ValueError as error:
            errors.append(format_ai_error("configuration", error))
            return None, errors

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    module_tasks = [
        process_module(module, client, semaphore)
        for module in payload["modules"]
    ]

    try:
        # gather keeps results aligned with the original module order.
        results = await asyncio.gather(*module_tasks)
    finally:
        if owns_client:
            await client.close()

    # Keep only successful modules while flushing hard failures forward.
    processed_modules = []
    for processed_module, module_error in results:
        if module_error is not None:
            errors.append(module_error)
        else:
            processed_modules.append(processed_module)

    if not processed_modules:
        LOGGER.warning("AI Manager produced no usable modules")
        return None, errors

    LOGGER.info(
        "AI Manager prepared %d module(s)",
        len(processed_modules),
    )
    return {
        "module_count": len(processed_modules),
        "modules": processed_modules,
    }, errors


async def generate_recommendation(
    client,
    recommendation_type,
    project_payload,
    preferences,
    semaphore,
):
    """Ask Qwen for one structured checklist or trimester revision plan."""
    prompt = RECOMMENDATION_TYPES.get(recommendation_type)
    if prompt is None:
        raise ValueError("Unsupported recommendation type.")
    context = {
        "confirmed_project": project_payload,
        "study_preferences": preferences,
    }
    messages = [
        {
            "role": "user",
            "content": f"{prompt}\n\nINPUT DATA:\n{json.dumps(context)}",
        }
    ]
    content = await call_model(
        client,
        REASONING_MODEL,
        messages,
        thinking=True,
        semaphore=semaphore,
        task_name=f"{recommendation_type} recommendation",
    )
    return validate_json_object(parse_json_content(content), "Recommendation")


async def process_recommendation(
    project_payload,
    recommendation_type,
    preferences,
    errors,
    client=None,
):
    """Generate one recommendation while preserving the shared error list."""
    owns_client = client is None
    if owns_client:
        try:
            client = create_client()
        except ValueError as error:
            errors.append(format_ai_error("configuration", error))
            return None, errors

    try:
        recommendation = await generate_recommendation(
            client,
            recommendation_type,
            project_payload,
            preferences,
            asyncio.Semaphore(MAX_CONCURRENT_REQUESTS),
        )
        return recommendation, errors
    except Exception as error:
        failure = format_ai_error("recommendation", error)
        LOGGER.warning("%s", failure)
        errors.append(failure)
        return None, errors
    finally:
        if owns_client:
            await client.close()
