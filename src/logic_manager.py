"""Normalize AI output and build a deterministic Week 1-14 schedule.

AI Manager returns structured model output. Logic Manager applies the domain
rules: expand repeated assessments, protect group weights, create stable IDs,
validate study advice and place assessments in the weekly overview.
"""

import logging
import re


LOGGER = logging.getLogger(__name__)
WEEK_COUNT = 14
RECESS_WEEKS = (7,)
SCHEDULE_KINDS = {"week", "week_range", "recurring", "unknown"}
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
SUPPORTED_RECOMMENDATION_TYPES = {
    "work_checklist",
    "trimester_revision_plan",
}
RECOMMENDATION_PRIORITIES = {"high", "medium", "low"}
DEFAULT_RECOMMENDATION_TYPE = "trimester_revision_plan"
DEFAULT_STUDY_PREFERENCES = {
    "available_hours_per_week": 8,
    "current_week": 1,
    "preferred_days": [],
}

UNSCHEDULED_MESSAGES = {
    "week_not_stated": "No teaching week was stated for this assessment.",
    "week_out_of_range": "The stated week is outside Weeks 1-14.",
    "week_range_invalid": "The stated week range cannot be placed in Weeks 1-14.",
    "recurrence_unresolved": (
        "The recurring assessments do not have an unambiguous weekly sequence."
    ),
}


def module_codes_match(requested_title, detected_title):
    """Return whether a visible module code matches the submitted label.

    A source without a visible code can continue. When both labels contain a
    code such as INF1103, they must refer to the same module.
    """
    if not isinstance(detected_title, str) or not detected_title.strip():
        return True

    pattern = re.compile(r"\b[A-Z]{2,}\s*[-_]?\s*\d{3,}[A-Z]?\b", re.IGNORECASE)
    requested_match = pattern.search(requested_title)
    detected_match = pattern.search(detected_title)
    if requested_match is None or detected_match is None:
        return True

    canonical = lambda value: re.sub(r"[^A-Z0-9]", "", value.upper())
    return canonical(requested_match.group()) == canonical(detected_match.group())


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
    elif kind == "recurring" and not isinstance(normalized["raw"], str):
        normalized["kind"] = "unknown"

    if normalized["kind"] == "unknown" and required:
        append_follow_up(
            follow_ups,
            assessment,
            "schedule",
            "No complete schedulable teaching week or recurrence was stated.",
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


def reconcile_numbered_week_ranges(assessment_types, follow_ups, notes):
    """Repair one safe model pattern and flag the remaining ambiguous ranges.

    Models sometimes copy a comma-separated list such as ``Week 2, Week 3``
    onto both ``Quiz 1`` and ``Quiz 2``. When numbered records, listed weeks
    and range length match exactly, source order gives an unambiguous one-to-one
    mapping. Other list-like ranges remain unchanged and receive a follow-up.
    """
    for group in assessment_types:
        shared_ranges = {}
        for assessment in group["assessments"]:
            schedule = assessment["schedule"]
            raw = schedule.get("raw")
            name_match = re.match(
                r"^(.*?)(?:\s+|[-#])(\d+)$",
                assessment["name"].strip(),
            )
            is_list_wording = (
                isinstance(raw, str)
                and re.search(r",|\band\b|&", raw, re.IGNORECASE)
            )
            if (
                assessment["record_role"] != "assessment"
                or schedule["kind"] != "week_range"
                or not name_match
                or not is_list_wording
            ):
                continue

            start_week = schedule["start_week"]
            end_week = schedule["end_week"]
            stated_weeks = [int(value) for value in re.findall(r"\d+", raw)]
            expected_weeks = list(range(start_week, end_week + 1))
            if stated_weeks != expected_weeks:
                continue

            key = (
                name_match.group(1).strip().casefold(),
                start_week,
                end_week,
                raw.casefold(),
            )
            shared_ranges.setdefault(key, []).append(
                (int(name_match.group(2)), assessment)
            )

        for (_, start_week, end_week, _), numbered in shared_ranges.items():
            numbered.sort(key=lambda item: item[0])
            numbers = [number for number, _ in numbered]
            weeks = list(range(start_week, end_week + 1))
            numbers_are_consecutive = numbers == list(
                range(numbers[0], numbers[0] + len(numbers))
            )
            if len(numbered) != len(weeks) or not numbers_are_consecutive:
                continue

            placements = []
            for week, (_, assessment) in zip(weeks, numbered):
                assessment["schedule"].update(
                    {
                        "kind": "week",
                        "week": week,
                        "start_week": None,
                        "end_week": None,
                    }
                )
                placements.append(f"{assessment['name']}—Week {week}")
            notes.append(
                "Schedule normalized from a shared list of weeks: "
                + "; ".join(placements)
                + "."
            )

        for assessment in group["assessments"]:
            schedule = assessment["schedule"]
            raw = schedule.get("raw")
            if (
                schedule["kind"] == "week_range"
                and isinstance(raw, str)
                and re.search(r"/|,|\band\b|&", raw, re.IGNORECASE)
            ):
                append_follow_up(
                    follow_ups,
                    assessment["name"],
                    "schedule",
                    "The source lists more than one week; confirm whether this "
                    "assessment is active across the range or occurs in one "
                    "specific week.",
                )


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

    # Step 3: repair only deterministic schedule patterns. Ambiguous ranges
    # remain source-faithful and become visible follow-ups.
    reconcile_numbered_week_ranges(assessment_types, follow_ups, notes)

    # Step 4: link children only when the parent name resolves to one record.
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

    # Step 5: a source-explicit schedule is authoritative. Remove model
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
                or records[0]["schedule"]["kind"] == "week"
                or (
                    records[0]["schedule"]["kind"] == "recurring"
                    and type(records[0]["schedule"]["start_week"]) is int
                    and type(records[0]["schedule"]["end_week"]) is int
                )
            )
        )
        if not schedule_is_resolved:
            resolved_follow_ups.append(follow_up)
    follow_ups = resolved_follow_ups

    # Step 6: add module-level comments and connect comments to stable IDs.
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


def normalize_study_preferences(preferences):
    """Return the small validated preference set used by recommendations."""
    if preferences is None:
        preferences = {}
    if not isinstance(preferences, dict):
        raise ValueError("Study preferences must be a dictionary.")

    available_hours = preferences.get("available_hours_per_week", 8)
    current_week = preferences.get("current_week", 1)
    if type(available_hours) not in (int, float) or not 0 < available_hours <= 168:
        raise ValueError("available_hours_per_week must be between 0 and 168.")
    if type(current_week) is not int or not 1 <= current_week <= 14:
        raise ValueError("current_week must be an integer from 1 to 14.")

    preferred_days = preferences.get("preferred_days", [])
    if not isinstance(preferred_days, list) or not all(
        isinstance(day, str) for day in preferred_days
    ):
        raise ValueError("preferred_days must be an array of strings.")
    return {
        "available_hours_per_week": available_hours,
        "current_week": current_week,
        "preferred_days": preferred_days,
    }


def collect_recommendation_references(project_payload):
    """Return valid modules and the module owning each assessment ID."""
    if not isinstance(project_payload, dict):
        raise ValueError("Recommendation input must be a project payload.")
    modules = project_payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("Recommendation input has no confirmed modules.")

    module_titles = set()
    assessment_modules = {}
    for module in modules:
        module_title = module.get("module_title")
        if not isinstance(module_title, str):
            raise ValueError("Recommendation input contains an invalid module.")
        module_titles.add(module_title)
        for group in module.get("assessment_types", []):
            for assessment in group.get("assessments", []):
                assessment_id = assessment.get("assessment_id")
                if isinstance(assessment_id, str):
                    existing_module = assessment_modules.get(assessment_id)
                    if existing_module not in (None, module_title):
                        raise ValueError(
                            "Recommendation input contains duplicate assessment IDs."
                        )
                    assessment_modules[assessment_id] = module_title
    return module_titles, assessment_modules


def resolve_recommendation_module(
    module_title,
    module_titles,
    assessment_id,
    assessment_modules,
):
    """Return a confirmed module title or ``None`` for general study work.

    Qwen may call a cross-module habit "All modules" or add a description to a
    real module code. Those wording differences should not discard the whole
    plan. Assessment ownership still comes only from confirmed source data.
    """
    if isinstance(module_title, str):
        clean_title = module_title.strip()
        for confirmed_title in module_titles:
            if clean_title.casefold() == confirmed_title.casefold():
                return confirmed_title

        canonical_title = re.sub(r"[^A-Z0-9]", "", clean_title.upper())
        canonical_matches = [
            confirmed_title
            for confirmed_title in module_titles
            if re.sub(r"[^A-Z0-9]", "", confirmed_title.upper())
            == canonical_title
        ]
        if len(canonical_matches) == 1:
            return canonical_matches[0]

        code_match = re.search(
            r"\b[A-Z]{2,}\s*[-_]?\s*\d{3,}[A-Z]?\b",
            clean_title,
            re.IGNORECASE,
        )
        if code_match:
            canonical_code = re.sub(
                r"[^A-Z0-9]",
                "",
                code_match.group().upper(),
            )
            code_matches = [
                confirmed_title
                for confirmed_title in module_titles
                if canonical_code
                in re.sub(r"[^A-Z0-9]", "", confirmed_title.upper())
            ]
            if len(code_matches) == 1:
                return code_matches[0]

    # An unfamiliar label attached to a real assessment is recoverable because
    # the assessment ID gives us its confirmed owner.
    if assessment_id in assessment_modules:
        return assessment_modules[assessment_id]

    # Unlinked advice may genuinely span the trimester. Do not retain an
    # invented label; represent it explicitly as general study work.
    if assessment_id is None:
        return None
    raise ValueError("Recommendation references an unknown module.")


def normalize_plan_item(
    item,
    module_titles,
    assessment_modules,
    recess_weeks,
    recess_assessment_ids,
    expected_week=None,
):
    """Validate and return one recommendation item without adding facts."""
    if not isinstance(item, dict):
        raise ValueError("Recommendation contains an invalid plan item.")
    title = item.get("title")
    module_title = item.get("module_title")
    assessment_id = item.get("assessment_id")
    week = item.get("week")
    estimated_hours = item.get("estimated_hours")
    priority = item.get("priority")
    reason = item.get("reason")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("Every recommendation item needs a title.")
    if assessment_id is not None and assessment_id not in assessment_modules:
        raise ValueError("Recommendation references an unknown assessment.")
    resolved_module_title = resolve_recommendation_module(
        module_title,
        module_titles,
        assessment_id,
        assessment_modules,
    )
    if (
        assessment_id is not None
        and assessment_modules[assessment_id] != resolved_module_title
    ):
        raise ValueError("Recommendation links an assessment to the wrong module.")
    if type(week) is not int or not 1 <= week <= 14:
        raise ValueError("Recommendation week must be between 1 and 14.")
    if expected_week is not None and week != expected_week:
        raise ValueError("Recommendation item week does not match its week group.")
    if week in recess_weeks and assessment_id not in recess_assessment_ids:
        raise ValueError("Recommendation adds work to a recess week.")
    if type(estimated_hours) not in (int, float) or estimated_hours <= 0:
        raise ValueError("Recommendation hours must be a positive number.")
    if priority not in RECOMMENDATION_PRIORITIES:
        raise ValueError("Recommendation priority must be high, medium or low.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Every recommendation item needs a reason.")

    return {
        "title": title.strip(),
        "assessment_id": assessment_id,
        "module_title": resolved_module_title,
        "week": week,
        "estimated_hours": round(estimated_hours, 2),
        "priority": priority,
        "reason": reason.strip(),
    }


def validate_weekly_hours(items, available_hours):
    """Reject recommendation output that exceeds the student's weekly limit."""
    totals = {}
    for item in items:
        week = item["week"]
        totals[week] = round(totals.get(week, 0) + item["estimated_hours"], 2)
    if any(total > available_hours for total in totals.values()):
        raise ValueError("Recommendation exceeds available_hours_per_week.")
    return totals


def recommendation_recess_rules(project_payload):
    """Return recess weeks and assessments explicitly placed within them."""
    schedule = project_payload.get("schedule", {})
    recess_weeks = {
        week for week in schedule.get("recess_weeks", [])
        if type(week) is int
    }
    explicit_assessments = {
        item.get("assessment_id")
        for week in schedule.get("weeks", [])
        if week.get("week") in recess_weeks
        for item in week.get("items", [])
        if isinstance(item.get("assessment_id"), str)
    }
    return recess_weeks, explicit_assessments


def normalize_highlights(recommendation):
    """Return at most three titled suggestions for a scannable frontend.

    Older saved recommendations used plain strings. They remain valid and get
    a neutral display title so existing student plans do not break.
    """
    highlights = recommendation.get("highlights", [])
    if not isinstance(highlights, list):
        raise ValueError("Recommendation highlights must be an array.")

    default_titles = ("Start here", "Plan ahead", "Keep in mind")
    normalized = []
    for index, highlight in enumerate(highlights[:3]):
        if isinstance(highlight, str) and highlight.strip():
            normalized.append(
                {
                    "title": default_titles[index],
                    "suggestion": highlight.strip(),
                }
            )
            continue
        if not isinstance(highlight, dict):
            raise ValueError("Every recommendation highlight must be a suggestion.")
        title = highlight.get("title")
        suggestion = highlight.get("suggestion")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Every recommendation highlight needs a title.")
        if not isinstance(suggestion, str) or not suggestion.strip():
            raise ValueError("Every recommendation highlight needs a suggestion.")
        normalized.append(
            {
                "title": title.strip(),
                "suggestion": suggestion.strip(),
            }
        )
    return normalized


def normalize_recommendation_output(
    recommendation,
    recommendation_type,
    project_payload,
    preferences,
):
    """Validate model advice against confirmed modules and study capacity."""
    if recommendation_type not in SUPPORTED_RECOMMENDATION_TYPES:
        raise ValueError("Unsupported recommendation type.")
    if not isinstance(recommendation, dict):
        raise ValueError("Recommendation model returned an invalid response.")
    if recommendation.get("recommendation_type") != recommendation_type:
        raise ValueError("Recommendation type does not match the request.")

    summary = recommendation.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Recommendation needs a summary.")
    normalized_preferences = normalize_study_preferences(preferences)
    module_titles, assessment_modules = collect_recommendation_references(
        project_payload
    )
    recess_weeks, recess_assessment_ids = recommendation_recess_rules(
        project_payload
    )
    highlights = normalize_highlights(recommendation)

    if recommendation_type == "work_checklist":
        raw_items = recommendation.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("Work checklist must contain an item array.")
        validated_items = [
            normalize_plan_item(
                item,
                module_titles,
                assessment_modules,
                recess_weeks,
                recess_assessment_ids,
            )
            for item in raw_items
        ]
        # The checklist is an overview, not a second assessment catalogue.
        items = validated_items[:12]
        weekly_hours = validate_weekly_hours(
            items,
            normalized_preferences["available_hours_per_week"],
        )
        return {
            "recommendation_type": recommendation_type,
            "summary": summary.strip(),
            "highlights": highlights,
            "items": items,
            "weekly_hours": weekly_hours,
        }

    raw_weeks = recommendation.get("weeks")
    if not isinstance(raw_weeks, list):
        raise ValueError("Revision plan must contain a week array.")
    seen_weeks = set()
    weeks = []
    all_items = []
    for raw_week in raw_weeks:
        if not isinstance(raw_week, dict):
            raise ValueError("Revision plan contains an invalid week.")
        week_number = raw_week.get("week")
        focus = raw_week.get("focus")
        raw_items = raw_week.get("items")
        if (
            type(week_number) is not int
            or not 1 <= week_number <= 14
            or week_number in seen_weeks
        ):
            raise ValueError("Revision plan contains an invalid or duplicate week.")
        if not isinstance(focus, str) or not focus.strip():
            raise ValueError("Every revision week needs a focus.")
        if not isinstance(raw_items, list):
            raise ValueError("Every revision week needs an item array.")
        seen_weeks.add(week_number)
        validated_items = [
            normalize_plan_item(
                item,
                module_titles,
                assessment_modules,
                recess_weeks,
                recess_assessment_ids,
                expected_week=week_number,
            )
            for item in raw_items
        ]
        # Keep weekly advice scannable even if the model returns extra detail.
        items = validated_items[:3]
        all_items.extend(items)
        weeks.append(
            {
                "week": week_number,
                "focus": focus.strip(),
                "items": items,
                "total_hours": round(
                    sum(item["estimated_hours"] for item in items),
                    2,
                ),
            }
        )
    validate_weekly_hours(
        all_items,
        normalized_preferences["available_hours_per_week"],
    )
    weeks.sort(key=lambda week: week["week"])
    return {
        "recommendation_type": recommendation_type,
        "summary": summary.strip(),
        "highlights": highlights,
        "weeks": weeks,
    }


def format_logic_error(error):
    """Return one hard Logic Manager error using the pipeline prefix."""
    return f"Logic Manager error: {error}"


def process_recommendation(
    recommendation,
    recommendation_type,
    project_payload,
    preferences,
    errors,
):
    """Validate one AI recommendation and preserve the shared error list."""
    try:
        normalized = normalize_recommendation_output(
            recommendation,
            recommendation_type,
            project_payload,
            preferences,
        )
        return normalized, errors
    except (KeyError, TypeError, ValueError) as error:
        failure = format_logic_error(f"Invalid AI recommendation: {error}")
        LOGGER.warning("%s", failure)
        errors.append(failure)
        return None, errors


def calculate_importance(credit, assessment, group):
    """Return the comparable score and its status for one assessment.

    Only an explicit module-level weight can be compared across modules. A
    repeated group's total is kept as context and is never divided among its
    occurrences.
    """
    weight = assessment["weight_percent"]
    weight_scope = assessment["weight_scope"]
    group_weight = group["group_weight_percent"]

    if type(weight) in (int, float) and weight_scope == "module":
        score = round(credit * weight / 100, 3)
        return score, "calculated"

    if weight is None and group_weight is not None:
        return None, "group_total_only"
    if weight is not None:
        return None, "non_module_weight"
    return None, "weight_unknown"


def rank_assessments(items):
    """Rank every comparable assessment and derive relative display bands.

    Ranking covers scheduled and unscheduled items together. Equal scores share
    the same rank and priority. Priority uses the item's relative position among
    the distinct observed scores, so it adapts to any number of input modules
    instead of relying on fixed score thresholds.
    """
    ranked_items = sorted(
        (item for item in items if item["importance_score"] is not None),
        key=lambda item: (
            -item["importance_score"],
            item["module_title"].casefold(),
            item["name"].casefold(),
            item["assessment_id"],
        ),
    )
    distinct_scores = sorted(
        {item["importance_score"] for item in ranked_items},
        reverse=True,
    )

    priority_by_score = {}
    for position, score in enumerate(distinct_scores):
        # The midpoint avoids calling a single available score high or low.
        relative_position = (position + 0.5) / len(distinct_scores)
        if relative_position < 1 / 3:
            priority = "high"
        elif relative_position < 2 / 3:
            priority = "medium"
        else:
            priority = "low"
        priority_by_score[score] = priority

    previous_score = None
    current_rank = 0
    for position, item in enumerate(ranked_items, start=1):
        score = item["importance_score"]
        if score != previous_score:
            current_rank = position
            previous_score = score
        item["importance_rank"] = current_rank
        item["importance_ranked_count"] = len(ranked_items)
        item["priority"] = priority_by_score[score]

    return {
        "formula": "credit * weight_percent / 100",
        "ranking_scope": "all assessments with explicit module-level weights",
        "priority_method": "relative thirds of distinct observed scores",
        "ranked_assessment_count": len(ranked_items),
    }


def collect_comments(module, assessment, assessment_type):
    """Project existing follow-up messages onto one schedule item.

    Validation happens before schedule construction. This helper only selects
    already recorded comments for convenient frontend display.
    """
    assessment_id = assessment["assessment_id"]
    targets = {assessment["name"].casefold(), assessment_type.casefold()}
    comments = []

    for follow_up in module["follow_ups"]:
        target = follow_up.get("assessment")
        applies_by_id = follow_up.get("assessment_id") == assessment_id
        applies_by_name = (
            follow_up.get("assessment_id") is None
            and isinstance(target, str)
            and target.casefold() in targets
        )
        if (applies_by_id or applies_by_name) and follow_up["message"] not in comments:
            comments.append(follow_up["message"])
    return comments


def make_schedule_item(module, group, assessment):
    """Create the small, frontend-ready view of one assessment record."""
    score, status = calculate_importance(
        module["credit"],
        assessment,
        group,
    )
    return {
        "assessment_id": assessment["assessment_id"],
        "module_title": module["module_title"],
        "assessment_type": group["type"],
        "name": assessment["name"],
        "slot_role": None,
        "credit": module["credit"],
        "weight_percent": assessment["weight_percent"],
        "group_weight_percent": group["group_weight_percent"],
        "importance_score": score,
        "importance_status": status,
        "importance_rank": None,
        "importance_ranked_count": None,
        "priority": "unknown",
        "week_rank": None,
        "parent_assessment_id": assessment["parent_assessment_id"],
        "source_schedule": assessment["schedule"].get("raw"),
        "comments": collect_comments(module, assessment, group["type"]),
    }


def resolve_target_weeks(assessment):
    """Return ``(placements, reason)`` for one normalized schedule.

    A placement is a ``(week, slot_role)`` pair. Repeated assessments are
    mapped only when their count exactly matches a complete consecutive range;
    raw phrases such as "weekly" are never parsed or guessed locally.
    """
    schedule = assessment["schedule"]
    kind = schedule["kind"]

    if kind == "week":
        week = schedule["week"]
        if 1 <= week <= WEEK_COUNT:
            return [(week, "due")], None
        return [], "week_out_of_range"

    if kind == "week_range":
        start_week = schedule["start_week"]
        end_week = schedule["end_week"]
        if 1 <= start_week <= end_week <= WEEK_COUNT:
            return [
                (week, "active")
                for week in range(start_week, end_week + 1)
                if week not in RECESS_WEEKS
            ], None
        return [], "week_range_invalid"

    if kind == "recurring":
        start_week = schedule["start_week"]
        end_week = schedule["end_week"]
        occurrence = assessment["occurrence_number"]
        count = assessment["occurrence_count"]
        has_complete_range = (
            type(start_week) is int
            and type(end_week) is int
            and 1 <= start_week <= end_week <= WEEK_COUNT
        )
        if has_complete_range:
            teaching_weeks = [
                week
                for week in range(start_week, end_week + 1)
                if week not in RECESS_WEEKS
            ]
            if len(teaching_weeks) == count:
                return [(teaching_weeks[occurrence - 1], "occurrence")], None
        return [], "recurrence_unresolved"

    return [], "week_not_stated"


def sort_and_rank_weeks(weeks):
    """Sort weekly buckets by global importance and add a local week rank."""
    for week in weeks:
        week["items"].sort(
            key=lambda item: (
                item["importance_rank"] is None,
                item["importance_rank"] or 0,
                item["module_title"].casefold(),
                item["name"].casefold(),
            )
        )
        next_rank = 1
        for item in week["items"]:
            if item["importance_rank"] is not None:
                item["week_rank"] = next_rank
                next_rank += 1


def build_weekly_schedule(modules, errors):
    """Build Week 1-14 buckets and preserve every unscheduled assessment.

    Structural group records are not timetable events. Duplicate IDs are the
    only per-record hard invariant checked here because duplicate references
    would make the frontend schedule unsafe to use.
    """
    weeks = [
        {
            "week": week_number,
            "is_recess": week_number in RECESS_WEEKS,
            "items": [],
        }
        for week_number in range(1, WEEK_COUNT + 1)
    ]
    unscheduled = []
    seen_ids = set()
    scheduled_ids = set()
    assessment_entries = []

    for module in modules:
        for group in module["assessment_types"]:
            for assessment in group["assessments"]:
                if assessment["record_role"] == "group":
                    continue

                assessment_id = assessment["assessment_id"]
                if assessment_id in seen_ids:
                    errors.append(
                        format_logic_error(
                            f"Duplicate assessment_id '{assessment_id}'."
                        )
                    )
                    continue
                seen_ids.add(assessment_id)

                item = make_schedule_item(module, group, assessment)
                placements, reason = resolve_target_weeks(assessment)
                assessment_entries.append((item, placements, reason))

    # Rank canonical items before week ranges create repeated display copies.
    importance = rank_assessments(
        [item for item, _, _ in assessment_entries]
    )

    for item, placements, reason in assessment_entries:
        if not placements:
            item["slot_role"] = "unscheduled"
            item["unscheduled_reason"] = reason
            message = UNSCHEDULED_MESSAGES[reason]
            if message not in item["comments"]:
                item["comments"].append(message)
            unscheduled.append(item)
            continue

        scheduled_ids.add(item["assessment_id"])
        for week_number, slot_role in placements:
            placed_item = dict(item)
            placed_item["slot_role"] = slot_role
            placed_item["comments"] = list(item["comments"])
            weeks[week_number - 1]["items"].append(placed_item)

    sort_and_rank_weeks(weeks)
    unscheduled.sort(
        key=lambda item: (
            item["importance_rank"] is None,
            item["importance_rank"] or 0,
            item["module_title"].casefold(),
            item["name"].casefold(),
        )
    )
    return {
        "week_count": WEEK_COUNT,
        "recess_weeks": list(RECESS_WEEKS),
        "importance": importance,
        "weeks": weeks,
        "unscheduled": unscheduled,
        "scheduled_assessment_count": len(scheduled_ids),
        "unscheduled_assessment_count": len(unscheduled),
    }


def normalize_module_record(module):
    """Validate one parsed AI record and return its final module structure."""
    if not isinstance(module, dict):
        raise ValueError("Module record must be a dictionary.")

    module_title = module.get("module_title")
    credit = module.get("credit")
    relevance = module.get("ai_relevance")
    ai_output = module.get("ai_output")
    if not isinstance(module_title, str) or not module_title.strip():
        raise ValueError("Module title is missing.")
    if type(credit) not in (int, float):
        raise ValueError("Credit value is invalid.")
    if not isinstance(relevance, dict) or type(relevance.get("relevant")) is not bool:
        raise ValueError("AI relevance response is invalid.")
    if relevance["relevant"] is not True:
        reason = relevance.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "The source is not assessment-related."
        raise ValueError(reason)
    detected_module = relevance.get("detected_module_title")
    if not module_codes_match(module_title, detected_module):
        raise ValueError(
            f"Uploaded evidence appears to belong to {detected_module}."
        )
    if not isinstance(ai_output, dict):
        raise ValueError("AI output is not a structured object.")
    return build_module_output(module_title, credit, ai_output)


def normalize_modules(modules, errors):
    """Normalize usable modules and append one hard error per failed module."""
    if not isinstance(modules, list):
        raise ValueError("AI payload modules must be a list.")

    normalized_modules = []
    for position, module in enumerate(modules, start=1):
        try:
            normalized_modules.append(normalize_module_record(module))
        except (KeyError, TypeError, ValueError) as error:
            module_name = (
                module.get("module_title")
                if isinstance(module, dict)
                else f"module {position}"
            )
            if not isinstance(module_name, str) or not module_name.strip():
                module_name = f"module {position}"
            failure = format_logic_error(f"{module_name}: {error}")
            LOGGER.warning("%s", failure)
            errors.append(failure)
    return normalized_modules


def process_payload(payload, errors):
    """Normalize AI records, attach a schedule and flush hard errors forward."""
    if payload is None:
        return None, errors

    try:
        modules = payload["modules"]
        LOGGER.info("Logic Manager started with %d module(s)", len(modules))
        normalized_modules = normalize_modules(modules, errors)
        if not normalized_modules:
            LOGGER.warning("Logic Manager produced no usable modules")
            return None, errors
        schedule = build_weekly_schedule(normalized_modules, errors)
    except (KeyError, TypeError, ValueError) as error:
        failure = format_logic_error(f"Invalid AI payload: {error}")
        LOGGER.warning("%s", failure)
        errors.append(failure)
        return None, errors

    processed_payload = dict(payload)
    processed_payload["module_count"] = len(normalized_modules)
    processed_payload["modules"] = normalized_modules
    processed_payload["schedule"] = schedule
    LOGGER.info(
        "Logic Manager completed with %d scheduled and %d unscheduled assessment(s)",
        schedule["scheduled_assessment_count"],
        schedule["unscheduled_assessment_count"],
    )
    return processed_payload, errors
