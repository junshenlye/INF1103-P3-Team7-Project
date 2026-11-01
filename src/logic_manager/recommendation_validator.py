"""Validate advice references, uncertainty, recess and weekly capacity."""

import math
import re
from .rules import *
from ..domain.study_plan import StudyPlan


class RecommendationValidator:
    def validate(self, recommendation, kind, project, preferences):
        return StudyPlan.from_validated(
            self.normalize_recommendation_output(
                recommendation, kind, project, preferences
            )
        )

    def normalize_study_preferences(self, preferences):
        """Return the small validated preference set used by recommendations."""
        if preferences is None:
            preferences = {}
        if not isinstance(preferences, dict):
            raise ValueError("Study preferences must be a dictionary.")
        available_hours = preferences.get("available_hours_per_week", 8)
        current_week = preferences.get("current_week")
        if type(available_hours) not in (int, float) or not 0 < available_hours <= 168:
            raise ValueError("available_hours_per_week must be between 0 and 168.")
        if current_week is not None and (
            type(current_week) is not int or not 1 <= current_week <= 14
        ):
            raise ValueError("current_week must be null or an integer from 1 to 14.")
        preferred_days = preferences.get("preferred_days", [])
        if not isinstance(preferred_days, list) or not all(
            (isinstance(day, str) for day in preferred_days)
        ):
            raise ValueError("preferred_days must be an array of strings.")
        return {
            "available_hours_per_week": available_hours,
            "current_week": current_week,
            "preferred_days": preferred_days,
        }

    def collect_recommendation_references(self, project_payload):
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
                        if assessment_id in assessment_modules:
                            raise ValueError(
                                "Recommendation input contains duplicate assessment IDs."
                            )
                        assessment_modules[assessment_id] = module_title
        return (module_titles, assessment_modules)

    def resolve_recommendation_module(
        self, module_title, module_titles, assessment_id, assessment_modules
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
            canonical_title = re.sub("[^A-Z0-9]", "", clean_title.upper())
            canonical_matches = [
                confirmed_title
                for confirmed_title in module_titles
                if re.sub("[^A-Z0-9]", "", confirmed_title.upper()) == canonical_title
            ]
            if len(canonical_matches) == 1:
                return canonical_matches[0]
            code_match = re.search(
                "\\b[A-Z]{2,}\\s*[-_]?\\s*\\d{3,}[A-Z]?\\b", clean_title, re.IGNORECASE
            )
            if code_match:
                canonical_code = re.sub("[^A-Z0-9]", "", code_match.group().upper())
                code_matches = [
                    confirmed_title
                    for confirmed_title in module_titles
                    if canonical_code
                    in re.sub("[^A-Z0-9]", "", confirmed_title.upper())
                ]
                if len(code_matches) == 1:
                    return code_matches[0]
        if assessment_id in assessment_modules:
            return assessment_modules[assessment_id]
        if assessment_id is None:
            return None
        raise ValueError("Recommendation references an unknown module.")

    def normalize_plan_item(
        self,
        item,
        module_titles,
        assessment_modules,
        recess_weeks,
        recess_assessment_ids,
        unscheduled_assessment_ids,
        expected_week=None,
    ):
        """Validate one recommendation item without inventing assessment timing.

        Advice linked to an assessment with no confirmed week becomes flexible
        work. Any numbered week returned by the model is discarded so it cannot be
        mistaken for a source-backed deadline or preparation week.
        """
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
        resolved_module_title = self.resolve_recommendation_module(
            module_title, module_titles, assessment_id, assessment_modules
        )
        if (
            assessment_id is not None
            and assessment_modules[assessment_id] != resolved_module_title
        ):
            raise ValueError("Recommendation links an assessment to the wrong module.")
        timing_status = "recommended"
        if assessment_id in unscheduled_assessment_ids:
            week = None
            timing_status = "date_unknown"
        else:
            if type(week) is not int or not 1 <= week <= 14:
                raise ValueError("Recommendation week must be between 1 and 14.")
            if expected_week is not None and week != expected_week:
                raise ValueError(
                    "Recommendation item week does not match its week group."
                )
            if week in recess_weeks and assessment_id not in recess_assessment_ids:
                raise ValueError("Recommendation adds work to a recess week.")
        if (
            type(estimated_hours) not in (int, float)
            or not math.isfinite(estimated_hours)
            or estimated_hours <= 0
        ):
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
            "timing_status": timing_status,
        }

    def validate_weekly_hours(self, items, available_hours):
        """Reject recommendation output that exceeds the student's weekly limit."""
        totals = {}
        for item in items:
            week = item["week"]
            totals[week] = round(totals.get(week, 0) + item["estimated_hours"], 2)
        if any((total > available_hours for total in totals.values())):
            raise ValueError("Recommendation exceeds available_hours_per_week.")
        return totals

    def recommendation_schedule_rules(self, project_payload):
        """Return the confirmed timing boundaries used to validate AI advice."""
        schedule = project_payload.get("schedule", {})
        recess_weeks = {
            week for week in schedule.get("recess_weeks", []) if type(week) is int
        }
        explicit_assessments = {
            item.get("assessment_id")
            for week in schedule.get("weeks", [])
            if week.get("week") in recess_weeks
            for item in week.get("items", [])
            if isinstance(item.get("assessment_id"), str)
        }
        unscheduled_assessments = {
            item.get("assessment_id")
            for item in schedule.get("unscheduled", [])
            if isinstance(item.get("assessment_id"), str)
        }
        return (recess_weeks, explicit_assessments, unscheduled_assessments)

    def deduplicate_flexible_items(self, items):
        """Return at most six distinct date-unknown preparation suggestions."""
        unique_items = []
        seen = set()
        for item in items:
            key = (item["assessment_id"], item["title"].casefold())
            if key in seen:
                continue
            seen.add(key)
            unique_items.append(item)
            if len(unique_items) == 6:
                break
        return unique_items

    def normalize_highlights(self, recommendation):
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
                    {"title": default_titles[index], "suggestion": highlight.strip()}
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
                {"title": title.strip(), "suggestion": suggestion.strip()}
            )
        return normalized

    def normalize_recommendation_output(
        self, recommendation, recommendation_type, project_payload, preferences
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
        normalized_preferences = self.normalize_study_preferences(preferences)
        (module_titles, assessment_modules) = self.collect_recommendation_references(
            project_payload
        )
        (recess_weeks, recess_assessment_ids, unscheduled_assessment_ids) = (
            self.recommendation_schedule_rules(project_payload)
        )
        highlights = self.normalize_highlights(recommendation)
        if recommendation_type == "work_checklist":
            raw_items = recommendation.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("Work checklist must contain an item array.")
            validated_items = [
                self.normalize_plan_item(
                    item,
                    module_titles,
                    assessment_modules,
                    recess_weeks,
                    recess_assessment_ids,
                    unscheduled_assessment_ids,
                )
                for item in raw_items
            ]
            flexible_items = self.deduplicate_flexible_items(
                [item for item in validated_items if item["week"] is None]
            )
            items = [item for item in validated_items if item["week"] is not None][:12]
            weekly_hours = self.validate_weekly_hours(
                items, normalized_preferences["available_hours_per_week"]
            )
            return {
                "recommendation_type": recommendation_type,
                "summary": summary.strip(),
                "highlights": highlights,
                "items": items,
                "flexible_items": flexible_items,
                "weekly_hours": weekly_hours,
            }
        raw_weeks = recommendation.get("weeks")
        if not isinstance(raw_weeks, list):
            raise ValueError("Revision plan must contain a week array.")
        seen_weeks = set()
        weeks = []
        all_items = []
        flexible_items = []
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
                self.normalize_plan_item(
                    item,
                    module_titles,
                    assessment_modules,
                    recess_weeks,
                    recess_assessment_ids,
                    unscheduled_assessment_ids,
                    expected_week=week_number,
                )
                for item in raw_items
            ]
            flexible_items.extend(
                (item for item in validated_items if item["week"] is None)
            )
            items = [item for item in validated_items if item["week"] is not None][:3]
            if not items:
                continue
            all_items.extend(items)
            weeks.append(
                {
                    "week": week_number,
                    "focus": focus.strip(),
                    "items": items,
                    "total_hours": round(
                        sum((item["estimated_hours"] for item in items)), 2
                    ),
                }
            )
        raw_flexible_items = recommendation.get("flexible_items", [])
        if not isinstance(raw_flexible_items, list):
            raise ValueError("Flexible recommendation items must be an array.")
        for item in raw_flexible_items:
            normalized_item = self.normalize_plan_item(
                item,
                module_titles,
                assessment_modules,
                recess_weeks,
                recess_assessment_ids,
                unscheduled_assessment_ids,
            )
            if normalized_item["week"] is not None:
                raise ValueError(
                    "Flexible recommendation item must reference an unscheduled assessment."
                )
            flexible_items.append(normalized_item)
        self.validate_weekly_hours(
            all_items, normalized_preferences["available_hours_per_week"]
        )
        weeks.sort(key=lambda week: week["week"])
        return {
            "recommendation_type": recommendation_type,
            "summary": summary.strip(),
            "highlights": highlights,
            "weeks": weeks,
            "flexible_items": self.deduplicate_flexible_items(flexible_items),
        }
