"""Established assessment and advice constants shared by focused policies."""

from ..domain.assessment_timing import WEEK_COUNT, RECESS_WEEKS

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
    "current_week": None,
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


def format_logic_error(error):
    """Return one hard Logic Manager error using the pipeline prefix."""
    return f"Logic Manager error: {error}"
