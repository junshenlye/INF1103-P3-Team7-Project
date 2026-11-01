"""Coordinate domain normalization, scheduling and advice validation."""

import logging
from .module_normalizer import ModuleNormalizer
from .schedule_builder import ScheduleBuilder
from .recommendation_validator import RecommendationValidator
from .rules import format_logic_error

LOGGER = logging.getLogger(__name__)


class LogicManager:
    def __init__(self, normalizer=None, schedules=None, recommendations=None):
        self.normalizer = normalizer or ModuleNormalizer()
        self.schedules = schedules or ScheduleBuilder()
        self.recommendations = recommendations or RecommendationValidator()

    def normalize(self, records, errors):
        if not isinstance(records, list):
            raise ValueError("AI payload modules must be a list.")
        modules = []
        seen = set()
        for position, record in enumerate(records, 1):
            try:
                module = self.normalizer.normalize(record)
                ids = {item.assessment_id for item in module.assessments}
                duplicates = ids & seen
                if duplicates:
                    raise ValueError(
                        f"Duplicate assessment_id '{sorted(duplicates)[0]}'."
                    )
                seen.update(ids)
                modules.append(module)
            except (KeyError, TypeError, ValueError) as error:
                name = record.get("module_title") if isinstance(record, dict) else None
                errors.append(
                    format_logic_error(f"{name or f'module {position}'}: {error}")
                )
        return tuple(modules)

    def build(self, records, errors):
        modules = self.normalize(records, errors)
        if not modules:
            return (), None
        return modules, self.schedules.build(modules, errors)

    def process_payload(self, payload, errors):
        if payload is None:
            return None, errors
        try:
            modules, schedule = self.build(payload["modules"], errors)
            if not modules:
                return None, errors
            return {
                **payload,
                "module_count": len(modules),
                "modules": [module.to_record() for module in modules],
                "schedule": schedule.to_record(),
            }, errors
        except (KeyError, TypeError, ValueError) as error:
            errors.append(format_logic_error(f"Invalid AI payload: {error}"))
            return None, errors

    def process_recommendation(
        self, recommendation, kind, project, preferences, errors
    ):
        try:
            return self.recommendations.validate(
                recommendation, kind, project, preferences
            ).to_record(), errors
        except (KeyError, TypeError, ValueError) as error:
            errors.append(format_logic_error(f"Invalid AI recommendation: {error}"))
            return None, errors
