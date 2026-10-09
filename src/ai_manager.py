"""Asynchronous assessment interpretation and normalization.

Each relevant module uses two Qwen reasoning passes. The first builds a
source-faithful evidence memo without the final schema. The second converts
that memo into small assessment prototypes. Local procedural code then expands
repeated assessments, assigns stable IDs, and preserves soft uncertainties as
follow-ups for Logic Manager.
"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import time

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .ai_prompts import (
    INTERPRETATION_PROMPT,
    NORMALIZATION_PROMPT,
    RELEVANCE_PROMPT,
)


RELEVANCE_MODEL = "qwen3.7-flash"
REASONING_MODEL = "qwen3.7-plus"
MAX_CONCURRENT_REQUESTS = 4
LOGGER = logging.getLogger(__name__)

# Values below form the stable part of the payload contract. Model wording is
# cleaned against these values before it reaches Logic Manager.
SCHEDULE_KINDS = {"week", "week_range", "date", "recurring", "unknown"}
WEIGHT_SCOPES = {"module", "part", "group", "unknown"}
RECORD_ROLES = {"assessment", "group"}
COVERAGE_STATUSES = {"appears_complete", "partial", "unclear"}
ASSESSMENT_TYPES = {
    "assignment",
    "quiz",
    "tutorial",
    "project",
    "test",
    "exam",
    "presentation",
    "essay",
    "participation",
    "other",
}
TYPE_ALIASES = {
    "assignments": "assignment",
    "quizzes": "quiz",
    "tutorials": "tutorial",
    "projects": "project",
    "tests": "test",
    "exams": "exam",
    "final_exam": "exam",
    "final_written_exam": "exam",
    "competency_test": "test",
    "presentations": "presentation",
    "oral_presentation": "presentation",
    "essays": "essay",
}
FOLLOW_UP_FIELDS = {
    "assessment_types",
    "count",
    "graded_status",
    "parent_assessment_id",
    "schedule",
    "source_coverage",
    "type",
    "weight_percent",
    "group_weight_percent",
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
    """Build the single multimodal message sent to Qwen.

    The message always contains the prompt, module title and image. The
    normalization pass also supplies the earlier interpretation memo.
    """
    text = f"{prompt}\n\nMODULE: {module_title}"
    if extra_text is not None:
        text += f"\n\nINTERPRETATION MEMO:\n{extra_text}"

    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_data}},
            ],
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


async def check_relevance(client, module_title, image_data, semaphore):
    """Return Qwen Flash's relevance decision for one module image.

    This inexpensive, non-thinking request prevents unrelated images from
    reaching the two reasoning passes.
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
    relevance = parse_json_content(content)
    if not isinstance(relevance, dict):
        raise ValueError("Relevance model returned an invalid response.")
    return relevance


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
    normalized = parse_json_content(content)
    if not isinstance(normalized, dict):
        raise ValueError("Normalization model returned an invalid response.")
    return normalized


def append_follow_up(follow_ups, assessment, field, message):
    """Append one soft comment unless its assessment and field already exist.

    Follow-ups remain module metadata; they never enter the hard-error list.
    """
    target = assessment.casefold() if isinstance(assessment, str) else None
    for follow_up in follow_ups:
        existing = follow_up.get("assessment")
        existing_target = existing.casefold() if isinstance(existing, str) else None
        if existing_target == target and follow_up.get("field") == field:
            return

    follow_ups.append(
        {
            "assessment": assessment,
            "field": field,
            "message": message,
        }
    )


def normalize_weight(value, assessment, field, follow_ups):
    """Return a numeric weight or ``None`` when the value is not usable.

    A malformed value is retained as a soft follow-up so the module can still
    continue through the pipeline.
    """
    if value is None or type(value) in (int, float):
        return value

    append_follow_up(
        follow_ups,
        assessment,
        field,
        "The source weight could not be represented as a number.",
    )
    return None


def normalize_schedule(schedule, assessment, follow_ups, required=True):
    """Return a schedule dictionary with the fields Logic Manager expects.

    Invalid combinations become ``kind: unknown``. When ``required`` is false,
    an unknown schedule is allowed because structural group records need no
    calendar entry.
    """
    if not isinstance(schedule, dict):
        schedule = {}

    normalized = {
        "kind": schedule.get("kind", "unknown"),
        "week": schedule.get("week"),
        "start_week": schedule.get("start_week"),
        "end_week": schedule.get("end_week"),
        "date": schedule.get("date"),
        "day": schedule.get("day"),
        "raw": schedule.get("raw"),
    }
    if normalized["kind"] not in SCHEDULE_KINDS:
        normalized["kind"] = "unknown"

    kind = normalized["kind"]
    if kind == "week" and type(normalized["week"]) is not int:
        normalized["kind"] = "unknown"
    elif kind == "week_range" and (
        type(normalized["start_week"]) is not int
        or type(normalized["end_week"]) is not int
    ):
        normalized["kind"] = "unknown"
    elif kind == "date" and not isinstance(normalized["date"], str):
        normalized["kind"] = "unknown"
    elif kind == "recurring" and not (
        isinstance(normalized["day"], str)
        or isinstance(normalized["raw"], str)
    ):
        normalized["kind"] = "unknown"

    if normalized["kind"] == "unknown" and required:
        append_follow_up(
            follow_ups,
            assessment,
            "schedule",
            "No complete schedulable week, date, or recurrence was stated.",
        )
    return normalized


def make_assessment_id(module_title, assessment_type, position):
    """Return a stable ID from module, type and one-based group position.

    IDs are created locally so model wording cannot introduce random or unsafe
    identifiers into frontend relationships.
    """
    module_code = re.sub(r"[^A-Z0-9]+", "-", module_title.upper()).strip("-")
    type_code = re.sub(
        r"[^A-Z0-9]+", "-", assessment_type.upper()
    ).strip("-")
    return f"{module_code}-{type_code or 'OTHER'}-{position:02d}"


def prepare_follow_ups(raw_follow_ups):
    """Return deduplicated model follow-ups that match the metadata contract.

    Unknown fields, malformed entries and messages without text are ignored.
    """
    if not isinstance(raw_follow_ups, list):
        return []

    follow_ups = []
    for follow_up in raw_follow_ups:
        if not isinstance(follow_up, dict):
            continue
        field = follow_up.get("field")
        message = follow_up.get("message")
        assessment = follow_up.get("assessment")
        if (
            field not in FOLLOW_UP_FIELDS
            or not isinstance(message, str)
        ):
            continue
        if not isinstance(assessment, str):
            assessment = None
        append_follow_up(follow_ups, assessment, field, message)
    return follow_ups


def prepare_group_specs(raw_groups, follow_ups):
    """Return validated intermediate groups keyed by canonical assessment type.

    Groups of the same type are merged in source order. Conflicting group
    weights are cleared and recorded as a soft follow-up instead of guessed.
    """
    if not isinstance(raw_groups, list):
        raise ValueError("Normalization response has no assessment type list.")

    group_order = []
    group_specs = {}
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            raise ValueError("Normalization response contains an invalid group.")
        raw_type = raw_group.get("type")
        prototypes = raw_group.get("assessments")
        if not isinstance(raw_type, str) or not isinstance(prototypes, list):
            raise ValueError("Normalization response contains an invalid group.")

        assessment_type = re.sub(
            r"[^a-z0-9]+", "_", raw_type.lower()
        ).strip("_") or "other"
        assessment_type = TYPE_ALIASES.get(assessment_type, assessment_type)
        if assessment_type not in ASSESSMENT_TYPES:
            append_follow_up(
                follow_ups,
                raw_type,
                "type",
                "The assessment type was unclear and was classified as other.",
            )
            assessment_type = "other"
        group_weight = normalize_weight(
            raw_group.get("group_weight_percent"),
            assessment_type,
            "group_weight_percent",
            follow_ups,
        )
        group_scope = raw_group.get("group_weight_scope", "unknown")
        if group_scope not in WEIGHT_SCOPES:
            group_scope = "unknown"
        group_scope_name = raw_group.get("group_weight_scope_name")
        if not isinstance(group_scope_name, str):
            group_scope_name = None

        if assessment_type not in group_specs:
            group_order.append(assessment_type)
            group_specs[assessment_type] = {
                "type": assessment_type,
                "group_weight_percent": group_weight,
                "group_weight_scope": group_scope,
                "group_weight_scope_name": group_scope_name,
                "prototypes": list(prototypes),
            }
            continue

        existing = group_specs[assessment_type]
        existing["prototypes"].extend(prototypes)
        if existing["group_weight_percent"] != group_weight:
            existing["group_weight_percent"] = None
            existing["group_weight_scope"] = "unknown"
            existing["group_weight_scope_name"] = None
            append_follow_up(
                follow_ups,
                assessment_type,
                "group_weight_percent",
                "Multiple conflicting group weights were returned for this type.",
            )

    return [group_specs[assessment_type] for assessment_type in group_order]


def build_module_output(module_title, credit, normalized):
    """Convert normalized prototypes into one schedule-ready module.

    This local pass expands repeated work, protects group weights, creates IDs,
    links parent records and attaches soft comments. Invalid core structures
    raise ``ValueError`` so only that module is removed.
    """
    # Step 1: normalize module-level source coverage and factual notes.
    coverage = normalized.get("source_coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    coverage_status = coverage.get("status", "unclear")
    if coverage_status not in COVERAGE_STATUSES:
        coverage_status = "unclear"
    coverage_comment = coverage.get("comment")
    if not isinstance(coverage_comment, str):
        coverage_comment = None
    source_coverage = {
        "status": coverage_status,
        "comment": coverage_comment,
    }

    notes = normalized.get("notes")
    if not isinstance(notes, list):
        notes = []
    notes = [note for note in notes if isinstance(note, str)]
    follow_ups = prepare_follow_ups(normalized.get("follow_ups"))
    group_specs = prepare_group_specs(
        normalized.get("assessment_types"),
        follow_ups,
    )

    # Step 2: expand each model prototype into concrete assessment records.
    assessment_types = []
    name_lookup = {}
    pending_parents = []
    for group_spec in group_specs:
        assessment_type = group_spec["type"]
        assessments = []
        position = 0
        for prototype in group_spec["prototypes"]:
            if not isinstance(prototype, dict):
                raise ValueError("Normalization response contains an invalid item.")
            base_name = prototype.get("name")
            if not isinstance(base_name, str) or not base_name.strip():
                raise ValueError("Normalization response contains an unnamed item.")
            base_name = base_name.strip()

            count = prototype.get("count", 1)
            if type(count) is not int or count < 1:
                count = 1
                append_follow_up(
                    follow_ups,
                    base_name,
                    "count",
                    "The number of occurrences was unclear; one was retained.",
                )

            record_role = prototype.get("record_role", "assessment")
            if record_role not in RECORD_ROLES:
                record_role = "assessment"
            weight = normalize_weight(
                prototype.get("weight_percent"),
                base_name,
                "weight_percent",
                follow_ups,
            )
            weight_scope = prototype.get("weight_scope", "unknown")
            if weight_scope not in WEIGHT_SCOPES:
                weight_scope = "unknown"
            if count > 1 and group_spec["group_weight_percent"] is not None:
                # The image states a repeated-group total, not a safe per-item
                # value. Never persist a model's arithmetic division as fact.
                weight = None
            weight_scope_name = prototype.get("weight_scope_name")
            if not isinstance(weight_scope_name, str):
                weight_scope_name = None
            parent_name = prototype.get("parent_assessment")
            if not isinstance(parent_name, str):
                parent_name = None
            details = prototype.get("details")
            if not isinstance(details, str):
                details = None

            follow_up_target = base_name
            schedule = normalize_schedule(
                prototype.get("schedule"),
                follow_up_target,
                follow_ups,
                required=record_role == "assessment",
            )
            if (
                count > 1
                and schedule["kind"] == "recurring"
                and (
                    type(schedule["start_week"]) is not int
                    or type(schedule["end_week"]) is not int
                )
            ):
                append_follow_up(
                    follow_ups,
                    follow_up_target,
                    "schedule",
                    "The recurring pattern does not state the full occurrence range.",
                )
            if (
                weight is None
                and group_spec["group_weight_percent"] is None
                and record_role == "assessment"
            ):
                append_follow_up(
                    follow_ups,
                    follow_up_target,
                    "weight_percent",
                    "No assessment weight was stated.",
                )

            for occurrence in range(1, count + 1):
                position += 1
                name = (
                    f"{base_name} {occurrence}"
                    if count > 1
                    else base_name
                )
                assessment_id = make_assessment_id(
                    module_title,
                    assessment_type,
                    position,
                )
                assessment = {
                    "assessment_id": assessment_id,
                    "name": name,
                    "record_role": record_role,
                    "occurrence_number": occurrence,
                    "occurrence_count": count,
                    "weight_percent": weight,
                    "weight_scope": weight_scope,
                    "weight_scope_name": weight_scope_name,
                    "schedule": dict(schedule),
                    "parent_assessment_id": None,
                    "details": details,
                }
                assessments.append(assessment)
                name_lookup.setdefault(name.casefold(), []).append(assessment_id)
                pending_parents.append((assessment, parent_name))

        group = {
            "type": assessment_type,
            "declared_count": len(assessments),
            "group_weight_percent": group_spec["group_weight_percent"],
            "group_weight_scope": group_spec["group_weight_scope"],
            "group_weight_scope_name": group_spec["group_weight_scope_name"],
            "assessments": assessments,
        }
        assessment_types.append(group)

        if (
            len(assessments) > 1
            and group["group_weight_percent"] is not None
            and all(item["weight_percent"] is None for item in assessments)
        ):
            append_follow_up(
                follow_ups,
                assessment_type,
                "weight_percent",
                "The group total is known, but individual weights are not stated.",
            )

    # Step 3: link children only when the parent name resolves to one record.
    for assessment, parent_name in pending_parents:
        if parent_name is None:
            continue
        parent_ids = name_lookup.get(parent_name.casefold(), [])
        if len(parent_ids) == 1:
            assessment["parent_assessment_id"] = parent_ids[0]
        else:
            append_follow_up(
                follow_ups,
                assessment["name"],
                "parent_assessment_id",
                f"Parent assessment '{parent_name}' could not be linked uniquely.",
            )

    # Step 4: a source-explicit schedule is authoritative. Remove model
    # questions that second-guess it or demand dates for structural groups.
    records_by_name = {}
    for group in assessment_types:
        for assessment in group["assessments"]:
            records_by_name.setdefault(
                assessment["name"].casefold(), []
            ).append(assessment)
    resolved_follow_ups = []
    for follow_up in follow_ups:
        assessment_name = follow_up.get("assessment")
        records = (
            records_by_name.get(assessment_name.casefold(), [])
            if isinstance(assessment_name, str)
            else []
        )
        schedule_is_resolved = (
            follow_up.get("field") == "schedule"
            and len(records) == 1
            and (
                records[0]["record_role"] == "group"
                or records[0]["schedule"]["kind"] != "unknown"
            )
        )
        if not schedule_is_resolved:
            resolved_follow_ups.append(follow_up)
    follow_ups = resolved_follow_ups

    # Step 5: add module-level comments and connect comments to stable IDs.
    if not assessment_types:
        append_follow_up(
            follow_ups,
            None,
            "assessment_types",
            "No schedulable assessments could be extracted from this source.",
        )
    if coverage_status != "appears_complete":
        append_follow_up(
            follow_ups,
            None,
            "source_coverage",
            coverage_comment or "The visible assessment source may be incomplete.",
        )

    for follow_up in follow_ups:
        assessment_name = follow_up.get("assessment")
        assessment_ids = (
            name_lookup.get(assessment_name.casefold(), [])
            if isinstance(assessment_name, str)
            else []
        )
        follow_up["assessment_id"] = (
            assessment_ids[0] if len(assessment_ids) == 1 else None
        )

    return {
        "module_title": module_title,
        "credit": credit,
        "source_coverage": source_coverage,
        "assessment_types": assessment_types,
        "notes": notes,
        "follow_ups": follow_ups,
    }


async def process_module(module, client, semaphore):
    """Process one IO-validated module and return ``(module, error)``.

    The three AI requests run in order for this module. Expected and unexpected
    failures are converted to one hard-error string so other modules continue.
    """
    module_title = module["module_title"]
    LOGGER.info("AI Manager processing %s", module_title)

    try:
        image_data = image_to_data_url(module["stored_file_path"])
        relevance = await check_relevance(
            client,
            module_title,
            image_data,
            semaphore,
        )
        if relevance.get("relevant") is not True:
            reason = relevance.get("reason", "Image is not assessment-related.")
            failure = format_ai_error(module_title, reason)
            LOGGER.warning("%s", failure)
            return None, failure

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
        module_output = build_module_output(
            module_title,
            module["credit"],
            normalized,
        )
        LOGGER.info("AI Manager completed %s", module_title)
        return module_output, None
    except Exception as error:
        # A failed module must not stop other concurrent module requests.
        failure = format_ai_error(module_title, error)
        LOGGER.warning("%s", failure)
        return None, failure


async def process_payload(payload, errors, client=None):
    """Process all modules and return the next payload with the same error list.

    Module tasks run concurrently but share a four-request semaphore. Failed
    modules append hard errors; successful modules keep input order. ``client``
    may be injected by tests, otherwise this function creates and closes it.
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
