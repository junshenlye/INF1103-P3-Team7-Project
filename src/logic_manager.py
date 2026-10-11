"""Build a deterministic Week 1-14 assessment schedule.

AI Manager owns interpretation and normalization. Logic Manager trusts that
structure and only decides where each schedulable assessment appears in the
weekly overview. Unclear placements remain visible under ``unscheduled``.
"""

import logging


LOGGER = logging.getLogger(__name__)
WEEK_COUNT = 14

UNSCHEDULED_MESSAGES = {
    "week_not_stated": "No teaching week was stated for this assessment.",
    "week_out_of_range": "The stated week is outside Weeks 1-14.",
    "week_range_invalid": "The stated week range cannot be placed in Weeks 1-14.",
    "recurrence_unresolved": (
        "The recurring assessments do not have an unambiguous weekly sequence."
    ),
}


def format_logic_error(error):
    """Return one hard Logic Manager error using the pipeline prefix."""
    return f"Logic Manager error: {error}"


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
    """Return existing AI follow-up messages relevant to an assessment.

    Logic Manager does not repeat AI validation. It only projects already
    recorded follow-ups into the timetable item for convenient frontend use.
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
        if has_complete_range and end_week - start_week + 1 == count:
            return [(start_week + occurrence - 1, "occurrence")], None
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
        {"week": week_number, "items": []}
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
        "importance": importance,
        "weeks": weeks,
        "unscheduled": unscheduled,
        "scheduled_assessment_count": len(scheduled_ids),
        "unscheduled_assessment_count": len(unscheduled),
    }


def process_payload(payload, errors):
    """Attach a weekly schedule and return the shared hard-error list.

    AI Manager already owns structural normalization. This boundary catches an
    unexpected contract break, formats it once and stops Logic Manager cleanly.
    """
    if payload is None:
        return None, errors

    LOGGER.info(
        "Logic Manager started with %d module(s)",
        payload["module_count"],
    )
    try:
        schedule = build_weekly_schedule(payload["modules"], errors)
    except (KeyError, TypeError, ValueError) as error:
        failure = format_logic_error(f"Invalid AI payload: {error}")
        LOGGER.warning("%s", failure)
        errors.append(failure)
        return None, errors

    processed_payload = dict(payload)
    processed_payload["schedule"] = schedule
    LOGGER.info(
        "Logic Manager completed with %d scheduled and %d unscheduled assessment(s)",
        schedule["scheduled_assessment_count"],
        schedule["unscheduled_assessment_count"],
    )
    return processed_payload, errors
