"""Concurrent AI processing for module assessment images.

Input:
    payload: The successful output from IO Manager.
    errors: The shared pipeline error list.

Output:
    A new payload containing extracted assessment components, plus the same
    shared error list for the next manager.

Each module runs independently. A failed or irrelevant module is removed while
the remaining modules continue. If every module fails, the payload is ``None``.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


RELEVANCE_MODEL = "qwen3.7-flash"
REASONING_MODEL = "qwen3.7-plus"
MAX_CONCURRENT_MODULES = 4
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

RELEVANCE_PROMPT = """Check whether the image contains assessment information
for the named module. Assessment information includes assignments, quizzes,
projects, examinations, weightages, deadlines, or teaching weeks.
Return JSON only in this exact shape:
{"relevant": true, "reason": "short explanation"}
"""

EXTRACTION_PROMPT = """Extract only assessment information visible in the image.
Do not invent missing values. Return JSON using this shape:
{
  "assessment_components": [
    {
      "name": "string",
      "type": "string or null",
      "weight_percent": "number or null",
      "schedule": "string or null",
      "parent_assessment": "string or null",
      "details": "string or null"
    }
  ],
  "notes": ["string"]
}
"""


def format_ai_error(module_title, error):
    """Give every AI error the same readable prefix."""
    return f"AI Manager error: {module_title}: {error}"


def create_client():
    """Create the shared Qwen API client from local environment settings."""
    load_dotenv()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY is not configured.")

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL),
    )


def image_to_data_url(file_path):
    """Encode one temporary image for the OpenAI-compatible Qwen API."""
    image_path = Path(file_path)
    mime_type, _ = mimetypes.guess_type(image_path.name)
    if mime_type is None or not mime_type.startswith("image/"):
        raise ValueError("The temporary file is not a supported image.")

    encoded_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded_image}"


def call_model(client, model, prompt, module_title, image_data, thinking):
    """Send one image request and decode its JSON response."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data},
                    },
                    {
                        "type": "text",
                        "text": f"Module: {module_title}",
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        extra_body={"enable_thinking": thinking},
    )
    return json.loads(response.choices[0].message.content)


def process_module(module, client):
    """Run the relevance and extraction stages for one module."""
    module_title = module["module_title"]

    try:
        image_data = image_to_data_url(module["stored_file_path"])
        relevance = call_model(
            client,
            RELEVANCE_MODEL,
            RELEVANCE_PROMPT,
            module_title,
            image_data,
            thinking=False,
        )
        if relevance.get("relevant") is not True:
            reason = relevance.get("reason", "Image is not assessment-related.")
            return None, format_ai_error(module_title, reason)

        context = call_model(
            client,
            REASONING_MODEL,
            EXTRACTION_PROMPT,
            module_title,
            image_data,
            thinking=True,
        )
        if not isinstance(context.get("assessment_components"), list):
            raise ValueError("Reasoning model returned an invalid response.")

        processed_module = {
            "module_title": module_title,
            "credit": module["credit"],
            "assessment_components": context["assessment_components"],
            "notes": context.get("notes", []),
        }
        return processed_module, None
    except Exception as error:
        # A failed module must not stop other concurrent module requests.
        return None, format_ai_error(module_title, error)


def process_payload(payload, errors):
    """Process modules concurrently and pass payload plus errors downstream."""
    if payload is None:
        return None, errors

    try:
        client = create_client()
    except ValueError as error:
        errors.append(format_ai_error("configuration", error))
        return None, errors

    modules = payload["modules"]
    worker_count = min(MAX_CONCURRENT_MODULES, len(modules))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = executor.map(
            lambda module: process_module(module, client),
            modules,
        )

    processed_modules = []
    for processed_module, module_error in results:
        if module_error is not None:
            errors.append(module_error)
        else:
            processed_modules.append(processed_module)

    if not processed_modules:
        return None, errors

    processed_payload = {
        "module_count": len(processed_modules),
        "modules": processed_modules,
    }
    return processed_payload, errors
