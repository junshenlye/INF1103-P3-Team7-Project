"""Create and own weekly appearances from canonical domain assessments."""

from .rules import WEEK_COUNT, RECESS_WEEKS, UNSCHEDULED_MESSAGES, format_logic_error
from .importance_ranker import ImportanceRanker
from ..domain.weekly_schedule import WeeklySchedule


class ScheduleBuilder:
    def __init__(self, ranker=None):
        self.ranker = ranker or ImportanceRanker()

    def make_item(self, module, group, assessment):
        score, status = assessment.importance(module.credit, group.group_weight_percent)
        return {
            "assessment_id": assessment.assessment_id,
            "module_title": module.module_title,
            "assessment_type": group.type,
            "name": assessment.name,
            "slot_role": None,
            "credit": module.credit,
            "weight_percent": assessment.weight_percent,
            "group_weight_percent": group.group_weight_percent,
            "importance_score": score,
            "importance_status": status,
            "importance_rank": None,
            "importance_ranked_count": None,
            "priority": "unknown",
            "week_rank": None,
            "parent_assessment_id": assessment.parent_assessment_id,
            "source_schedule": assessment.timing.raw,
            "comments": module.comments_for(assessment, group.type),
        }

    def sort_and_rank_weeks(self, weeks):
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

    def build(self, modules, errors):
        """Build Week 1-14 buckets and preserve every unscheduled assessment.

        Structural group records are not timetable events. Duplicate IDs are the
        only per-record hard invariant checked here because duplicate references
        would make the frontend schedule unsafe to use.
        """
        weeks = [
            {"week": week_number, "is_recess": week_number in RECESS_WEEKS, "items": []}
            for week_number in range(1, WEEK_COUNT + 1)
        ]
        unscheduled = []
        seen_ids = set()
        scheduled_ids = set()
        assessment_entries = []
        for module in modules:
            for group in module.groups:
                for assessment in group.assessments:
                    if assessment.record_role == "group":
                        continue
                    assessment_id = assessment.assessment_id
                    if assessment_id in seen_ids:
                        errors.append(
                            format_logic_error(
                                f"Duplicate assessment_id '{assessment_id}'."
                            )
                        )
                        continue
                    seen_ids.add(assessment_id)
                    item = self.make_item(module, group, assessment)
                    (placements, reason) = assessment.placements()
                    assessment_entries.append((item, placements, reason))
        importance = self.ranker.rank([item for (item, _, _) in assessment_entries])
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
        self.sort_and_rank_weeks(weeks)
        unscheduled.sort(
            key=lambda item: (
                item["importance_rank"] is None,
                item["importance_rank"] or 0,
                item["module_title"].casefold(),
                item["name"].casefold(),
            )
        )
        return WeeklySchedule.from_record(
            {
                "week_count": WEEK_COUNT,
                "recess_weeks": list(RECESS_WEEKS),
                "importance": importance,
                "weeks": weeks,
                "unscheduled": unscheduled,
                "scheduled_assessment_count": len(scheduled_ids),
                "unscheduled_assessment_count": len(unscheduled),
            }
        )
