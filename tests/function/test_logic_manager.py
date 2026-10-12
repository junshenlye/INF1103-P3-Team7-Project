"""Function tests for weekly placement and importance handling."""

from src import logic_manager


def test_logic_manager_validates_visible_module_ownership():
    """A wrongly attached screenshot cannot populate another module."""
    assert logic_manager.module_codes_match("INF1103", "INF1103")
    assert logic_manager.module_codes_match("INF1103", None)
    assert not logic_manager.module_codes_match(
        "INF1102",
        "INF1103 - Development Management",
    )


def make_assessment(
    assessment_id,
    name,
    schedule,
    weight=10,
    scope="module",
    occurrence=1,
    count=1,
    role="assessment",
):
    """Return one AI-shaped assessment for concise Logic Manager tests."""
    return {
        "assessment_id": assessment_id,
        "name": name,
        "record_role": role,
        "occurrence_number": occurrence,
        "occurrence_count": count,
        "weight_percent": weight,
        "weight_scope": scope,
        "weight_scope_name": None,
        "schedule": schedule,
        "parent_assessment_id": None,
        "details": None,
    }


def make_group(assessment_type, assessments, group_weight=None):
    """Return one AI-shaped assessment type group."""
    return {
        "type": assessment_type,
        "declared_count": len(assessments),
        "group_weight_percent": group_weight,
        "group_weight_scope": "module" if group_weight is not None else "unknown",
        "group_weight_scope_name": None,
        "assessments": assessments,
    }


def make_module(groups):
    """Return one complete module payload accepted by Logic Manager."""
    return {
        "module_title": "INF1104",
        "credit": 4,
        "source_coverage": {"status": "appears_complete", "comment": None},
        "assessment_types": groups,
        "notes": [],
        "follow_ups": [],
    }


def test_week_range_and_complete_recurrence_are_placed_without_double_weight():
    """Ranges span weeks and repeated group totals stay out of item scores."""
    project = make_assessment(
        "INF1104-PROJECT-01",
        "Project",
        {
            "kind": "week_range",
            "week": None,
            "start_week": 3,
            "end_week": 5,
            "raw": "Weeks 3-5",
        },
        weight=30,
    )
    tutorials = [
        make_assessment(
            f"INF1104-TUTORIAL-{position:02d}",
            f"Tutorial {position}",
            {
                "kind": "recurring",
                "week": None,
                "start_week": 6,
                "end_week": 8,
                "raw": "Weekly, Weeks 6-8 excluding recess",
            },
            weight=None,
            scope="group",
            occurrence=position,
            count=2,
        )
        for position in (1, 2)
    ]
    module = make_module(
        [
            make_group("project", [project]),
            make_group("tutorial", tutorials, group_weight=5),
        ]
    )

    schedule = logic_manager.build_weekly_schedule([module], [])

    assert schedule["recess_weeks"] == [7]
    assert schedule["weeks"][6]["is_recess"] is True

    for week_number in (3, 4, 5):
        item = schedule["weeks"][week_number - 1]["items"][0]
        assert item["assessment_id"] == "INF1104-PROJECT-01"
        assert item["slot_role"] == "active"
        assert item["importance_score"] == 1.2

    tutorial_one = schedule["weeks"][5]["items"][0]
    assert schedule["weeks"][6]["items"] == []
    tutorial_two = schedule["weeks"][7]["items"][0]
    assert tutorial_one["name"] == "Tutorial 1"
    assert tutorial_two["name"] == "Tutorial 2"
    assert tutorial_one["importance_score"] is None
    assert tutorial_one["importance_status"] == "group_total_only"
    assert tutorial_one["group_weight_percent"] == 5
    assert schedule["scheduled_assessment_count"] == 3


def test_recess_removes_range_activity_but_keeps_explicit_due_event():
    """Week 7 is empty unless a source explicitly names that exact week."""
    active = make_assessment(
        "INF1104-PROJECT-01",
        "Project work",
        {
            "kind": "week_range",
            "week": None,
            "start_week": 6,
            "end_week": 8,
            "raw": "Weeks 6-8",
        },
    )
    due = make_assessment(
        "INF1104-QUIZ-01",
        "Recess quiz",
        {
            "kind": "week",
            "week": 7,
            "start_week": None,
            "end_week": None,
            "raw": "Week 7",
        },
    )

    schedule = logic_manager.build_weekly_schedule(
        [make_module([make_group("project", [active]), make_group("quiz", [due])])],
        [],
    )

    assert [item["assessment_id"] for item in schedule["weeks"][5]["items"]] == [
        "INF1104-PROJECT-01"
    ]
    assert [item["assessment_id"] for item in schedule["weeks"][6]["items"]] == [
        "INF1104-QUIZ-01"
    ]
    assert [item["assessment_id"] for item in schedule["weeks"][7]["items"]] == [
        "INF1104-PROJECT-01"
    ]


def test_incomplete_recurrence_stays_visible_as_unscheduled():
    """A weekly phrase without teaching weeks is never guessed locally."""
    tutorials = [
        make_assessment(
            f"INF1104-TUTORIAL-{position:02d}",
            f"Tutorial {position}",
            {
                "kind": "recurring",
                "week": None,
                "start_week": None,
                "end_week": None,
                "raw": "Weekly",
            },
            weight=None,
            scope="group",
            occurrence=position,
            count=10,
        )
        for position in range(1, 11)
    ]
    module = make_module(
        [make_group("tutorial", tutorials, group_weight=5)]
    )

    schedule = logic_manager.build_weekly_schedule([module], [])

    assert schedule["scheduled_assessment_count"] == 0
    assert schedule["unscheduled_assessment_count"] == 10
    assert {
        item["unscheduled_reason"] for item in schedule["unscheduled"]
    } == {"recurrence_unresolved"}
    assert all(
        item["importance_status"] == "group_total_only"
        for item in schedule["unscheduled"]
    )


def test_all_weighted_items_receive_global_rank_before_week_placement():
    """Scheduled and unresolved items share one adaptive importance ranking."""
    low = make_assessment(
        "INF1104-QUIZ-01",
        "Quiz",
        {"kind": "week", "week": 5, "start_week": None, "end_week": None, "raw": "Week 5"},
        weight=15,
    )
    high = make_assessment(
        "INF1104-EXAM-01",
        "Exam",
        {"kind": "week", "week": 5, "start_week": None, "end_week": None, "raw": "Week 5"},
        weight=50,
    )
    parent = make_assessment(
        "INF1104-PROJECT-01",
        "Project total",
        {"kind": "unknown", "week": None, "start_week": None, "end_week": None, "raw": None},
        weight=50,
        role="group",
    )
    module = make_module(
        [
            make_group("quiz", [low]),
            make_group("exam", [high]),
            make_group("project", [parent]),
        ]
    )
    unresolved_quiz = make_assessment(
        "INF1103-QUIZ-01",
        "Theory Quiz",
        {
            "kind": "unknown",
            "week": None,
            "start_week": None,
            "end_week": None,
            "raw": None,
        },
        weight=20,
    )
    unresolved_module = make_module(
        [make_group("quiz", [unresolved_quiz])]
    )
    unresolved_module["module_title"] = "INF1103"

    schedule = logic_manager.build_weekly_schedule(
        [module, unresolved_module],
        [],
    )
    week_five = schedule["weeks"][4]["items"]

    assert [item["name"] for item in week_five] == ["Exam", "Quiz"]
    assert [item["importance_rank"] for item in week_five] == [1, 3]
    assert [item["week_rank"] for item in week_five] == [1, 2]
    assert [item["priority"] for item in week_five] == ["high", "low"]
    assert schedule["unscheduled"][0]["name"] == "Theory Quiz"
    assert schedule["unscheduled"][0]["importance_rank"] == 2
    assert schedule["unscheduled"][0]["priority"] == "medium"
    assert schedule["importance"]["ranked_assessment_count"] == 3
    assert schedule["scheduled_assessment_count"] == 2
    assert schedule["unscheduled_assessment_count"] == 1


def test_duplicate_id_appends_hard_error_and_skips_the_duplicate():
    """Duplicate references are flushed through the shared error list."""
    first = make_assessment(
        "INF1104-QUIZ-01",
        "Quiz 1",
        {"kind": "week", "week": 5, "start_week": None, "end_week": None, "raw": "Week 5"},
    )
    duplicate = make_assessment(
        "INF1104-QUIZ-01",
        "Quiz duplicate",
        {"kind": "week", "week": 9, "start_week": None, "end_week": None, "raw": "Week 9"},
    )
    errors = []

    schedule = logic_manager.build_weekly_schedule(
        [make_module([make_group("quiz", [first, duplicate])])],
        errors,
    )

    assert schedule["scheduled_assessment_count"] == 1
    assert errors == [
        "Logic Manager error: Duplicate assessment_id 'INF1104-QUIZ-01'."
    ]


def test_process_payload_expands_fresh_ai_prototypes_before_scheduling():
    """Fresh AI output is normalized by Logic Manager, not AI Manager."""
    raw_module = {
        "module_title": "INF1103",
        "credit": 6,
        "ai_relevance": {
            "relevant": True,
            "detected_module_title": "INF1103",
            "reason": "Assessment information is visible.",
        },
        "ai_output": {
            "source_coverage": {"status": "appears_complete", "comment": None},
            "assessment_types": [
                {
                    "type": "tutorial",
                    "group_weight_percent": 5,
                    "group_weight_scope": "module",
                    "group_weight_scope_name": None,
                    "assessments": [
                        {
                            "name": "Tutorial",
                            "count": 2,
                            "record_role": "assessment",
                            "weight_percent": None,
                            "weight_scope": "unknown",
                            "weight_scope_name": None,
                            "schedule": {
                                "kind": "recurring",
                                "week": None,
                                "start_week": 6,
                                "end_week": 8,
                                "raw": "Weeks 6-8 excluding recess",
                            },
                            "parent_assessment": None,
                            "details": None,
                        }
                    ],
                }
            ],
            "notes": [],
            "follow_ups": [],
        },
    }

    result, errors = logic_manager.process_payload(
        {"module_count": 1, "modules": [raw_module]},
        [],
    )

    assessments = result["modules"][0]["assessment_types"][0]["assessments"]
    assert errors == []
    assert [item["name"] for item in assessments] == ["Tutorial 1", "Tutorial 2"]
    assert result["schedule"]["weeks"][5]["items"][0]["name"] == "Tutorial 1"
    assert result["schedule"]["weeks"][6]["items"] == []
    assert result["schedule"]["weeks"][7]["items"][0]["name"] == "Tutorial 2"
