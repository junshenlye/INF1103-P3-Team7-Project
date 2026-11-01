"""Domain invariants, ownership and legacy serialization contracts."""

from dataclasses import FrozenInstanceError, replace

import pytest

from src.domain import DomainError
from src.domain.assessment import Assessment
from src.domain.assessment_timing import AssessmentTiming
from src.domain.module import Module, AssessmentGroup
from src.data_manager.serializers import ResultSerializer
from src.data_manager import DataManagerError
from src.logic_manager import ModuleNormalizer, ScheduleBuilder
from tests.fakes import extraction


def module():
    return ModuleNormalizer().normalize(
        {
            "module_title": "INF1103",
            "credit": 6,
            "ai_relevance": {"relevant": True},
            "ai_output": extraction(),
        }
    )


@pytest.mark.parametrize(
    "timing,occurrence,count,weeks,reason",
    [
        (AssessmentTiming("week", week=7), 1, 1, [7], None),
        (AssessmentTiming("week", week=15), 1, 1, [], "week_out_of_range"),
        (AssessmentTiming("unknown", raw="TBA"), 1, 1, [], "week_not_stated"),
        (AssessmentTiming("week_range", start_week=6, end_week=8), 1, 1, [6, 8], None),
        (
            AssessmentTiming("week_range", start_week=7, end_week=7),
            1,
            1,
            [],
            "week_range_invalid",
        ),
        (
            AssessmentTiming("week_range", start_week=8, end_week=2),
            1,
            1,
            [],
            "week_range_invalid",
        ),
        (
            AssessmentTiming("recurring", start_week=6, end_week=8, raw="Weekly"),
            2,
            2,
            [8],
            None,
        ),
        (
            AssessmentTiming("recurring", raw="Weekly"),
            1,
            3,
            [],
            "recurrence_unresolved",
        ),
        (
            AssessmentTiming("recurring", start_week=6, end_week=8, raw="Weekly"),
            1,
            3,
            [],
            "recurrence_unresolved",
        ),
    ],
)
def test_timing_never_guesses_weeks(timing, occurrence, count, weeks, reason):
    placements, actual_reason = timing.placements(occurrence, count)
    assert [week for week, _ in placements] == weeks
    assert actual_reason == reason
    assert AssessmentTiming.from_record(timing.to_record()) == timing


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "week", "week": True},
        {"kind": "week_range", "start_week": 1},
        {"kind": "invented"},
        {"kind": "recurring"},
        {"raw": {"mutable": []}},
    ],
)
def test_invalid_timing_states_are_rejected(fields):
    with pytest.raises(DomainError):
        AssessmentTiming(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"assessment_id": ""},
        {"name": ""},
        {"record_role": "deadline"},
        {"occurrence_number": 0},
        {"occurrence_number": 2, "occurrence_count": 1},
        {"occurrence_count": True},
        {"weight_percent": float("nan")},
        {"weight_scope": "invented"},
        {"parent_assessment_id": "id"},
    ],
)
def test_assessment_changes_validate_before_acceptance(fields):
    original = Assessment("id", "Quiz", AssessmentTiming())
    with pytest.raises(DomainError):
        replace(original, **fields)
    assert original.assessment_id == "id" and original.occurrence_number == 1


def test_module_and_schedule_are_deeply_immutable_and_detached():
    record = module().to_record()
    record["notes"] = [{"nested": ["original"]}]
    record["follow_ups"] = [
        {
            "assessment": "Quiz",
            "field": "schedule",
            "message": "Confirm the source",
            "assessment_id": None,
        }
    ]
    value = Module.from_record(record)
    record["notes"][0]["nested"].append("changed source")
    assert value.to_record()["notes"] == [{"nested": ["original"]}]
    with pytest.raises(TypeError):
        value.notes[0]["nested"] = ()
    with pytest.raises(FrozenInstanceError):
        value.credit = 1
    schedule = ScheduleBuilder().build((value,), [])
    displayed = schedule.to_record()
    displayed["weeks"][2]["items"][0]["comments"].append("external mutation")
    assert schedule.to_record()["weeks"][2]["items"][0]["comments"] == [
        "Confirm the source"
    ]


def test_groups_keep_totals_separate_and_reject_duplicate_identity():
    item = module().assessments[0]
    group = AssessmentGroup(
        "tutorial", [replace(item, weight_percent=None)], 5, "module"
    )
    assert group.assessments[0].importance(6, group.group_weight_percent) == (
        None,
        "group_total_only",
    )
    with pytest.raises(DomainError, match="duplicate"):
        Module("INF1103", 6, (group, group))


def test_serializer_round_trip_preserves_ids_uncertainty_and_legacy_extras():
    value = module()
    record = value.to_record()
    record["assessment_types"][0]["assessments"][0]["schedule"] = AssessmentTiming(
        raw="TBA"
    ).to_record()
    legacy = {
        "module_count": 1,
        "modules": [record],
        "schedule": {"weeks": []},
        "legacy_extra": {"unknown": None},
    }
    serializer = ResultSerializer()
    loaded = serializer.decode(serializer.encode(legacy))
    assert loaded == legacy
    restored = serializer.modules(loaded)[0]
    assert restored.assessments[0].assessment_id == value.assessments[0].assessment_id
    assert restored.assessments[0].placements() == ([], "week_not_stated")
    loaded["legacy_extra"]["unknown"] = "changed"
    assert legacy["legacy_extra"]["unknown"] is None


def test_invalid_saved_modules_report_storage_error():
    with pytest.raises(DataManagerError, match="Invalid saved module"):
        ResultSerializer().modules({"modules": [{"module_title": "INF1103"}]})


def test_study_plan_separates_flexible_preparation_from_weekly_capacity():
    from src.domain.study_plan import StudyPlan

    plan = StudyPlan.from_validated(
        {
            "recommendation_type": "work_checklist",
            "summary": "Prepare",
            "items": [
                {
                    "title": "Quiz",
                    "assessment_id": "known",
                    "week": 2,
                    "estimated_hours": 2,
                    "timing_status": "recommended",
                }
            ],
            "flexible_items": [
                {
                    "title": "Confirm date",
                    "assessment_id": "unknown",
                    "week": None,
                    "estimated_hours": 1,
                    "timing_status": "date_unknown",
                }
            ],
        }
    )
    assert plan.weekly_hours() == {2: 2}
    assert [task.assessment_id for task in plan.flexible_tasks] == ["unknown"]
    with pytest.raises(TypeError):
        plan.weekly_hours()[2] = 100
    with pytest.raises(DomainError):
        replace(plan.flexible_tasks[0], week=1)


def test_structural_records_have_no_placements_even_with_an_explicit_week():
    group_record = Assessment(
        "group", "Quiz total", AssessmentTiming("week", week=4), record_role="group"
    )
    assert group_record.placements() == ([], None)


def test_malformed_source_timing_stays_unknown_without_losing_the_module():
    raw = extraction()
    raw["assessment_types"][0]["assessments"][0]["schedule"] = {
        "kind": "week",
        "week": "TBA",
        "start_week": {"untrusted": []},
        "raw": "Date TBA",
    }
    result = ModuleNormalizer().normalize(
        {
            "module_title": "INF1103",
            "credit": 6,
            "ai_relevance": {"relevant": True},
            "ai_output": raw,
        }
    )
    item = result.assessments[0]
    assert item.timing.kind == "unknown" and item.timing.week is None
    assert item.timing.raw == "Date TBA"
    assert item.placements() == ([], "week_not_stated")
    assert result.follow_ups
