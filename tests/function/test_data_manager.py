"""Function tests for PostgreSQL persistence and revision safety."""

from src import data_manager


def module_payload(name="Quiz 1"):
    """Return one small normalized module document."""
    return {
        "module_title": "INF1104",
        "credit": 4,
        "source_coverage": {"status": "appears_complete", "comment": None},
        "assessment_types": [
            {
                "type": "quiz",
                "assessments": [
                    {"assessment_id": "INF1104-QUIZ-01", "name": name}
                ],
            }
        ],
        "notes": [],
        "follow_ups": [],
    }


def test_pipeline_rerun_activates_latest_revision(database_url):
    """A demo rerun displays its latest result while preserving history."""
    project = data_manager.create_project("Trimester 1", database_url=database_url)
    first_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    first = module_payload()
    data_manager.save_pipeline_result(
        project["id"],
        first_run,
        {"module_count": 1, "modules": [first], "schedule": {}},
        [],
        source_hashes={"INF1104": "hash-one"},
        prompt_version="v1",
        model_name="qwen",
        database_url=database_url,
    )

    second_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    second = module_payload("Quiz updated")
    data_manager.save_pipeline_result(
        project["id"],
        second_run,
        {"module_count": 1, "modules": [second], "schedule": {}},
        [],
        source_hashes={"INF1104": "hash-two"},
        prompt_version="v1",
        model_name="qwen",
        database_url=database_url,
    )

    assert data_manager.get_confirmed_modules(project["id"], database_url) == [second]
    assert data_manager.confirm_module_revision(
        project["id"], "INF1104", 1, database_url
    )
    assert data_manager.get_confirmed_modules(project["id"], database_url) == [first]


def test_recommendation_is_saved_separately_from_module_facts(database_url):
    """Study advice has its own record and never mutates confirmed modules."""
    project = data_manager.create_project("Planning", database_url=database_url)
    module = module_payload()
    saved = data_manager.save_recommendation(
        project["id"],
        "work_checklist",
        [module],
        {"available_hours_per_week": 6},
        {"recommendation_type": "work_checklist", "items": []},
        "v1",
        "qwen",
        database_url,
    )

    assert saved["status"] == "candidate"
    assert saved["recommendation_payload"]["recommendation_type"] == "work_checklist"
    assert data_manager.list_recommendations(project["id"], database_url)[0]["id"] == saved["id"]


def test_student_edit_creates_confirmed_revision_and_preserves_history(database_url):
    """Manual correction activates a new revision rather than overwriting AI data."""
    project = data_manager.create_project("Editing", database_url=database_url)
    run_id = data_manager.start_pipeline_run(project["id"], 1, database_url)
    original = module_payload()
    data_manager.save_pipeline_result(
        project["id"],
        run_id,
        {"module_count": 1, "modules": [original], "schedule": {}},
        [],
        prompt_version="v1",
        model_name="qwen",
        database_url=database_url,
    )
    edited = module_payload("Quiz corrected by student")

    saved = data_manager.save_confirmed_module_edit(
        project["id"], edited, database_url
    )

    assert saved["revision"] == 2
    assert saved["model_name"] == "student-edit"
    assert data_manager.get_confirmed_modules(project["id"], database_url) == [edited]
