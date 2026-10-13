"""Function tests for safe AI checklist and revision-plan normalization."""

import pytest

from src import logic_manager


def project_payload():
    """Return one confirmed module suitable for recommendation tests."""
    return {
        "module_count": 1,
        "modules": [
            {
                "module_title": "INF1104",
                "credit": 4,
                "assessment_types": [
                    {
                        "type": "quiz",
                        "assessments": [
                            {
                                "assessment_id": "INF1104-QUIZ-01",
                                "name": "Quiz 1",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_checklist_accepts_only_confirmed_references_and_tracks_hours():
    """Valid checklist actions retain links and receive deterministic totals."""
    recommendation = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "work_checklist",
            "summary": "Prepare early.",
            "items": [
                {
                    "title": "Review quiz topics",
                    "assessment_id": "INF1104-QUIZ-01",
                    "module_title": "INF1104",
                    "week": 4,
                    "estimated_hours": 2,
                    "priority": "high",
                    "reason": "The quiz is in the following week.",
                }
            ],
        },
        "work_checklist",
        project_payload(),
        {"available_hours_per_week": 5, "current_week": 2},
    )

    assert recommendation["weekly_hours"] == {4: 2}
    assert recommendation["items"][0]["assessment_id"] == "INF1104-QUIZ-01"
    assert recommendation["highlights"] == []


def test_recommendation_density_is_capped_for_a_scannable_ui():
    """Extra model detail is trimmed before it reaches the frontend."""
    checklist_items = [
        {
            "title": f"Review topic {position}",
            "assessment_id": None,
            "module_title": None,
            "week": position % 6 + 1,
            "estimated_hours": 0.25,
            "priority": "low",
            "reason": "Keep the topic fresh.",
        }
        for position in range(13)
    ]
    checklist = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "work_checklist",
            "summary": "Focus on the useful work.",
            "highlights": [
                {"title": "Start here", "suggestion": "One"},
                {"title": "Plan ahead", "suggestion": "Two"},
                {"title": "Keep in mind", "suggestion": "Three"},
                {"title": "Extra", "suggestion": "Four"},
            ],
            "items": checklist_items,
        },
        "work_checklist",
        project_payload(),
        {"available_hours_per_week": 5},
    )

    assert len(checklist["items"]) == 12
    assert checklist["highlights"] == [
        {"title": "Start here", "suggestion": "One"},
        {"title": "Plan ahead", "suggestion": "Two"},
        {"title": "Keep in mind", "suggestion": "Three"},
    ]

    week_items = [dict(checklist_items[0], title=f"Action {position}", week=4)
                  for position in range(4)]
    revision = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "trimester_revision_plan",
            "summary": "Prepare without filling every hour.",
            "weeks": [{"week": 4, "focus": "Quiz preparation", "items": week_items}],
        },
        "trimester_revision_plan",
        project_payload(),
        {"available_hours_per_week": 5},
    )

    assert len(revision["weeks"][0]["items"]) == 3


def test_checklist_rejects_invented_assessment_and_excess_hours():
    """AI advice cannot invent assessment links or exceed student capacity."""
    base_item = {
        "title": "Review",
        "assessment_id": "MADE-UP-ID",
        "module_title": "INF1104",
        "week": 4,
        "estimated_hours": 2,
        "priority": "high",
        "reason": "Prepare.",
    }
    with pytest.raises(ValueError, match="unknown assessment"):
        logic_manager.normalize_recommendation_output(
            {
                "recommendation_type": "work_checklist",
                "summary": "Plan.",
                "items": [base_item],
            },
            "work_checklist",
            project_payload(),
            {"available_hours_per_week": 5},
        )

    overloaded = dict(base_item)
    overloaded["assessment_id"] = "INF1104-QUIZ-01"
    overloaded["estimated_hours"] = 6
    with pytest.raises(ValueError, match="exceeds"):
        logic_manager.normalize_recommendation_output(
            {
                "recommendation_type": "work_checklist",
                "summary": "Plan.",
                "items": [overloaded],
            },
            "work_checklist",
            project_payload(),
            {"available_hours_per_week": 5},
        )


def test_revision_plan_rejects_item_in_the_wrong_week_group():
    """Nested week structure cannot disguise a conflicting item week."""
    with pytest.raises(ValueError, match="does not match"):
        logic_manager.normalize_recommendation_output(
            {
                "recommendation_type": "trimester_revision_plan",
                "summary": "Revise steadily.",
                "weeks": [
                    {
                        "week": 4,
                        "focus": "Quiz preparation",
                        "items": [
                            {
                                "title": "Review",
                                "assessment_id": "INF1104-QUIZ-01",
                                "module_title": "INF1104",
                                "week": 5,
                                "estimated_hours": 2,
                                "priority": "high",
                                "reason": "Prepare.",
                            }
                        ],
                    }
                ],
            },
            "trimester_revision_plan",
            project_payload(),
            {"available_hours_per_week": 5},
        )


def test_unknown_date_advice_is_removed_from_numbered_weeks():
    """AI preparation cannot turn an unknown assessment date into Week 1."""
    payload = project_payload()
    payload["schedule"] = {
        "recess_weeks": [7],
        "weeks": [],
        "unscheduled": [
            {"assessment_id": "INF1104-QUIZ-01"}
        ],
    }

    recommendation = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "trimester_revision_plan",
            "summary": "Prepare without inventing a deadline.",
            "weeks": [
                {
                    "week": 1,
                    "focus": "Quiz preparation",
                    "items": [
                        {
                            "title": "Review quiz topics",
                            "assessment_id": "INF1104-QUIZ-01",
                            "module_title": "INF1104",
                            "week": 1,
                            "estimated_hours": 2,
                            "priority": "medium",
                            "reason": "Prepare once the timing is confirmed.",
                        }
                    ],
                }
            ],
        },
        "trimester_revision_plan",
        payload,
        {"available_hours_per_week": 5},
    )

    assert recommendation["weeks"] == []
    assert recommendation["flexible_items"][0]["week"] is None
    assert recommendation["flexible_items"][0]["timing_status"] == "date_unknown"
    assert logic_manager.normalize_study_preferences({})["current_week"] is None


def test_recommendation_rejects_cross_module_assessment_links():
    """An assessment cannot be displayed beneath another valid module."""
    payload = project_payload()
    payload["modules"].append(
        {
            "module_title": "INF1103",
            "credit": 6,
            "assessment_types": [],
        }
    )
    with pytest.raises(ValueError, match="wrong module"):
        logic_manager.normalize_recommendation_output(
            {
                "recommendation_type": "work_checklist",
                "summary": "Plan.",
                "items": [
                    {
                        "title": "Prepare for the quiz",
                        "assessment_id": "INF1104-QUIZ-01",
                        "module_title": "INF1103",
                        "week": 4,
                        "estimated_hours": 2,
                        "priority": "high",
                        "reason": "Prepare early.",
                    }
                ],
            },
            "work_checklist",
            payload,
            {"available_hours_per_week": 5},
        )


def test_recommendation_normalizes_general_and_descriptive_module_labels():
    """Harmless model wording does not discard an otherwise valid plan."""
    recommendation = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "work_checklist",
            "summary": "Plan.",
            "items": [
                {
                    "title": "Review the trimester workload",
                    "assessment_id": None,
                    "module_title": "All modules",
                    "week": 3,
                    "estimated_hours": 1,
                    "priority": "low",
                    "reason": "Keep the plan current.",
                },
                {
                    "title": "Prepare for the quiz",
                    "assessment_id": "INF1104-QUIZ-01",
                    "module_title": "INF1104 · Programming",
                    "week": 4,
                    "estimated_hours": 2,
                    "priority": "high",
                    "reason": "Prepare early.",
                },
            ],
        },
        "work_checklist",
        project_payload(),
        {"available_hours_per_week": 5},
    )

    assert recommendation["items"][0]["module_title"] is None
    assert recommendation["items"][1]["module_title"] == "INF1104"


def test_recommendation_keeps_recess_empty_unless_assessment_is_there():
    """General AI work cannot occupy recess, but an explicit event may."""
    payload = project_payload()
    payload["schedule"] = {
        "recess_weeks": [7],
        "weeks": [{"week": 7, "items": []}],
    }
    item = {
        "title": "General revision",
        "assessment_id": None,
        "module_title": "INF1104",
        "week": 7,
        "estimated_hours": 2,
        "priority": "low",
        "reason": "Keep revising.",
    }
    with pytest.raises(ValueError, match="recess"):
        logic_manager.normalize_recommendation_output(
            {
                "recommendation_type": "work_checklist",
                "summary": "Plan.",
                "items": [item],
            },
            "work_checklist",
            payload,
            {"available_hours_per_week": 5},
        )

    payload["schedule"]["weeks"][0]["items"] = [
        {"assessment_id": "INF1104-QUIZ-01"}
    ]
    item["assessment_id"] = "INF1104-QUIZ-01"
    result = logic_manager.normalize_recommendation_output(
        {
            "recommendation_type": "work_checklist",
            "summary": "Plan.",
            "highlights": ["A quiz is explicitly scheduled during recess."],
            "items": [item],
        },
        "work_checklist",
        payload,
        {"available_hours_per_week": 5},
    )

    assert result["items"][0]["week"] == 7
    assert result["highlights"] == [
        {
            "title": "Start here",
            "suggestion": "A quiz is explicitly scheduled during recess.",
        }
    ]
