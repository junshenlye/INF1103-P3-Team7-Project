"""Extract structured assessment facts from module evidence."""

import asyncio
import base64
import inspect
import json
import logging
import os
from pathlib import Path
import time
import zipfile
from xml.etree import ElementTree

from openai import AsyncOpenAI, OpenAIError


LOGGER = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
PRECHECK_MODEL = "qwen3.7-flash"
CONTEXT_MODEL = "qwen3.7-plus"
REASONING_MODEL = "qwen3.7-plus"
MAX_DOCUMENT_CHARS = 12_000
DEFAULT_CONCURRENT_REQUESTS = 2
MAX_CONCURRENT_REQUESTS = 8
DEFAULT_MODEL_TIMEOUT_SECONDS = 45
DEFAULT_REQUEST_TIMEOUT_SECONDS = 240
DEFAULT_MODEL_RETRIES = 0

PRECHECK_SYSTEM_PROMPT = """Classify whether each supplied image contains readable
assessment scheduling evidence for the named module. Do not extract a schedule.
Return uncertain when relevance cannot be safely rejected."""

CONTEXT_SYSTEM_PROMPT = """Copy explicit academic assessment evidence into the
supplied JSON schema. Preserve source wording and source IDs. Do not infer missing
facts, reconcile conflicts, calculate totals, or create a schedule."""

REASONING_SYSTEM_PROMPT = """Reconcile supplied assessment evidence into the
supplied schedule schema.

Rules:
- Never invent dates, weeks, weights, recurrence, credits, or assessment status.
- Do not give study advice or calculate priority, pressure, or relative scores.
- Return partial facts when evidence is incomplete; use null for unknown fields.
- Preserve every visible item, but classify how it affects the module total:
  graded for an independently weighted assessment, aggregate for a parent summary,
  bonus for marks outside the normal total, ungraded for zero-mark practice or
  formative work, and uncertain when the evidence cannot decide.
- Do not count both an aggregate parent and its independently weighted children.
- Do not force the graded items to total 100%. Missing or unusual totals are valid
  incomplete evidence and must be explained for later user review.
- A clearly stated teaching week is sufficient scheduling evidence. Do not request
  a calendar date when an exact week is already known.
- A total weight and known week range are sufficient for recurring participation.
  Do not request a per-week weight breakdown unless the source says each occurrence
  is weighted separately.
- Keep feedback compact: one missing-information item per assessment and no more
  than three checklist items for the module. Do not repeat the same issue.
- Participation, attendance, tutorial engagement, and student engagement are
  participation assessments, not assignments.
- A percentage covering repeated participation is the total trimester weight.
  Use per_occurrence only when the source explicitly says each occurrence has
  that weight.
- Return JSON only. Use a hard error only when the request cannot be processed.
"""

# Multi-module extraction


def process(input_data, api_caller=None):
    """Synchronous entry point for the current Flask request path."""
    _require_no_running_loop("process", "process_async")
    process_coroutine = process_async(input_data, api_caller)
    result = asyncio.run(process_coroutine)
    return result


async def process_async(input_data, api_caller=None):
    """Extract modules as concurrent network tasks, preserving input order."""
    requested_modules = input_data.get("modules", [])
    repeating_schedule_data = input_data.get("repeating_schedule_data")
    if not requested_modules:
        return {
            "modules": [],
            "failures": [],
            "models_used": [],
            "model_runs": [],
        }

    module_count = len(requested_modules)
    request_limit = _concurrent_request_limit(module_count)
    LOGGER.info(
        "Extracting %d module(s) with up to %d concurrent request(s)",
        module_count,
        request_limit,
    )
    request_slots = asyncio.Semaphore(request_limit)
    module_tasks = []
    for module in requested_modules:
        extraction = _extract_module(
            module,
            repeating_schedule_data,
            api_caller,
            request_slots,
        )
        module_task = asyncio.create_task(extraction)
        module_tasks.append(module_task)

    raw_request_timeout = os.getenv(
        "AI_REQUEST_TIMEOUT_SECONDS",
        str(DEFAULT_REQUEST_TIMEOUT_SECONDS),
    )
    try:
        request_timeout = float(raw_request_timeout)
    except ValueError:
        request_timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS
    if request_timeout <= 0:
        request_timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS

    completed_tasks, pending_tasks = await asyncio.wait(
        module_tasks,
        timeout=request_timeout,
    )
    for pending_task in pending_tasks:
        pending_task.cancel()
    if pending_tasks:
        await asyncio.gather(*pending_tasks, return_exceptions=True)

    results = []
    for module_index, module_task in enumerate(module_tasks):
        if module_task in completed_tasks:
            completed_module = requested_modules[module_index]
            module_name = completed_module["module_name"]
            try:
                module_result = module_task.result()
            except Exception:
                LOGGER.exception(
                    "AI module pipeline stopped unexpectedly module=%s",
                    module_name,
                )
                module_result = {
                    "module": {
                        "module_name": module_name,
                        "credit_units": completed_module.get("credit_units"),
                        "assessments": [],
                        "comments": [],
                    },
                    "failure": {
                        "module_name": module_name,
                        "stage": "pipeline",
                        "category": "system_failure",
                        "message": "The AI service could not process this module.",
                    },
                    "models_used": [],
                    "model_runs": [],
                }
            results.append(module_result)
            continue

        timed_out_module = requested_modules[module_index]
        module_name = timed_out_module["module_name"]
        timeout_result = {
            "module": {
                "module_name": module_name,
                "credit_units": timed_out_module.get("credit_units"),
                "assessments": [],
                "comments": [],
            },
            "failure": {
                "module_name": module_name,
                "stage": "pipeline",
                "category": "system_failure",
                "message": "The module exceeded the AI request time limit.",
            },
            "models_used": [],
            "model_runs": [
                {
                    "module_name": module_name,
                    "stage": "pipeline",
                    "model": None,
                    "status": "timed_out",
                    "duration_ms": round(request_timeout * 1000, 2),
                }
            ],
        }
        results.append(timeout_result)

    modules = []
    failures = []
    models_used = []
    model_runs = []
    for result in results:
        failure = result.get("failure")
        if failure is None:
            modules.append(result["module"])
        else:
            failures.append(failure)
        result_models = result.get("models_used", [])
        models_used.extend(result_models)
        result_runs = result.get("model_runs", [])
        model_runs.extend(result_runs)
    return {
        "modules": modules,
        "failures": failures,
        "models_used": _unique_text(models_used),
        "model_runs": model_runs,
    }


# Per-module extraction and evidence


def _concurrent_request_limit(module_count):
    default_limit = str(DEFAULT_CONCURRENT_REQUESTS)
    configured_value = os.getenv(
        "AI_MAX_CONCURRENT_REQUESTS",
        default_limit,
    )
    try:
        configured = int(configured_value)
    except ValueError:
        configured = DEFAULT_CONCURRENT_REQUESTS
    upper_limit = min(module_count, configured, MAX_CONCURRENT_REQUESTS)
    return max(1, upper_limit)


async def _extract_module(
    module,
    repeating_schedule_data,
    api_caller,
    request_slots,
):
    """Run precheck, context extraction, and reasoning for one module."""
    module_name = module["module_name"]
    images = module["images"]
    documents = module["documents"]
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if api_caller is None and not api_key:
        return {
            "module": {
                "module_name": module_name,
                "credit_units": module.get("credit_units"),
                "assessments": [],
                "comments": [],
            },
            "failure": {
                "module_name": module_name,
                "stage": "configuration",
                "category": "system_failure",
                "message": "The AI service is not configured.",
            },
            "models_used": [],
            "model_runs": [],
        }

    models_used = []
    model_runs = []
    current_stage = "precheck"
    current_model = None
    stage_started_at = None
    stage_in_progress = False

    try:
        accepted_images = images
        precheck_result = None
        if images:
            precheck_model = os.getenv("AI_PRECHECK_MODEL", PRECHECK_MODEL)
            precheck_prompt = _format_precheck_prompt(module, images)
            current_model = precheck_model
            async with request_slots:
                stage_started_at = time.perf_counter()
                stage_in_progress = True
                precheck_result = await _run_model_stage(
                    stage="precheck",
                    prompt=precheck_prompt,
                    images=images,
                    api_key=api_key,
                    model=precheck_model,
                    system_prompt=PRECHECK_SYSTEM_PROMPT,
                    tool_name="submit_image_precheck",
                    tool_description="Classify the relevance of each supplied image.",
                    schema=_precheck_schema(),
                    max_tokens=4_096,
                    reasoning_effort="none",
                    api_caller=api_caller,
                )
            stage_in_progress = False
            stage_finished_at = time.perf_counter()
            stage_duration_ms = round(
                (stage_finished_at - stage_started_at) * 1000,
                2,
            )
            model_runs.append(
                {
                    "module_name": module_name,
                    "stage": current_stage,
                    "model": current_model,
                    "status": "completed",
                    "duration_ms": stage_duration_ms,
                }
            )
            LOGGER.info(
                "AI stage completed module=%s stage=%s model=%s duration_ms=%s",
                module_name,
                current_stage,
                current_model,
                stage_duration_ms,
            )
            models_used.append(precheck_model)
            accepted_images = _accepted_images(
                images,
                precheck_result,
            )

            if not accepted_images:
                raw_comments = precheck_result.get("comments")
                comments = _text_list(raw_comments)
                if not comments:
                    comments = ["The supplied images are not relevant to this module schedule."]
                return {
                    "module": {
                        "module_name": module_name,
                        "credit_units": module.get("credit_units"),
                        "assessments": [],
                        "comments": [],
                    },
                    "failure": {
                        "module_name": module_name,
                        "stage": "precheck",
                        "category": "rejected_input",
                        "message": comments[0],
                    },
                    "models_used": models_used,
                    "model_runs": model_runs,
                }

        current_stage = "context"
        document_text, document_comments = _read_module_documents(documents)
        context_model = os.getenv("AI_CONTEXT_MODEL", CONTEXT_MODEL)
        context_prompt = _format_context_prompt(
            module,
            accepted_images,
            document_text,
        )
        current_model = context_model
        async with request_slots:
            stage_started_at = time.perf_counter()
            stage_in_progress = True
            context_result = await _run_model_stage(
                stage="context",
                prompt=context_prompt,
                images=accepted_images,
                api_key=api_key,
                model=context_model,
                system_prompt=CONTEXT_SYSTEM_PROMPT,
                tool_name="submit_assessment_evidence",
                tool_description="Submit explicit assessment evidence from the sources.",
                schema=_context_schema(),
                max_tokens=4_096,
                reasoning_effort="none",
                api_caller=api_caller,
            )
        stage_in_progress = False
        stage_finished_at = time.perf_counter()
        stage_duration_ms = round(
            (stage_finished_at - stage_started_at) * 1000,
            2,
        )
        model_runs.append(
            {
                "module_name": module_name,
                "stage": current_stage,
                "model": current_model,
                "status": "completed",
                "duration_ms": stage_duration_ms,
            }
        )
        LOGGER.info(
            "AI stage completed module=%s stage=%s model=%s duration_ms=%s",
            module_name,
            current_stage,
            current_model,
            stage_duration_ms,
        )
        models_used.append(context_model)

        current_stage = "reasoning"
        reasoning_model = os.getenv("AI_REASONING_MODEL", REASONING_MODEL)
        reasoning_prompt = _format_reasoning_prompt(
            module,
            context_result,
            repeating_schedule_data,
        )
        current_model = reasoning_model
        async with request_slots:
            stage_started_at = time.perf_counter()
            stage_in_progress = True
            reasoning_result = await _run_model_stage(
                stage="reasoning",
                prompt=reasoning_prompt,
                images=[],
                api_key=api_key,
                model=reasoning_model,
                system_prompt=REASONING_SYSTEM_PROMPT,
                tool_name="submit_module_facts",
                tool_description="Submit the reconciled module assessment schedule.",
                schema=_pacing_schema(),
                max_tokens=4_096,
                reasoning_effort="none",
                api_caller=api_caller,
            )
        stage_in_progress = False
        stage_finished_at = time.perf_counter()
        stage_duration_ms = round(
            (stage_finished_at - stage_started_at) * 1000,
            2,
        )
        model_runs.append(
            {
                "module_name": module_name,
                "stage": current_stage,
                "model": current_model,
                "status": "completed",
                "duration_ms": stage_duration_ms,
            }
        )
        LOGGER.info(
            "AI stage completed module=%s stage=%s model=%s duration_ms=%s",
            module_name,
            current_stage,
            current_model,
            stage_duration_ms,
        )
        models_used.append(reasoning_model)

        normalized_module = _normalize_module_result(reasoning_result, module)
        module_comments = normalized_module["comments"]
        combined_comments = module_comments + document_comments
        normalized_module["comments"] = _unique_text(combined_comments)
        normalized_module["pipeline_context"] = {
            "precheck": precheck_result,
            "evidence": context_result,
        }
        return {
            "module": normalized_module,
            "failure": None,
            "models_used": models_used,
            "model_runs": model_runs,
        }
    except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
        safe_error = _safe_error(error)
        failure_type = "model_error"
        failure_message = "The AI service could not process this module."
        lower_error = safe_error.lower()
        if "timed out" in lower_error:
            failure_type = "model_timeout"
            failure_message = f"{current_model} timed out during {current_stage}."
        elif "http 429" in lower_error or "rate limit" in lower_error:
            failure_type = "rate_limit"
            failure_message = "The AI service rate limit was reached."
        elif "quota" in lower_error or "balance" in lower_error or "credit" in lower_error:
            failure_type = "quota"
            failure_message = "The AI service quota or credit is unavailable."
        elif "valid json" in lower_error or "model response" in lower_error:
            failure_type = "invalid_model_response"
            failure_message = "The AI model returned an invalid response."
        if stage_in_progress and stage_started_at is not None:
            stage_finished_at = time.perf_counter()
            stage_duration_ms = round(
                (stage_finished_at - stage_started_at) * 1000,
                2,
            )
            model_runs.append(
                {
                    "module_name": module_name,
                    "stage": current_stage,
                    "model": current_model,
                    "status": "failed",
                    "duration_ms": stage_duration_ms,
                }
            )
        LOGGER.warning(
            "AI stage failed module=%s stage=%s model=%s error=%s",
            module_name,
            current_stage,
            current_model,
            safe_error,
        )
        return {
            "module": {
                "module_name": module_name,
                "credit_units": module.get("credit_units"),
                "assessments": [],
                "comments": [],
            },
            "failure": {
                "module_name": module_name,
                "stage": current_stage,
                "category": "system_failure",
                "failure_type": failure_type,
                "message": failure_message,
            },
            "models_used": models_used,
            "model_runs": model_runs,
        }


async def _run_model_stage(
    *,
    stage,
    prompt,
    images,
    api_key,
    model,
    system_prompt,
    tool_name,
    tool_description,
    schema,
    max_tokens,
    reasoning_effort,
    api_caller,
):
    if api_caller is not None:
        reply = await _invoke_caller(
            api_caller,
            stage=stage,
            prompt=prompt,
            images=images,
            model=model,
            schema=schema,
            reasoning_effort=reasoning_effort,
        )
    else:
        reply = await _call_model(
            prompt=prompt,
            images=images,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            tool_name=tool_name,
            tool_description=tool_description,
            schema=schema,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

    parsed_reply = _parse_model_reply(
        reply,
        tool_name=tool_name,
    )
    return parsed_reply


def _format_precheck_prompt(module, images):
    source_lines = []
    for image in images:
        source_id = image["source_id"]
        image_path = image["path"]
        file_name = Path(image_path).name
        source_lines.append(f"{source_id}: {file_name}")

    sources = "\n".join(source_lines)
    return (
        f"Expected module: {module['module_name']}\n"
        "Classify each image as relevant, irrelevant, or uncertain. An image is "
        "relevant when it contains readable assessment names, weights, deadlines, "
        "weeks, recurrence, or another fact needed for a module schedule.\n"
        f"Sources:\n{sources}"
    )


def _accepted_images(images, precheck_result):
    image_results = precheck_result.get("images")
    if not isinstance(image_results, list):
        raise ValueError("The precheck result did not contain an images list.")
    if len(image_results) != len(images):
        raise ValueError("The precheck did not classify every supplied image.")

    images_by_source_id = {}
    for image in images:
        source_id = image["source_id"]
        images_by_source_id[source_id] = image

    accepted_images = []
    seen_source_ids = set()
    for image_result in image_results:
        if not isinstance(image_result, dict):
            raise ValueError("The precheck returned an invalid image result.")

        source_id = image_result.get("source_id")
        status = image_result.get("status")
        if status not in {"relevant", "irrelevant", "uncertain"}:
            raise ValueError("The precheck returned an invalid relevance status.")
        if source_id not in images_by_source_id:
            raise ValueError("The precheck returned an invalid source ID.")
        if source_id in seen_source_ids:
            raise ValueError("The precheck returned a duplicate source ID.")
        seen_source_ids.add(source_id)

        if status == "irrelevant":
            continue

        accepted_image = images_by_source_id[source_id]
        accepted_images.append(accepted_image)

    return accepted_images


def _read_module_documents(documents):
    document_parts = []
    comments = []
    remaining_chars = MAX_DOCUMENT_CHARS
    for document in documents:
        file_path = document["path"]
        document_type = document["document_type"]
        path = Path(file_path)
        try:
            text = _read_document_text(path, document_type)
            if not text.strip():
                comments.append(f"{path.name} did not contain readable text.")
                continue
            excerpt = text[:remaining_chars]
            if excerpt:
                document_parts.append(f"--- {path.name} ---\n{excerpt}")
                remaining_chars -= len(excerpt)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
            safe_error = _safe_error(error)
            LOGGER.warning(
                "Could not read uploaded document %s: %s",
                path.name,
                safe_error,
            )
            comments.append(f"{path.name} could not be read as assessment evidence.")

    document_text = "\n".join(document_parts)
    return document_text, comments


def _format_context_prompt(module, images, document_text):
    image_sources = []
    for image in images:
        source_id = image["source_id"]
        image_path = image["path"]
        file_name = Path(image_path).name
        image_sources.append(f"{source_id}: {file_name}")

    image_source_text = "\n".join(image_sources)
    return (
        f"Module: {module['module_name']}\n"
        f"Credit units: {module.get('credit_units')}\n"
        f"User context: {module.get('additional_context') or 'None'}\n"
        "Extract only explicit assessment evidence. Give each image evidence item "
        "the source ID listed below. Preserve contradictions as "
        "separate evidence items. Do not produce a final schedule.\n"
        f"Image sources:\n{image_source_text or 'None'}\n"
        f"Document text:\n{document_text or 'None'}"
    )


def _format_reasoning_prompt(module, context_result, repeating_schedule_data):
    evidence_text = json.dumps(context_result, separators=(",", ":"))
    retry_text = "None"
    if repeating_schedule_data is not None:
        retry_text = json.dumps(repeating_schedule_data, separators=(",", ":"))

    return (
        f"Module: {module['module_name']}\n"
        f"Credit units: {module.get('credit_units')}\n"
        f"User context: {module.get('additional_context') or 'None'}\n"
        f"Extracted evidence: {evidence_text}\n"
        f"Existing retry schedule: {retry_text}\n"
        "Reconcile duplicates and conflicts, interpret recurrence and shared weights, "
        "and return the most defensible schedule. Use null rather than guessing."
    )


def _read_document_text(path, document_type):
    if document_type == "text":
        return path.read_text(encoding="utf-8", errors="replace")
    if document_type == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError("PDF support is unavailable") from error
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if document_type == "docx":
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(document_xml)
        return "\n".join(text for text in root.itertext() if text.strip())
    raise ValueError("Unsupported document type")


# Model request and response contract


async def _call_model(
    *,
    prompt,
    images,
    api_key,
    model,
    system_prompt,
    tool_name,
    tool_description,
    schema,
    max_tokens,
    reasoning_effort,
):
    user_content = _build_user_content(prompt, images)
    tool_choice = "auto"
    if reasoning_effort == "none":
        tool_choice = {
            "type": "function",
            "function": {"name": tool_name},
        }

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": schema,
                },
            }
        ],
        "tool_choice": tool_choice,
    }

    raw_timeout = os.getenv(
        "AI_MODEL_TIMEOUT_SECONDS",
        str(DEFAULT_MODEL_TIMEOUT_SECONDS),
    )
    try:
        model_timeout = float(raw_timeout)
    except ValueError:
        model_timeout = DEFAULT_MODEL_TIMEOUT_SECONDS
    if model_timeout <= 0:
        model_timeout = DEFAULT_MODEL_TIMEOUT_SECONDS

    raw_retries = os.getenv(
        "AI_MODEL_RETRIES",
        str(DEFAULT_MODEL_RETRIES),
    )
    try:
        model_retries = int(raw_retries)
    except ValueError:
        model_retries = DEFAULT_MODEL_RETRIES
    model_retries = max(0, min(model_retries, 2))

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL).strip()
        or DASHSCOPE_BASE_URL,
        timeout=model_timeout,
        max_retries=model_retries,
    )
    try:
        completion = await client.chat.completions.create(**request)
    except OpenAIError as error:
        status = getattr(error, "status_code", None)
        status_text = f" (HTTP {status})" if status else ""
        raise ConnectionError(
            f"Alibaba Model Studio request failed{status_text}: {error}"
        ) from error
    finally:
        await client.close()
    if not completion.choices:
        raise ValueError("Alibaba Model Studio returned no model message.")

    usage = getattr(completion, "usage", None)
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        LOGGER.info(
            "%s token usage: input=%s output=%s total=%s",
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
    return completion.choices[0].message.model_dump(exclude_none=True)


def _build_user_content(prompt, images):
    content = [{"type": "text", "text": prompt}]
    for image in images:
        image_path = image["path"]
        media_type = image["media_type"]
        path = Path(image_path)
        image_bytes = path.read_bytes()
        encoded_bytes = base64.b64encode(image_bytes)
        encoded = encoded_bytes.decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{media_type};base64,"
                        f"{encoded}"
                    )
                },
            }
        )
    return content


def _parse_model_reply(reply, *, tool_name):
    if isinstance(reply, dict) and "tool_calls" not in reply and "content" not in reply:
        return reply
    if not isinstance(reply, dict):
        reply_text = str(reply)
        return _parse_json_object(reply_text)
    raw_tool_calls = reply.get("tool_calls")
    tool_calls = _list_or_empty(raw_tool_calls)
    for tool_call in tool_calls:
        function = (
            tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        )
        if function.get("name") == tool_name:
            arguments = function.get("arguments", "")
            return _parse_json_object(arguments)
    content = reply.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _parse_json_object(content)


def _parse_json_object(text):
    if not isinstance(text, str):
        raise ValueError("The model response was not text.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("The model did not return valid JSON.") from error
    if isinstance(value, dict):
        return value
    raise ValueError("The model JSON response was not an object.")


def _strict_object(properties, *, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
    }


def _string_list(max_items=None):
    schema = {"type": "array", "items": {"type": "string"}}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _precheck_schema():
    image_result = _strict_object(
        {
            "source_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["relevant", "irrelevant", "uncertain"],
            },
            "comment": {"type": "string"},
        }
    )
    return _strict_object(
        {
            "images": {"type": "array", "items": image_result},
            "comments": _string_list(3),
        }
    )


def _context_schema():
    evidence_item = _strict_object(
        {
            "source_id": {"type": "string"},
            "evidence_text": {"type": "string"},
            "assessment_hint": {"type": ["string", "null"]},
            "weightage_seen": {"type": ["number", "null"]},
            "timing_seen": {"type": ["string", "null"]},
            "recurrence_seen": {"type": ["string", "null"]},
        }
    )
    return _strict_object(
        {
            "evidence": {"type": "array", "items": evidence_item},
            "unclear_evidence": _string_list(5),
            "comments": _string_list(3),
        }
    )


def _pacing_schema():
    nullable_number = {"type": ["number", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    nullable_string = {"type": ["string", "null"]}
    recurrence = _strict_object(
        {
            "frequency": nullable_string,
            "weeks": {"type": "array", "items": {"type": "integer"}},
            "start_week": nullable_integer,
            "end_week": nullable_integer,
            "every_n_weeks": nullable_integer,
        }
    )
    recurrence["type"] = ["object", "null"]
    assessment = _strict_object(
        {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "classification": {
                "type": "string",
                "enum": ["graded", "aggregate", "bonus", "ungraded", "uncertain"],
            },
            "weightage_percent": nullable_number,
            "weightage_scope": {
                "type": "string",
                "enum": ["total", "per_occurrence", "unknown"],
            },
            "due_date": nullable_string,
            "due_week": nullable_integer,
            "recurring": {"type": "boolean"},
            "recurrence": recurrence,
            "spans_multiple_weeks": {"type": "boolean"},
            "start_week": nullable_integer,
            "end_week": nullable_integer,
            "confidence": nullable_number,
            "comments": _string_list(1),
            "missing_information": _string_list(1),
            "assumptions": _string_list(1),
        }
    )
    return _strict_object(
        {
            "assessments": {"type": "array", "items": assessment},
            "comments": _string_list(3),
        }
    )


# AI result normalization


def _normalize_module_result(reply, supplied_module):
    if not isinstance(reply, dict):
        raise ValueError("The model result was not an object.")

    raw_assessments = reply.get("assessments", [])
    raw_comments = reply.get("comments")
    comments = _text_list(raw_comments)
    if not isinstance(raw_assessments, list):
        raise ValueError("The model result did not contain an assessment list.")

    assessments = []
    for index, raw in enumerate(raw_assessments, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Assessment {index} was not an object.")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError(f"Assessment {index} has no title.")

        classification = raw.get("classification")
        allowed_classifications = {
            "graded",
            "aggregate",
            "bonus",
            "ungraded",
            "uncertain",
        }
        if classification not in allowed_classifications:
            raise ValueError(f"Assessment {index} has an invalid classification.")

        raw_weight = raw.get("weightage_percent")
        weight = _number_or_none(raw_weight)
        raw_item_comments = raw.get("comments")
        item_comments = _text_list(raw_item_comments)
        raw_missing_information = raw.get("missing_information")
        missing_information = _text_list(raw_missing_information)
        missing = _unique_text(missing_information)
        if weight is not None and not 0 <= weight <= 100:
            raise ValueError(f"Assessment {index} has an invalid weightage.")

        raw_due_week = raw.get("due_week")
        due_week = _week_or_none(raw_due_week)

        raw_recurrence = raw.get("recurrence")
        recurrence = _normalize_recurrence(raw_recurrence)
        recurring = raw.get("recurring")
        if not isinstance(recurring, bool):
            raise ValueError(f"Assessment {index} has invalid recurrence status.")

        spans_multiple_weeks = raw.get("spans_multiple_weeks")
        if not isinstance(spans_multiple_weeks, bool):
            raise ValueError(f"Assessment {index} has invalid duration status.")

        raw_confidence = raw.get("confidence")
        confidence = _number_or_none(raw_confidence)
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError(f"Assessment {index} has invalid confidence.")
        raw_scope = str(raw.get("weightage_scope") or "").strip().lower()
        allowed_scopes = {"total", "per_occurrence", "unknown"}
        if raw_scope not in allowed_scopes:
            raise ValueError(f"Assessment {index} has an invalid weightage scope.")

        raw_start_week = raw.get("start_week")
        start_week = _week_or_none(raw_start_week)
        raw_end_week = raw.get("end_week")
        end_week = _week_or_none(raw_end_week)
        raw_assumptions = raw.get("assumptions")
        assumptions = _text_list(raw_assumptions)
        unique_assumptions = _unique_text(assumptions)
        assessment_type = str(raw.get("type") or "assessment")
        assessment_type = assessment_type.strip().lower()
        raw_due_date = raw.get("due_date")
        due_date = str(raw_due_date or "").strip() or None

        assessment = {
            "name": name,
            "type": assessment_type,
            "classification": classification,
            "weightage_percent": weight,
            "weightage_scope": raw_scope,
            "due_date": due_date,
            "due_week": due_week,
            "recurring": recurring,
            "recurrence": recurrence,
            "spans_multiple_weeks": spans_multiple_weeks,
            "start_week": start_week,
            "end_week": end_week,
            "confidence": confidence,
            "comments": _unique_text(item_comments),
            "missing_information": missing,
            "assumptions": unique_assumptions[:1],
        }
        assessments.append(assessment)

    return {
        "module_name": supplied_module["module_name"],
        "credit_units": supplied_module.get("credit_units"),
        "assessments": assessments,
        "comments": _unique_text(comments),
    }


def _normalize_recurrence(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Assessment recurrence was not an object or null.")
    raw_weeks = value.get("weeks")
    if not isinstance(raw_weeks, list):
        raise ValueError("Assessment recurrence weeks were not a list.")

    weeks = []
    for raw_week in raw_weeks:
        week = _week_or_none(raw_week)
        weeks.append(week)

    raw_start_week = value.get("start_week")
    start_week = _week_or_none(raw_start_week)
    raw_end_week = value.get("end_week")
    end_week = _week_or_none(raw_end_week)
    raw_interval = value.get("every_n_weeks")
    every_n_weeks = _week_or_none(raw_interval)

    return {
        "frequency": str(value.get("frequency") or "").strip() or None,
        "weeks": weeks,
        "start_week": start_week,
        "end_week": end_week,
        "every_n_weeks": every_n_weeks,
    }


# Small shared helpers


async def _invoke_caller(caller, **arguments):
    """Accept native async callers while retaining simple synchronous test fakes."""
    result = caller(**arguments)
    return await result if inspect.isawaitable(result) else result


def _require_no_running_loop(sync_name, async_name):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"{sync_name} cannot run inside an active event loop; await {async_name} instead."
    )


def _list_or_empty(value):
    return value if isinstance(value, list) else []


def _text_list(value):
    if not isinstance(value, list):
        raise ValueError("Expected a list of text values.")
    text_items = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Expected every list item to be text.")
        cleaned_item = item.strip()
        if cleaned_item:
            text_items.append(cleaned_item)
    return text_items


def _unique_text(items):
    unique_items = []
    for item in items:
        cleaned_item = str(item).strip()
        if cleaned_item and cleaned_item not in unique_items:
            unique_items.append(cleaned_item)
    return unique_items


def _number_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a number or null.")
    return float(value)


def _week_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer week or null.")
    return value


def _safe_error(error):
    if isinstance(error, ConnectionError):
        return str(error)
    if isinstance(error, OSError):
        return "An uploaded file could not be read."
    return str(error) or "The model response could not be processed."
