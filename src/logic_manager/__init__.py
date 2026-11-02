"""Transitional dictionary adapters. Running workflows use domain-aware LogicManager."""

from copy import deepcopy
from .rules import *
from .manager import LogicManager
from .module_normalizer import ModuleNormalizer
from .recommendation_validator import RecommendationValidator
from .schedule_builder import ScheduleBuilder
from .importance_ranker import ImportanceRanker
from ..domain.module import Module
from ..domain.assessment import Assessment


def module_codes_match(requested_title, detected_title):
    return ModuleNormalizer().module_codes_match(requested_title, detected_title)


def append_follow_up(follow_ups, assessment, field, message):
    return ModuleNormalizer().append_follow_up(follow_ups, assessment, field, message)


def normalize_weight(value, assessment, field, follow_ups):
    return ModuleNormalizer().normalize_weight(value, assessment, field, follow_ups)


def normalize_schedule(schedule, assessment, follow_ups, required=True):
    return ModuleNormalizer().normalize_schedule(
        schedule, assessment, follow_ups, required
    )


def make_assessment_id(module_title, assessment_type, position):
    return ModuleNormalizer().make_assessment_id(
        module_title, assessment_type, position
    )


def prepare_follow_ups(raw_follow_ups):
    return ModuleNormalizer().prepare_follow_ups(raw_follow_ups)


def prepare_group_specs(raw_groups, follow_ups):
    return ModuleNormalizer().prepare_group_specs(raw_groups, follow_ups)


def reconcile_numbered_week_ranges(assessment_types, follow_ups, notes):
    return ModuleNormalizer().reconcile_numbered_week_ranges(
        assessment_types, follow_ups, notes
    )


def build_module_output(module_title, credit, normalized):
    return ModuleNormalizer().build_module_output(module_title, credit, normalized)


def normalize_module_record(module):
    return ModuleNormalizer().normalize_module_record(module)


def normalize_study_preferences(preferences):
    return RecommendationValidator().normalize_study_preferences(preferences)


def collect_recommendation_references(project_payload):
    return RecommendationValidator().collect_recommendation_references(project_payload)


def resolve_recommendation_module(
    module_title, module_titles, assessment_id, assessment_modules
):
    return RecommendationValidator().resolve_recommendation_module(
        module_title, module_titles, assessment_id, assessment_modules
    )


def normalize_plan_item(
    item,
    module_titles,
    assessment_modules,
    recess_weeks,
    recess_assessment_ids,
    unscheduled_assessment_ids,
    expected_week=None,
):
    return RecommendationValidator().normalize_plan_item(
        item,
        module_titles,
        assessment_modules,
        recess_weeks,
        recess_assessment_ids,
        unscheduled_assessment_ids,
        expected_week,
    )


def validate_weekly_hours(items, available_hours):
    return RecommendationValidator().validate_weekly_hours(items, available_hours)


def recommendation_schedule_rules(project_payload):
    return RecommendationValidator().recommendation_schedule_rules(project_payload)


def deduplicate_flexible_items(items):
    return RecommendationValidator().deduplicate_flexible_items(items)


def normalize_highlights(recommendation):
    return RecommendationValidator().normalize_highlights(recommendation)


def normalize_recommendation_output(
    recommendation, recommendation_type, project_payload, preferences
):
    return RecommendationValidator().normalize_recommendation_output(
        recommendation, recommendation_type, project_payload, preferences
    )


def process_payload(payload, errors):
    return LogicManager().process_payload(payload, errors)


def process_recommendation(
    recommendation, recommendation_type, project_payload, preferences, errors
):
    return LogicManager().process_recommendation(
        recommendation, recommendation_type, project_payload, preferences, errors
    )


def normalize_modules(modules, errors):
    return [module.to_record() for module in LogicManager().normalize(modules, errors)]


def build_weekly_schedule(modules, errors):
    # Retain the old adapter's per-record duplicate isolation for direct callers.
    records = deepcopy(modules)
    seen = set()
    for module in records:
        for group in module["assessment_types"]:
            accepted = []
            for item in group["assessments"]:
                identity = item["assessment_id"]
                if identity in seen:
                    errors.append(
                        format_logic_error(f"Duplicate assessment_id '{identity}'.")
                    )
                else:
                    seen.add(identity)
                    accepted.append(item)
            group["assessments"] = accepted
    return (
        ScheduleBuilder()
        .build(tuple(Module.from_record(record) for record in records), errors)
        .to_record()
    )


def resolve_target_weeks(assessment):
    return Assessment.from_record(assessment).placements()


def calculate_importance(credit, assessment, group):
    return Assessment.from_record(assessment).importance(
        credit, group["group_weight_percent"]
    )


def rank_assessments(items):
    return ImportanceRanker().rank(items)
